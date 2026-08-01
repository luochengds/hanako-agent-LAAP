"""LAAP MCP — Configuration

Persistent MCP server configuration management.
"""

from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from laap.mcp.client import MCPClient
from laap.mcp.lifecycle import MCPServerConfig
from laap.mcp.transports import StdioTransport

logger = logging.getLogger("laap.mcp.config")

CONFIG_DIR = Path.home() / ".laap" / "mcp"
CONFIG_FILE = CONFIG_DIR / "servers.json"


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, dict]:
    """Load MCP server configurations from disk."""
    _ensure_dir()
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load MCP config: {e}")
        return {}


def save_config(config: Dict[str, dict]):
    """Save MCP server configurations to disk."""
    _ensure_dir()
    try:
        CONFIG_FILE.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except OSError as e:
        logger.error(f"Failed to save MCP config: {e}")


def add_server(name: str, command: str = "",
               args: Optional[List[str]] = None,
               url: str = "",
               transport: str = "stdio",
               env: Optional[Dict[str, str]] = None,
               enabled: bool = True) -> bool:
    """Add an MCP server configuration."""
    config = load_config()
    if name in config:
        return False
    config[name] = {
        "name": name,
        "command": command,
        "args": args or [],
        "url": url,
        "transport": transport,
        "env": env or {},
        "enabled": enabled,
        "auto_reconnect": True,
    }
    save_config(config)
    return True


def remove_server(name: str) -> bool:
    """Remove an MCP server configuration."""
    config = load_config()
    if name not in config:
        return False
    del config[name]
    save_config(config)
    return True


def list_servers() -> List[Dict]:
    """List all configured MCP servers."""
    config = load_config()
    return list(config.values())


def get_server(name: str) -> Optional[dict]:
    """Get a specific MCP server configuration."""
    config = load_config()
    return config.get(name)


def to_lifecycle_configs() -> List[MCPServerConfig]:
    """Convert saved configs to MCPServerConfig objects."""
    configs = []
    for data in list_servers():
        configs.append(MCPServerConfig(
            name=data.get("name", ""),
            command=data.get("command", ""),
            args=data.get("args", []),
            url=data.get("url", ""),
            transport=data.get("transport", "stdio"),
            env=data.get("env", {}),
            auto_reconnect=data.get("auto_reconnect", True),
            enabled=data.get("enabled", True),
        ))
    return configs


# ── claw-in-chrome 默认配置 ──────────────────────────────────

def ensure_default_servers():
    """确保 claw-in-chrome MCP server 已注册到配置中.

    在 LAAP 启动时调用，自动将 claw-in-chrome-mcp 添加为
    stdio MCP server（如果尚未存在）。
    """
    import shutil
    cic_path = shutil.which("claw-in-chrome-mcp")
    if not cic_path:
        # Windows npm global
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidate = Path(appdata) / "npm" / "claw-in-chrome-mcp.cmd"
            if candidate.exists():
                cic_path = str(candidate)
    if not cic_path:
        logger.debug("claw-in-chrome-mcp not found, skipping default registration")
        return False

    config = load_config()
    if "claw-in-chrome" in config:
        # 更新路径（以防 npm 升级后路径变化）
        config["claw-in-chrome"]["command"] = cic_path
        config["claw-in-chrome"]["args"] = ["serve"]
        config["claw-in-chrome"]["transport"] = "stdio"
        config["claw-in-chrome"]["enabled"] = True
        save_config(config)
        return True

    config["claw-in-chrome"] = {
        "name": "claw-in-chrome",
        "command": cic_path,
        "args": ["serve"],
        "url": "",
        "transport": "stdio",
        "env": {},
        "enabled": True,
        "auto_reconnect": True,
    }
    save_config(config)
    logger.info("Registered claw-in-chrome MCP server (stdio)")
    return True


class MCPConfig:
    """Lightweight MCP client configuration.

    Reads a JSON config with a top-level ``mcpServers`` mapping where each
    entry may contain ``command``, ``args``, ``env`` and optionally ``url``.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config: Dict[str, Any] = config or {}
        self._servers: Dict[str, Dict[str, Any]] = self._config.get("mcpServers", {})

    @classmethod
    def load_from_file(cls, path: str) -> "MCPConfig":
        """Load config from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    @classmethod
    def load_from_dict(cls, data: Dict[str, Any]) -> "MCPConfig":
        """Load config from a dictionary."""
        return cls(data)

    def server_names(self) -> List[str]:
        """Return configured server names."""
        return sorted(self._servers.keys())

    def get_server_config(self, name: str) -> Optional[Dict[str, Any]]:
        """Return the raw config entry for *name*."""
        return self._servers.get(name)

    def get_client(self, name: str) -> Optional[MCPClient]:
        """Build and return a connected :class:`MCPClient` for *name*.

        For stdio servers the subprocess is spawned.  For SSE servers the
        URL must be provided.
        """
        entry = self._servers.get(name)
        if entry is None:
            return None
        transport = entry.get("transport", "stdio")
        if transport == "sse":
            url = entry.get("url", "")
            if not url:
                logger.error("MCP server %s missing url", name)
                return None
            from laap.mcp.transports import SSETransport
            return MCPClient(SSETransport(sse_url=url))

        command = entry.get("command", "")
        if not command:
            logger.error("MCP server %s missing command", name)
            return None
        args = entry.get("args", [])
        env = entry.get("env", {})
        import asyncio
        transport = asyncio.run(
            StdioTransport.spawn(command, args, env)
        )
        return MCPClient(transport)
