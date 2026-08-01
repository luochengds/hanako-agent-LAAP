"""P2-skill-packs: sidecar 端点 helper.

5 个 handle_pack_* 函数, 供 ``hanako/aris-bridge/aris-engine/sidecar.py`` 调用.
封装 ``laap.skills.pack_manager`` 的纯 Python API, 让 sidecar 仅负责 HTTP 解析.

5 端点对应:
- ``GET  /skills/list?agent_name=X``        → ``handle_pack_list(agent_name)``
- ``POST /skills/export``  body {skill_id, output_dir?}
                                            → ``handle_pack_export(skill_id, output_dir)``
- ``POST /skills/import``  body {zip_path}  → ``handle_pack_import(zip_path)``
- ``POST /skills/install`` body {agent_name, skill_id}
                                            → ``handle_pack_install(agent_name, skill_id)``
- ``POST /skills/uninstall`` body {agent_name, skill_id}
                                            → ``handle_pack_uninstall(agent_name, skill_id)``

每个 helper 返回 (status_code, payload), 由 sidecar 的 _json_response 写出.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

# lazy import pack_manager 以避免在 sidecar import 阶段触发 sqlite3 / vault_manager 副作用
_pm = None  # type: ignore


def _pm_mod():
    """Lazy import laap.skills.pack_manager."""
    global _pm
    if _pm is None:
        from laap.skills import pack_manager as _m
        _pm = _m
    return _pm


logger = logging.getLogger("laap.skills.skill_pack_mcp_endpoints")


# ── 5 个端点 helper ──────────────────────────────────────────


def handle_pack_list(agent_name: str) -> Tuple[int, Dict[str, Any]]:
    """``GET /skills/list?agent_name=X`` → 返回 agent 已安装 + 系统可用技能.

    Response: ``{installed: [...], available: [...]}``
    """
    if not agent_name:
        return 400, {"error": "agent_name is required"}
    try:
        pm = _pm_mod()
        installed = pm.list_installed(agent_name)
        available = pm.list_available()
        return 200, {
            "agent_name": agent_name,
            "installed": installed,
            "available": available,
        }
    except Exception as e:
        logger.error(f"handle_pack_list failed for '{agent_name}': {e}")
        return 500, {"error": str(e)}


def handle_pack_export(
    skill_id: str,
    output_dir: Optional[str] = None,
) -> Tuple[int, Dict[str, Any]]:
    """``POST /skills/export`` body ``{skill_id, output_dir?}`` → 打包 zip.

    Response: ``{exported: True, skill_id, zip_path, version}``
    """
    if not skill_id:
        return 400, {"error": "skill_id is required"}
    try:
        pm = _pm_mod()
        zip_path = pm.export_pack(skill_id, output_dir)
        # 读取 manifest 获取 version 用于响应
        manifest = pm._read_manifest(pm._skill_dir(skill_id))
        return 200, {
            "exported": True,
            "skill_id": manifest.name,
            "version": manifest.version,
            "zip_path": zip_path,
        }
    except FileNotFoundError as e:
        return 404, {"error": str(e)}
    except ValueError as e:
        return 400, {"error": str(e)}
    except Exception as e:
        logger.error(f"handle_pack_export failed for '{skill_id}': {e}")
        return 500, {"error": str(e)}


def handle_pack_import(zip_path: str) -> Tuple[int, Dict[str, Any]]:
    """``POST /skills/import`` body ``{zip_path}`` → 解压并安装到 laap/skills/.

    Response: ``{imported: True, skill_id}``
    """
    if not zip_path:
        return 400, {"error": "zip_path is required"}
    try:
        pm = _pm_mod()
        skill_id = pm.import_pack(zip_path)
        return 200, {
            "imported": True,
            "skill_id": skill_id,
        }
    except FileNotFoundError as e:
        return 404, {"error": str(e)}
    except ValueError as e:
        return 400, {"error": str(e)}
    except Exception as e:
        logger.error(f"handle_pack_import failed for '{zip_path}': {e}")
        return 500, {"error": str(e)}


def handle_pack_install(
    agent_name: str,
    skill_id: str,
) -> Tuple[int, Dict[str, Any]]:
    """``POST /skills/install`` body ``{agent_name, skill_id}`` → 注册到 vault.

    幂等: 重复调用不报错 (INSERT OR REPLACE).

    Response: ``{installed: True, skill_id, version, agent_name}``
    """
    if not agent_name or not skill_id:
        return 400, {
            "error": "agent_name and skill_id are required",
        }
    try:
        pm = _pm_mod()
        result = pm.install(agent_name, skill_id)
        return 200, result
    except FileNotFoundError as e:
        return 404, {"error": str(e)}
    except ValueError as e:
        return 400, {"error": str(e)}
    except Exception as e:
        logger.error(
            f"handle_pack_install failed for ('{agent_name}','{skill_id}'): {e}"
        )
        return 500, {"error": str(e)}


def handle_pack_uninstall(
    agent_name: str,
    skill_id: str,
) -> Tuple[int, Dict[str, Any]]:
    """``POST /skills/uninstall`` body ``{agent_name, skill_id}`` → 从 vault 删除.

    幂等: 不存在的记录静默成功.

    Response: ``{uninstalled: True, skill_id, agent_name}``
    """
    if not agent_name or not skill_id:
        return 400, {
            "error": "agent_name and skill_id are required",
        }
    try:
        pm = _pm_mod()
        result = pm.uninstall(agent_name, skill_id)
        return 200, result
    except Exception as e:
        logger.error(
            f"handle_pack_uninstall failed for ('{agent_name}','{skill_id}'): {e}"
        )
        return 500, {"error": str(e)}
