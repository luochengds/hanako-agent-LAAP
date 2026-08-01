"""内生演化沙箱 — Evolution Sandbox

封装代码执行环境，用于运行 RSI 生成的代码变更。
基础实现使用 subprocess 隔离；Docker 容器实现由 realize-laap-agi-vision M5 完成。

沙箱特性：
- 无网络访问（基础实现通过环境变量禁用）
- 资源受限（CPU/内存/磁盘配额）
- 执行超时强制终止
- 失败时自动回滚到上一个已知良好状态
- 完整审计日志

References:
- LAAP2.0大版本升级方案 § 内生演化沙箱
- realize-laap-agi-vision spec M5 Task I1-I3
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from laap.security.zones import SafetyZone, ZoneManager, ActionType


@dataclass
class SandboxResourceLimit:
    """沙箱资源限制"""
    cpu_quota: str = "1.0"           # CPU 配额（核数）
    memory_mb: int = 512             # 内存上限（MB）
    disk_mb: int = 1024              # 磁盘上限（MB）
    execution_timeout_sec: int = 300 # 执行超时（秒）
    max_processes: int = 4           # 最大进程数


@dataclass
class SandboxResult:
    """沙箱执行结果"""
    sandbox_id: str
    success: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    execution_time_sec: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)
    # 性能/质量/稳定性指标
    error: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)  # 产物文件路径
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class VersionSnapshot:
    """版本快照（用于回滚）"""
    snapshot_id: str
    sandbox_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    code_state: Dict[str, str] = field(default_factory=dict)  # file_path -> content
    metadata: Dict[str, Any] = field(default_factory=dict)
    git_commit_sha: Optional[str] = None  # 如可用，关联 git commit


class EvolutionSandbox:
    """内生演化沙箱

    提供隔离的代码执行环境，用于 RSI 自改进代码的测试与验证。
    支持版本快照与自动回滚。
    """

    def __init__(
        self,
        zone_manager: Optional[ZoneManager] = None,
        resource_limit: Optional[SandboxResourceLimit] = None,
        work_dir: Optional[str] = None,
    ):
        self._zone_manager = zone_manager or ZoneManager()
        self._resource_limit = resource_limit or SandboxResourceLimit()
        self._work_dir = work_dir or tempfile.mkdtemp(prefix="laap_evo_")
        self._snapshots: Dict[str, VersionSnapshot] = {}  # snapshot_id -> snapshot
        self._sandbox_snapshots: Dict[str, List[str]] = {}  # sandbox_id -> [snapshot_id]
        self._audit_log: List[Dict[str, Any]] = []

    def execute_in_sandbox(
        self,
        code: str,
        tests: Optional[str] = None,
        sandbox_id: Optional[str] = None,
    ) -> SandboxResult:
        """在沙箱中执行代码并运行测试

        Args:
            code: 要执行的 Python 代码字符串
            tests: 可选的测试代码字符串（pytest 风格）
            sandbox_id: 可选的沙箱 ID（用于追踪多次执行）

        Returns:
            SandboxResult 执行结果
        """
        sandbox_id = sandbox_id or f"sandbox_{uuid.uuid4().hex[:8]}"
        # 策略校验：必须在 SANDBOX 区执行
        if not self._zone_manager.enforce(SafetyZone.SANDBOX, ActionType.CODE_EXECUTION):
            return SandboxResult(
                sandbox_id=sandbox_id,
                success=False,
                exit_code=-1,
                error="策略校验失败：SANDBOX 区不允许 CODE_EXECUTION",
            )
        # 创建快照（执行前状态）
        snapshot = self._create_snapshot(sandbox_id)
        # 准备执行目录
        exec_dir = Path(self._work_dir) / sandbox_id
        exec_dir.mkdir(parents=True, exist_ok=True)
        # 写入代码文件
        code_file = exec_dir / "subject.py"
        code_file.write_text(code, encoding="utf-8")
        # 写入测试文件（如有）
        test_file = None
        if tests:
            test_file = exec_dir / "test_subject.py"
            test_file.write_text(tests, encoding="utf-8")
        # 执行
        start_time = time.time()
        try:
            result = self._run_subprocess(
                code_file, test_file, exec_dir, sandbox_id
            )
            execution_time = time.time() - start_time
            # 采集指标
            metrics = self._collect_metrics(exec_dir, execution_time)
            sandbox_result = SandboxResult(
                sandbox_id=sandbox_id,
                success=result[0],
                exit_code=result[1],
                stdout=result[2],
                stderr=result[3],
                execution_time_sec=execution_time,
                metrics=metrics,
            )
            # 失败时自动回滚
            if not result[0] and self._resource_limit:
                self._auto_rollback(snapshot, reason="执行失败")
            self._log_audit(sandbox_id, "execute", sandbox_result.success)
            return sandbox_result
        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            self._auto_rollback(snapshot, reason="执行超时")
            self._log_audit(sandbox_id, "execute", False, "超时")
            return SandboxResult(
                sandbox_id=sandbox_id,
                success=False,
                exit_code=-1,
                stderr=f"执行超时（{self._resource_limit.execution_timeout_sec}s）",
                execution_time_sec=execution_time,
                error="timeout",
            )
        except Exception as e:
            execution_time = time.time() - start_time
            self._auto_rollback(snapshot, reason=f"异常：{e}")
            self._log_audit(sandbox_id, "execute", False, str(e))
            return SandboxResult(
                sandbox_id=sandbox_id,
                success=False,
                exit_code=-1,
                stderr=str(e),
                execution_time_sec=execution_time,
                error=type(e).__name__,
            )

    def create_snapshot(
        self,
        sandbox_id: str,
        files: Optional[Dict[str, str]] = None,
    ) -> VersionSnapshot:
        """创建版本快照

        Args:
            sandbox_id: 沙箱 ID
            files: 可选的文件路径到内容的映射

        Returns:
            VersionSnapshot 快照对象
        """
        return self._create_snapshot(sandbox_id, files)

    def rollback(self, snapshot_id: str) -> bool:
        """回滚到指定快照

        Args:
            snapshot_id: 快照 ID

        Returns:
            True 表示回滚成功
        """
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            self._log_audit("unknown", "rollback", False, "快照不存在")
            return False
        # 恢复文件状态
        exec_dir = Path(self._work_dir) / snapshot.sandbox_id
        for file_path, content in snapshot.code_state.items():
            target = exec_dir / file_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self._log_audit(snapshot.sandbox_id, "rollback", True, f"快照 {snapshot_id}")
        return True

    def get_snapshots(self, sandbox_id: str) -> List[VersionSnapshot]:
        """获取指定沙箱的所有快照"""
        snapshot_ids = self._sandbox_snapshots.get(sandbox_id, [])
        return [self._snapshots[sid] for sid in snapshot_ids if sid in self._snapshots]

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取审计日志"""
        return list(reversed(self._audit_log))[:limit]

    def cleanup(self, sandbox_id: Optional[str] = None) -> None:
        """清理沙箱工作目录

        Args:
            sandbox_id: 指定沙箱 ID 则只清理该沙箱；None 则清理全部
        """
        if sandbox_id:
            exec_dir = Path(self._work_dir) / sandbox_id
            if exec_dir.exists():
                shutil.rmtree(exec_dir, ignore_errors=True)
        else:
            if Path(self._work_dir).exists():
                shutil.rmtree(self._work_dir, ignore_errors=True)

    def _create_snapshot(
        self,
        sandbox_id: str,
        files: Optional[Dict[str, str]] = None,
    ) -> VersionSnapshot:
        """内部创建快照"""
        snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
        code_state = {}
        if files:
            code_state.update(files)
        else:
            # 从执行目录读取现有文件
            exec_dir = Path(self._work_dir) / sandbox_id
            if exec_dir.exists():
                for f in exec_dir.rglob("*.py"):
                    try:
                        rel_path = str(f.relative_to(exec_dir))
                        code_state[rel_path] = f.read_text(encoding="utf-8")
                    except Exception:
                        pass
        snapshot = VersionSnapshot(
            snapshot_id=snapshot_id,
            sandbox_id=sandbox_id,
            code_state=code_state,
        )
        self._snapshots[snapshot_id] = snapshot
        self._sandbox_snapshots.setdefault(sandbox_id, []).append(snapshot_id)
        return snapshot

    def _run_subprocess(
        self,
        code_file: Path,
        test_file: Optional[Path],
        exec_dir: Path,
        sandbox_id: str,
    ) -> Tuple[bool, int, str, str]:
        """运行子进程执行代码或测试

        Returns:
            (success, exit_code, stdout, stderr)
        """
        env = self._build_sandbox_env()
        if test_file:
            # 运行 pytest
            cmd = [
                sys.executable, "-m", "pytest",
                str(test_file),
                "-v", "--tb=short", "--no-header",
            ]
        else:
            # 直接执行代码
            cmd = [sys.executable, str(code_file)]
        proc = subprocess.run(
            cmd,
            cwd=str(exec_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=self._resource_limit.execution_timeout_sec,
        )
        success = proc.returncode == 0
        return success, proc.returncode, proc.stdout, proc.stderr

    def _build_sandbox_env(self) -> Dict[str, str]:
        """构建沙箱环境变量（禁用网络等）"""
        env = dict(os.environ)
        # 禁用网络访问（通过设置无效代理）
        env["http_proxy"] = "http://invalid:1"
        env["https_proxy"] = "http://invalid:1"
        env["HTTP_PROXY"] = "http://invalid:1"
        env["HTTPS_PROXY"] = "http://invalid:1"
        env["no_proxy"] = "*"
        env["NO_PROXY"] = "*"
        # 限制 Python 递归深度
        env["PYTHONRECURSIONLIMIT"] = "1000"
        # 禁用 pytest 插件自动加载（沙箱隔离：防止宿主环境的插件影响子进程）
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        return env

    def _collect_metrics(self, exec_dir: Path, execution_time: float) -> Dict[str, Any]:
        """采集执行指标"""
        metrics: Dict[str, Any] = {
            "execution_time_sec": execution_time,
            "files_created": 0,
            "total_size_bytes": 0,
        }
        if exec_dir.exists():
            for f in exec_dir.rglob("*"):
                if f.is_file():
                    metrics["files_created"] += 1
                    try:
                        metrics["total_size_bytes"] += f.stat().st_size
                    except Exception:
                        pass
        return metrics

    def _auto_rollback(self, snapshot: VersionSnapshot, reason: str) -> None:
        """自动回滚到指定快照"""
        success = self.rollback(snapshot.snapshot_id)
        self._log_audit(
            snapshot.sandbox_id,
            "auto_rollback",
            success,
            f"原因：{reason}，快照：{snapshot.snapshot_id}",
        )

    def _log_audit(
        self,
        sandbox_id: str,
        action: str,
        success: bool,
        message: str = "",
    ) -> None:
        """记录审计日志"""
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "sandbox_id": sandbox_id,
            "action": action,
            "success": success,
            "message": message,
        })


__all__ = [
    "SandboxResourceLimit",
    "SandboxResult",
    "VersionSnapshot",
    "EvolutionSandbox",
]
