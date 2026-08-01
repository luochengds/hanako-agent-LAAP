"""P2-skill-packs: 技能包打包 / 导入 / 安装 / 卸载管理器.

技能包 = component.tsx + prompt.md + tools.json + manifest.json 的 zip 复合产物,
可在不同 Hanako 实例间导出 / 导入, 并能注册到指定 agent 的 vault
``installed_skills`` 表（幂等 upsert / delete / select）.

复用现有模块:
- ``laap.skills.versioning``: Version.parse / Version.compatible_with / check_compatibility
- ``laap.memory_vault.vault_manager``: vault_manager._get_vault + _open_vault_connection
  （参考 sidecar.py L902-945 witness_trail_local 建表模式）

幂等保证:
- install 同一 (agent_name, skill_id) 重复调用 → INSERT OR REPLACE, 不报错
- uninstall 不存在的记录 → 静默成功
- export_pack 输出 zip 存在 → 覆盖
- import_pack 目标目录存在 → 合并覆盖
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from laap.skills.versioning import Version, check_compatibility

logger = logging.getLogger("laap.skills.pack_manager")

# ── 路径常量 ──────────────────────────────────────────────────

SKILLS_DIR = Path(__file__).resolve().parent
"""laap/skills/ 根目录, 技能包源文件存放处."""

DEFAULT_OUTPUT_DIR = SKILLS_DIR / "_exports"
"""export_pack 默认输出目录."""

# ── SubTask 2.1: SkillPackManifest dataclass ─────────────────


@dataclass
class SkillPackManifest:
    """技能包 manifest schema (spec L72 / L88 / L250-258).

    字段:
        name: 技能包唯一标识 (slug, e.g. "aris-code-review")
        version: semver-ish 字符串 (e.g. "1.2.0"), 由 versioning.Version 解析
        component: 可选, 组件 tsx 文件名 (相对 zip 根). None 表示纯提示词技能.
        prompt: 可选, 提示词 md 文件名 (相对 zip 根).
        tools: 工具名列表 (MCP 工具绑定), 空列表表示无工具绑定
        dependencies: 可选, 依赖的其他 skill_id 列表
        author: 作者字符串
        charter_compatible: 是否通过宪章八条检查 (默认 True)
        description: 可选, 简短描述 (UI 显示)
    """

    name: str
    version: str = "0.1.0"
    component: Optional[str] = None
    prompt: Optional[str] = None
    tools: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    author: str = ""
    charter_compatible: bool = True
    description: str = ""

    # ── 序列化 / 反序列化 ──

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可写入 manifest.json 的 dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillPackManifest":
        """从 dict 反序列化 (manifest.json 解析后).

        宽容地忽略未知字段; 缺失字段使用 dataclass 默认值.
        """
        if not isinstance(data, dict):
            raise ValueError(f"manifest must be a dict, got {type(data).__name__}")
        return cls(
            name=str(data.get("name", "")),
            version=str(data.get("version", "0.1.0")),
            component=data.get("component") or None,
            prompt=data.get("prompt") or None,
            tools=list(data.get("tools", []) or []),
            dependencies=list(data.get("dependencies", []) or []),
            author=str(data.get("author", "")),
            charter_compatible=bool(data.get("charter_compatible", True)),
            description=str(data.get("description", "")),
        )

    # ── 校验 ──

    def validate(self) -> List[str]:
        """校验 manifest 字段合法性, 返回错误信息列表 (空列表 = 通过).

        校验项:
        - name 非空且为 slug 形式 (a-z0-9-_)
        - version 可被 Version.parse 解析
        - component / prompt 若非 None 必须是相对文件名 (无路径分隔符)
        - tools / dependencies 元素均为字符串
        """
        errors: List[str] = []

        if not self.name:
            errors.append("name is required")
        elif not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.name):
            errors.append(
                f"name '{self.name}' must be a slug (lowercase [a-z0-9_-])"
            )

        v = Version.parse(self.version)
        if v is None:
            errors.append(f"version '{self.version}' is not a valid semver-ish string")

        for fld, val in (("component", self.component), ("prompt", self.prompt)):
            if val is not None and not isinstance(val, str):
                errors.append(f"{fld} must be a string or null")
            elif val is not None and (os.sep in val or "/" in val or "\\" in val):
                errors.append(
                    f"{fld} '{val}' must be a bare filename (no path separators)"
                )

        if not isinstance(self.tools, list) or not all(
            isinstance(t, str) for t in self.tools
        ):
            errors.append("tools must be a list of strings")

        if not isinstance(self.dependencies, list) or not all(
            isinstance(d, str) for d in self.dependencies
        ):
            errors.append("dependencies must be a list of strings")

        if not isinstance(self.author, str):
            errors.append("author must be a string")

        if not isinstance(self.charter_compatible, bool):
            errors.append("charter_compatible must be a bool")

        return errors


# ── SubTask 2.2: 打包 / 导入 / 安装 / 卸载 ────────────────────

# 技能包内必须包含的文件名 (zip 根级别)
MANIFEST_FILENAME = "manifest.json"

# 打包时尝试收集的附加文件 (存在则打包, 不存在跳过)
PACK_BUNDLED_FILES = ("component.tsx", "prompt.md", "tools.json")

# SkillManifest 默认放置位置 (相对 skill_id 目录)
DEFAULT_MANIFEST_PATH_TEMPLATE = "{skill_id}/manifest.json"


def _skill_dir(skill_id: str) -> Path:
    """返回 laap/skills/{skill_id}/ 路径 (不检查存在性)."""
    return SKILLS_DIR / skill_id


def _read_manifest(skill_dir: Path) -> SkillPackManifest:
    """从 skill_dir 读取 manifest.json 并校验.

    Raises:
        FileNotFoundError: manifest.json 不存在
        ValueError: manifest 校验失败
    """
    manifest_path = skill_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"manifest.json not found in skill dir {skill_dir}"
        )
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"manifest.json invalid JSON: {e}") from e
    manifest = SkillPackManifest.from_dict(data)
    errors = manifest.validate()
    if errors:
        raise ValueError(
            f"manifest validation failed for '{manifest.name}': {'; '.join(errors)}"
        )
    return manifest


def _ensure_output_dir(output_dir: Optional[Path | str]) -> Path:
    """确保 output_dir 存在并返回 Path."""
    out = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    return out


def export_pack(
    skill_id: str,
    output_dir: Optional[Path | str] = None,
) -> str:
    """把 laap/skills/{skill_id}/ 打包为 zip (含 manifest + 附加文件).

    Args:
        skill_id: 技能 ID (laap/skills/ 下的子目录名)
        output_dir: 输出目录, None 时使用 DEFAULT_OUTPUT_DIR

    Returns:
        zip 文件绝对路径字符串

    Raises:
        FileNotFoundError: skill_id 目录或 manifest.json 不存在
        ValueError: manifest 校验失败
    """
    src_dir = _skill_dir(skill_id)
    if not src_dir.is_dir():
        raise FileNotFoundError(f"skill directory not found: {src_dir}")

    manifest = _read_manifest(src_dir)
    # 复用 versioning.py: 版本号必须可解析 (validate 已校验, 此处再确认)
    v = Version.parse(manifest.version)
    if v is None:  # pragma: no cover - validate() 已拦截
        raise ValueError(f"invalid version '{manifest.version}'")

    out_dir = _ensure_output_dir(output_dir)
    zip_name = f"{manifest.name}-v{manifest.version}.zip"
    zip_path = out_dir / zip_name

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # manifest.json 一定打包
        zf.write(src_dir / MANIFEST_FILENAME, MANIFEST_FILENAME)
        # 附加文件: 存在则打包
        for fname in PACK_BUNDLED_FILES:
            fpath = src_dir / fname
            if fpath.is_file():
                zf.write(fpath, fname)
        # 如果 manifest.component / prompt 指向其他文件名, 也尝试打包
        for extra in (manifest.component, manifest.prompt):
            if extra and extra not in PACK_BUNDLED_FILES:
                fpath = src_dir / extra
                if fpath.is_file():
                    zf.write(fpath, extra)

    logger.info(
        f"export_pack: '{skill_id}' v{manifest.version} -> {zip_path} "
        f"({zip_path.stat().st_size} bytes)"
    )
    return str(zip_path)


def import_pack(
    zip_path: Path | str,
    output_dir: Optional[Path | str] = None,
) -> str:
    """把 zip 解压到 output_dir/{skill_id}/, 校验 manifest.

    Args:
        zip_path: zip 文件路径
        output_dir: 解压目标父目录, None 时使用 laap/skills/

    Returns:
        skill_id (从 manifest.json 读取)

    Raises:
        FileNotFoundError: zip 不存在
        ValueError: zip 内 manifest.json 缺失 / 校验失败
    """
    zip_p = Path(zip_path)
    if not zip_p.is_file():
        raise FileNotFoundError(f"zip file not found: {zip_p}")

    out_root = Path(output_dir) if output_dir else SKILLS_DIR
    out_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_p, "r") as zf:
        names = zf.namelist()
        if MANIFEST_FILENAME not in names:
            raise ValueError(
                f"zip '{zip_p.name}' missing {MANIFEST_FILENAME}"
            )
        # 读取 manifest 校验
        with zf.open(MANIFEST_FILENAME) as f:
            data = json.loads(f.read().decode("utf-8"))
        manifest = SkillPackManifest.from_dict(data)
        errors = manifest.validate()
        if errors:
            raise ValueError(
                f"manifest validation failed: {'; '.join(errors)}"
            )

        # 复用 versioning.py: 版本号必须可解析
        v = Version.parse(manifest.version)
        if v is None:  # pragma: no cover
            raise ValueError(f"invalid version '{manifest.version}'")

        target_dir = out_root / manifest.name
        target_dir.mkdir(parents=True, exist_ok=True)
        # 解压所有文件到 target_dir (覆盖)
        for name in names:
            # 防止 zip slip: 不允许绝对路径或 ..
            if name.startswith("/") or ".." in Path(name).parts:
                logger.warning(f"import_pack: skip unsafe path '{name}'")
                continue
            zf.extract(name, target_dir)

    logger.info(f"import_pack: '{manifest.name}' v{manifest.version} -> {target_dir}")
    return manifest.name


# ── 安装 / 卸载 / 列表 (vault installed_skills 表) ────────────

def _get_vault_conn(agent_name: str):
    """获取 agent vault 的打开连接 (幂等: 必要时自动 init).

    复用 vault_manager._get_vault + _open_vault_connection 模式.

    Returns:
        (conn, db_path, key_hex)
    """
    from laap.memory_vault.vault_manager import (
        vault_manager, _open_vault_connection,
    )
    db_path, key_hex = vault_manager._get_vault(agent_name)
    conn = _open_vault_connection(db_path, key_hex)
    return conn, db_path, key_hex


def _ensure_installed_skills_table(conn) -> None:
    """幂等创建 installed_skills 表 (参考 sidecar.py witness_trail_local 模式)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS installed_skills (
            skill_id           TEXT NOT NULL,
            agent_name         TEXT NOT NULL,
            version            TEXT NOT NULL,
            author             TEXT DEFAULT '',
            charter_compatible INTEGER DEFAULT 1,
            installed_at       TEXT NOT NULL,
            PRIMARY KEY (agent_name, skill_id)
        );
        CREATE INDEX IF NOT EXISTS idx_installed_skills_agent
            ON installed_skills(agent_name);
    """)


def install(agent_name: str, skill_id: str) -> Dict[str, Any]:
    """把 skill_id 注册到 agent_name 的 vault installed_skills 表.

    幂等: 同一 (agent_name, skill_id) 重复调用 → INSERT OR REPLACE, 不报错.

    Args:
        agent_name: 目标 agent 名称
        skill_id: 要安装的技能 ID (laap/skills/{skill_id}/ 必须存在)

    Returns:
        ``{"installed": True, "skill_id": str, "version": str, "agent_name": str}``

    Raises:
        FileNotFoundError: skill_id 目录或 manifest.json 不存在
        ValueError: manifest 校验失败
    """
    skill_dir = _skill_dir(skill_id)
    manifest = _read_manifest(skill_dir)

    conn, _db_path, _key = _get_vault_conn(agent_name)
    try:
        _ensure_installed_skills_table(conn)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO installed_skills
               (skill_id, agent_name, version, author,
                charter_compatible, installed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                manifest.name,
                agent_name,
                manifest.version,
                manifest.author,
                1 if manifest.charter_compatible else 0,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(
        f"install: skill '{manifest.name}' v{manifest.version} "
        f"-> agent '{agent_name}'"
    )
    return {
        "installed": True,
        "skill_id": manifest.name,
        "version": manifest.version,
        "agent_name": agent_name,
    }


def uninstall(agent_name: str, skill_id: str) -> Dict[str, Any]:
    """从 agent_name 的 vault installed_skills 表删除 skill_id.

    幂等: 不存在的记录 → 静默成功.

    Args:
        agent_name: 目标 agent 名称
        skill_id: 要卸载的技能 ID

    Returns:
        ``{"uninstalled": True, "skill_id": str, "agent_name": str}``
    """
    conn, _db_path, _key = _get_vault_conn(agent_name)
    try:
        _ensure_installed_skills_table(conn)
        conn.execute(
            "DELETE FROM installed_skills WHERE agent_name = ? AND skill_id = ?",
            (agent_name, skill_id),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(
        f"uninstall: skill '{skill_id}' removed from agent '{agent_name}'"
    )
    return {
        "uninstalled": True,
        "skill_id": skill_id,
        "agent_name": agent_name,
    }


def list_installed(agent_name: str) -> List[Dict[str, Any]]:
    """查询 agent_name 的 vault installed_skills 表.

    Args:
        agent_name: 目标 agent 名称

    Returns:
        已安装技能列表, 每项 ``{skill_id, agent_name, version, author,
        charter_compatible, installed_at}``. 空列表 = 未安装任何技能.
    """
    conn, _db_path, _key = _get_vault_conn(agent_name)
    try:
        _ensure_installed_skills_table(conn)
        rows = conn.execute(
            """SELECT skill_id, agent_name, version, author,
                      charter_compatible, installed_at
               FROM installed_skills
               WHERE agent_name = ?
               ORDER BY installed_at DESC""",
            (agent_name,),
        ).fetchall()
        return [
            {
                "skill_id": row["skill_id"],
                "agent_name": row["agent_name"],
                "version": row["version"],
                "author": row["author"] or "",
                "charter_compatible": bool(row["charter_compatible"]),
                "installed_at": row["installed_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def list_available() -> List[Dict[str, Any]]:
    """扫描 laap/skills/ 下所有带 manifest.json 的子目录, 返回可用技能列表.

    Returns:
        每项 ``{skill_id, version, author, charter_compatible, description}``.
        扫描失败 (无 manifest / 校验失败) 的目录被跳过.
    """
    available: List[Dict[str, Any]] = []
    for child in SKILLS_DIR.iterdir():
        if not child.is_dir():
            continue
        if child.name.startswith("_") or child.name.startswith("."):
            continue
        manifest_path = child / MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue
        try:
            manifest = _read_manifest(child)
            available.append(
                {
                    "skill_id": manifest.name,
                    "version": manifest.version,
                    "author": manifest.author,
                    "charter_compatible": manifest.charter_compatible,
                    "description": manifest.description,
                }
            )
        except Exception as e:
            logger.warning(f"list_available: skip '{child.name}': {e}")
    return available


def is_compatible(skill_id: str, host_version: str) -> bool:
    """检查 skill_id 是否与 host_version 兼容 (复用 versioning.check_compatibility).

    Args:
        skill_id: 技能 ID
        host_version: 宿主版本字符串 (e.g. "1.0.0")

    Returns:
        兼容 = True; 不兼容 / 解析失败 = False
    """
    try:
        manifest = _read_manifest(_skill_dir(skill_id))
        return check_compatibility(manifest.version, host_version)
    except Exception:
        return False
