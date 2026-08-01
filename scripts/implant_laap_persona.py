#!/usr/bin/env python3
"""LAAP 人格模板深度植入脚本.

把 LAAP 专属的人格模板（yuan/ishiki/identity/pinned）按两种方案植入：

方案 A — 产品模板层（影响所有新创建/重置的 agent）:
    将模板写入 hanako/lib/{yuan,identity-templates,ishiki-templates,public-ishiki-templates}/
    并在 hanako/lib 生成 pinned.example.md 的 LAAP 版本.

方案 B — 单个 agent 实例层（立即影响当前 agent）:
    将 identity.md / ishiki.md / pinned.md 写入指定 agentDir.

用法:
    # 方案 A: 植入产品模板
    python scripts/implant_laap_persona.py --mode product

    # 方案 B: 植入指定 agent 目录
    python scripts/implant_laap_persona.py --mode agent --agent-dir "%USERPROFILE%\\.hana\\agents\\aris"

    # 同时执行 A + B
    python scripts/implant_laap_persona.py --mode both --agent-dir "%USERPROFILE%\\.hana\\agents\\aris"
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Dict, List

# ── 路径 ──────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "hanako" / "lib" / "laap-persona"
HANAKO_LIB = REPO_ROOT / "hanako" / "lib"

# yuan 模板（agent.ts 读取 productDir/yuan/{yuan}.md）
YUAN_TARGET = HANAKO_LIB / "yuan" / "laap.md"
YUAN_EN_TARGET = HANAKO_LIB / "yuan" / "en" / "laap.md"

# identity / ishiki / public-ishiki 模板
IDENTITY_TARGET = HANAKO_LIB / "identity-templates" / "laap.md"
IDENTITY_EN_TARGET = HANAKO_LIB / "identity-templates" / "en" / "laap.md"
ISHIKI_TARGET = HANAKO_LIB / "ishiki-templates" / "laap.md"
ISHIKI_EN_TARGET = HANAKO_LIB / "ishiki-templates" / "en" / "laap.md"
PUBLIC_ISHIKI_TARGET = HANAKO_LIB / "public-ishiki-templates" / "laap.md"
PUBLIC_ISHIKI_EN_TARGET = HANAKO_LIB / "public-ishiki-templates" / "en" / "laap.md"

PINNED_EXAMPLE_TARGET = HANAKO_LIB / "pinned.example.md"

AGENT_FILES: Dict[str, str] = {
    "identity.md": "laap.md",
    "ishiki.md": "ishiki.md",
    "pinned.md": "pinned.md",
}


def ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def copy(src: Path, dst: Path) -> None:
    ensure_dir(dst)
    shutil.copy2(src, dst)
    print(f"  [OK] {src.name} -> {dst}")


def implant_product() -> None:
    """方案 A: 植入产品模板目录."""
    print("[方案 A] 植入 hanako/lib/ 产品模板 ...")
    if not SOURCE_DIR.is_dir():
        raise RuntimeError(f"源模板目录不存在: {SOURCE_DIR}")

    copy(SOURCE_DIR / "yuan.md", YUAN_TARGET)
    copy(SOURCE_DIR / "yuan.md", YUAN_EN_TARGET)
    copy(SOURCE_DIR / "laap.md", IDENTITY_TARGET)
    copy(SOURCE_DIR / "laap.md", IDENTITY_EN_TARGET)
    copy(SOURCE_DIR / "ishiki.md", ISHIKI_TARGET)
    copy(SOURCE_DIR / "ishiki.md", ISHIKI_EN_TARGET)
    copy(SOURCE_DIR / "ishiki.md", PUBLIC_ISHIKI_TARGET)
    copy(SOURCE_DIR / "ishiki.md", PUBLIC_ISHIKI_EN_TARGET)
    copy(SOURCE_DIR / "pinned.md", PINNED_EXAMPLE_TARGET)
    print("[方案 A] 完成\n")


def implant_agent(agent_dir: Path, backup: bool = True) -> None:
    """方案 B: 植入单个 agent 目录."""
    print(f"[方案 B] 植入 agent 目录: {agent_dir} ...")
    if not agent_dir.is_dir():
        raise RuntimeError(f"agent 目录不存在: {agent_dir}")

    for dst_name, src_name in AGENT_FILES.items():
        src = SOURCE_DIR / src_name
        dst = agent_dir / dst_name
        if dst.is_file() and backup:
            bak = agent_dir / f"{dst_name}.bak.{int(__import__('time').time())}"
            shutil.copy2(dst, bak)
            print(f"  [INFO] 已备份 {dst} -> {bak.name}")
        copy(src, dst)
    print("[方案 B] 完成\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="LAAP 人格模板深度植入")
    parser.add_argument(
        "--mode",
        choices=["product", "agent", "both"],
        required=True,
        help="植入模式: product=产品模板, agent=单个 agent, both=两者都执行",
    )
    parser.add_argument(
        "--agent-dir",
        type=Path,
        help="方案 B 所需 agent 目录路径（如 ~/.hana/agents/aris）",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="方案 B 不备份原文件（默认备份）",
    )
    args = parser.parse_args()

    if args.mode in ("agent", "both") and not args.agent_dir:
        parser.error("--mode agent/both 时必须提供 --agent-dir")

    if args.mode in ("product", "both"):
        implant_product()

    if args.mode in ("agent", "both"):
        implant_agent(args.agent_dir, backup=not args.no_backup)

    print("LAAP 人格模板植入完成。")
    if args.mode in ("product", "both"):
        print("  新 agent 创建/重置时选择 yuan='laap' 即可生效。")
    if args.mode in ("agent", "both"):
        print(f"  当前 agent {args.agent_dir} 已立即生效，重启对话后读取新 pinned/identity/ishiki。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
