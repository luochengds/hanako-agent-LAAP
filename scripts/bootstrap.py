#!/usr/bin/env python3
"""Prepare the LAAP + Hanako source checkout.

This bootstrapper installs project dependencies only. It never installs or
configures API keys, Hermes, Agent-Reach, or Swarm automatically.
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import venv
from pathlib import Path

MIN_PYTHON = (3, 11)
MIN_NODE = (24, 12, 0)
MAX_NODE_EXCLUSIVE = (25, 0, 0)


def version_tuple(value: str, width: int = 3) -> tuple[int, ...]:
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
    if not match:
        return tuple()
    values = [int(group or 0) for group in match.groups()]
    return tuple(values[:width])


def run(command: list[str], cwd: Path, dry_run: bool = False) -> None:
    print(f"[bootstrap] {' '.join(command)}  (cwd={cwd})")
    if dry_run:
        return
    subprocess.run(command, cwd=cwd, check=True)


def locate_node() -> str:
    configured = (os.environ.get("LAAP_NODE") or "").strip()
    if configured:
        return configured
    return shutil.which("node") or "node"


def locate_npm() -> str:
    configured = (os.environ.get("LAAP_NPM") or "").strip()
    if configured:
        return configured
    return shutil.which("npm") or ("npm.cmd" if os.name == "nt" else "npm")


def check_python() -> None:
    if sys.version_info[:2] < MIN_PYTHON:
        raise SystemExit(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required; "
            f"found {platform.python_version()}"
        )
    print(f"[bootstrap] Python {platform.python_version()} OK")


def ensure_python(project_root: Path, with_dev: bool, dry_run: bool, skip_python: bool) -> None:
    if skip_python:
        print("[bootstrap] Python dependency installation skipped")
        return

    check_python()
    venv_dir = Path(os.environ.get("LAAP_VENV", project_root / ".venv"))
    if not venv_dir.is_absolute():
        venv_dir = project_root / venv_dir
    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not venv_python.exists():
        print(f"[bootstrap] creating virtual environment: {venv_dir}")
        if not dry_run:
            venv.EnvBuilder(with_pip=True, clear=False).create(venv_dir)

    pip = str(venv_python)
    requirements = project_root / "requirements.txt"
    if not requirements.exists():
        raise SystemExit(f"Missing {requirements}")
    run([pip, "-m", "pip", "install", "-U", "pip"], project_root, dry_run)
    run([pip, "-m", "pip", "install", "-r", str(requirements)], project_root, dry_run)
    if with_dev:
        run([pip, "-m", "pip", "install", "-e", ".[dev]"], project_root, dry_run)
    print(f"[bootstrap] Python environment ready: {venv_dir}")


def ensure_node(project_root: Path, dry_run: bool, skip_node: bool) -> None:
    if skip_node:
        print("[bootstrap] Node dependency installation skipped")
        return

    node = locate_node()
    npm = locate_npm()
    try:
        node_version_text = subprocess.check_output([node, "--version"], text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("Node.js is required; install Node 24.12.x–24.x before rerunning.") from exc
    node_version = version_tuple(node_version_text)
    if not node_version or not (MIN_NODE <= node_version < MAX_NODE_EXCLUSIVE):
        raise SystemExit(
            f"Node.js 24.12.x–24.x is required; found {node_version_text}."
        )
    print(f"[bootstrap] Node {node_version_text} OK")

    hanako_dir = project_root / "hanako"
    lockfile = hanako_dir / "package-lock.json"
    package_json = hanako_dir / "package.json"
    if not package_json.exists() or not lockfile.exists():
        raise SystemExit("hanako/package.json or hanako/package-lock.json is missing")

    env = os.environ.copy()
    # Native packages (better-sqlite3/node-pty) require lifecycle scripts.
    env.pop("npm_config_ignore_scripts", None)
    env.pop("NPM_CONFIG_IGNORE_SCRIPTS", None)
    print(f"[bootstrap] {npm} ci  (cwd={hanako_dir})")
    if not dry_run:
        subprocess.run([npm, "ci"], cwd=hanako_dir, env=env, check=True)
    print("[bootstrap] Hanako Node dependencies ready")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install LAAP and Hanako source dependencies")
    parser.add_argument("--with-dev", action="store_true", help="install Python test/lint tools")
    parser.add_argument("--skip-python", action="store_true")
    parser.add_argument("--skip-node", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="detect and print commands without installing")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    print(f"[bootstrap] root={root}")
    print(f"[bootstrap] platform={platform.platform()}")
    ensure_python(root, args.with_dev, args.dry_run, args.skip_python)
    ensure_node(root, args.dry_run, args.skip_node)
    print("[bootstrap] complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
