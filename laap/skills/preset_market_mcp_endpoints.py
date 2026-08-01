"""P5-laaper-market MCP 端点桥接.

把 PresetRegistry (list / get / clone) 接入 sidecar HTTP 端点 ``/preset/*``
与 MCP server.

3 个桥接 helper (供 sidecar 调用, 返回 (status_code, payload)):
- ``handle_preset_list()``                    → ``GET  /preset/list``
- ``handle_preset_get(preset_id)``            → ``GET  /preset/get?id=xxx``
- ``handle_preset_clone(preset_id, new_name, customizations?)``
                                              → ``POST /preset/clone``

另导出 ``register_preset_market_tools(mcp_server)``, 供
``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用注册 MCP 工具.

设计约束:
- lazy import PresetRegistry, 避免模块加载副作用
- 克隆不直接创建身份, 返回配置交给前端 birth-ceremony
- 幂等: list/get 可重复调用; clone 同样参数返回新配置 (不写盘)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("laap.skills.preset_market_mcp_endpoints")

# lazy import preset_registry 以避免在 sidecar import 阶段产生耦合
_pr = None  # type: ignore


def _pr_mod():
    """Lazy import laap.skills.preset_registry."""
    global _pr
    if _pr is None:
        from laap.skills import preset_registry as _m
        _pr = _m
    return _pr


# ── 3 个端点 helper ──────────────────────────────────────────


def handle_preset_list() -> Tuple[int, Dict[str, Any]]:
    """``GET /preset/list`` → 返回全部社区预设包列表.

    Response: ``{presets: [...]}``
    """
    try:
        pr = _pr_mod()
        registry = pr.get_preset_registry()
        presets = registry.list_presets()
        return 200, {"presets": presets}
    except Exception as e:
        logger.error(f"handle_preset_list failed: {e}")
        return 500, {"error": str(e)}


def handle_preset_get(preset_id: str) -> Tuple[int, Dict[str, Any]]:
    """``GET /preset/get?id=xxx`` → 返回单个预设详情.

    Response: ``{preset: {...}}`` (200) 或 ``{error: ...}`` (404)
    """
    if not preset_id:
        return 400, {"error": "preset_id is required"}
    try:
        pr = _pr_mod()
        registry = pr.get_preset_registry()
        preset = registry.get_preset(preset_id)
        if preset is None:
            return 404, {"error": f"preset not found: {preset_id}"}
        return 200, {"preset": preset}
    except Exception as e:
        logger.error(f"handle_preset_get failed for '{preset_id}': {e}")
        return 500, {"error": str(e)}


def handle_preset_clone(
    preset_id: str,
    new_name: str,
    customizations: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Dict[str, Any]]:
    """``POST /preset/clone`` body ``{preset_id, new_name, customizations?}``
    → 克隆预设返回新 LAAPer 配置.

    不直接创建身份, 返回 ``{cloned, config}`` 让前端进入 birth-ceremony.

    Response: ``{cloned: True, config: {...}}`` (200) 或
              ``{error: ...}`` (400 / 404)
    """
    if not preset_id:
        return 400, {"error": "preset_id is required"}
    if not new_name or not str(new_name).strip():
        return 400, {"error": "new_name is required"}
    try:
        pr = _pr_mod()
        registry = pr.get_preset_registry()
        result = registry.clone_preset(preset_id, new_name.strip(), customizations)
        return 200, result
    except KeyError:
        return 404, {"error": f"preset not found: {preset_id}"}
    except Exception as e:
        logger.error(
            f"handle_preset_clone failed for '{preset_id}': {e}"
        )
        return 500, {"error": str(e)}


# ── MCP 工具注册 ─────────────────────────────────────────────


def register_preset_market_tools(mcp_server: Any) -> None:
    """向 FastMCP 实例注册 preset-market MCP 工具.

    在 ``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用::

        from laap.skills.preset_market_mcp_endpoints import (
            register_preset_market_tools,
        )
        register_preset_market_tools(mcp)

    注册的工具:
    - ``preset_list()`` 列出全部社区预设包
    - ``preset_get(preset_id)`` 查询单个预设详情
    - ``preset_clone(preset_id, new_name, customizations?)`` 克隆预设

    幂等: 本函数可被重复调用, FastMCP 内部去重.

    Args:
        mcp_server: FastMCP 实例 (必须提供 ``tool()`` 装饰器).
    """
    if mcp_server is None:
        logger.warning("register_preset_market_tools: mcp_server is None")
        return

    @mcp_server.tool()
    async def preset_list() -> str:
        """列出全部社区示例 LAAPer 预设包."""
        import json as _json
        status, payload = handle_preset_list()
        return _json.dumps(payload, ensure_ascii=False)

    @mcp_server.tool()
    async def preset_get(preset_id: str) -> str:
        """查询单个预设包详情.

        Args:
            preset_id: 预设包 ID (如 "aris")
        """
        import json as _json
        status, payload = handle_preset_get(preset_id)
        return _json.dumps(payload, ensure_ascii=False)

    @mcp_server.tool()
    async def preset_clone(
        preset_id: str,
        new_name: str,
        customizations: Optional[Dict[str, Any]] = None,
    ) -> str:
        """克隆预设包, 返回新 LAAPer 配置 (不创建身份).

        Args:
            preset_id: 要克隆的预设 ID
            new_name: 新 LAAPer 名称
            customizations: 可选自定义字段 (yuan/ishiki/color 等)
        """
        import json as _json
        status, payload = handle_preset_clone(preset_id, new_name, customizations)
        return _json.dumps(payload, ensure_ascii=False)

    logger.debug("register_preset_market_tools: registered 3 tools")
