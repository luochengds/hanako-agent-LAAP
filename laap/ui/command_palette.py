"""LAAP - Command Palette with Tool & MCP integration"""
from rich.text import Text
from rich.style import Style
from laap.ui.dragon_art import GOLD, GOLD_BRIGHT, GOLD_DIM, GOLD_LIGHT, CRIMSON
NL = chr(10)

class ToolDef:
    """Definition of a single tool."""
    def __init__(self, name: str, desc: str, category: str, icon: str = ""):
        self.name = name
        self.desc = desc
        self.category = category
        self.icon = icon or chr(0x2699)

class CommandPalette:
    """Slash-command palette for tool discovery and invocation."""

    def __init__(self):
        self.tools: list[ToolDef] = []
        self.mcp_tools: list[ToolDef] = []
        self._register_defaults()

    def _register_defaults(self):
        """Register built-in tools."""
        builtins = [
            ToolDef("read_file","Read file contents","code",chr(0x1F4D6)),
            ToolDef("write_file","Write content to file","code",chr(0x1F4DD)),
            ToolDef("patch","Apply find-replace edits","code",chr(0x2701)),
            ToolDef("search_files","Search file contents","code",chr(0x1F50D)),
            ToolDef("terminal","Run shell commands","shell",chr(0x26A1)),
            ToolDef("web_search","Search the web","web",chr(0x1F310)),
            ToolDef("web_fetch","Fetch URL content","web",chr(0x1F4E1)),
            ToolDef("memory_save","Save to persistent memory","memory",chr(0x1F9E0)),
            ToolDef("memory_recall","Recall from memory","memory",chr(0x1F4AD)),
            ToolDef("delegate","Spawn sub-agent","agent",chr(0x1F916)),
            ToolDef("run_python","Execute Python code","code",chr(0x1F40D)),
            ToolDef("git_diff","Show git diff","git",chr(0x1F500)),
            ToolDef("list_files","List directory","code",chr(0x1F4C1)),
        ]
        self.tools.extend(builtins)

    def register_mcp_tool(self, name: str, desc: str, server: str = ""):
        """Register a tool from an MCP server."""
        prefix = f"[{server}] " if server else ""
        self.mcp_tools.append(ToolDef(name, prefix+desc, "mcp", chr(0x1F50C)))

    def all_tools(self) -> list[ToolDef]:
        return self.tools + self.mcp_tools

    def filter(self, query: str) -> list[ToolDef]:
        """Filter tools by name or description."""
        q = query.lower().strip()
        if not q: return self.all_tools()
        results = []
        for t in self.all_tools():
            if q in t.name.lower() or q in t.desc.lower() or q in t.category.lower():
                results.append(t)
        return results

    def render(self, query: str = "", max_items: int = 10) -> Text:
        """Render the filtered tool list as Rich Text."""
        tools = self.filter(query)[:max_items]
        r = Text()
        r.append(Text(f" {chr(0x250D)}{chr(0x2501)*40}{chr(0x2511)}"+NL))
        r.append(Text(f" {chr(0x2503)}  {chr(0x2699)} Tools & Commands", style=Style(color=GOLD_BRIGHT,bold=True)))
        r.append(Text(f" {chr(0x2503)}  Type to filter or select a number", style=Style(color="#555555")))
        r.append(Text(f" {chr(0x2520)}{chr(0x2501)*40}{chr(0x2528)}"+NL))

        if not tools:
            r.append(Text(f" {chr(0x2503)}  No tools matched", style=Style(color="#666666",italic=True)))
            r.append(Text(NL))
        else:
            for i, tool in enumerate(tools, 1):
                cat_color = {"code":GOLD_BRIGHT,"shell":GOLD_LIGHT,"web":"#4FC1FF","memory":"#69DB7C","agent":"#FF6B6B","mcp":"#FFB347","git":"#F05032"}.get(tool.category,"#AAAAAA")
                r.append(Text(f" {chr(0x2503)}  ", style=Style(color="#444444")))
                r.append(Text(f"{i:2d}. ", style=Style(color="#555555")))
                r.append(Text(f"{tool.icon} ", style=Style(color=cat_color)))
                r.append(Text(f"{tool.name:<20s}", style=Style(color=GOLD_BRIGHT,bold=True)))
                r.append(Text(f"{tool.desc[:30]}", style=Style(color="#888888")))
                if tool.category == "mcp":
                    r.append(Text(" MCP", style=Style(color="#FFB347",italic=True)))
                r.append(NL)

        r.append(Text(f" {chr(0x2514)}{chr(0x2501)*40}{chr(0x2518)}"+NL))
        r.append(Text(f" Esc to close, Enter to select. /tool_name to run directly.", style=Style(color="#555555",italic=True)))
        return r

class SlashDispatcher:
    """Parse and dispatch slash commands."""

    def __init__(self, palette: CommandPalette = None):
        self.palette = palette or CommandPalette()

    def parse(self, text: str) -> dict:
        """Parse a slash command. Returns {type, name, args, raw}."""
        if not text.startswith("/"): return None
        parts = text[1:].strip().split(" ", 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Built-in commands
        if cmd in ("help","h"):
            return {"type":"builtin","name":"help","args":args,"raw":text}
        if cmd in ("new","clear","c"):
            return {"type":"builtin","name":"new_session","args":args,"raw":text}
        if cmd in ("exit","quit","q"):
            return {"type":"builtin","name":"exit","args":args,"raw":text}
        if cmd == "config":
            return {"type":"builtin","name":"config","args":args,"raw":text}
        if cmd == "cost":
            return {"type":"builtin","name":"cost","args":args,"raw":text}
        if cmd == "model":
            return {"type":"builtin","name":"model","args":args,"raw":text}
        if cmd in ("agents","subs"):
            return {"type":"builtin","name":"agents","args":args,"raw":text}

        # Tool invocation
        for tool in self.palette.all_tools():
            if cmd == tool.name:
                return {"type":"tool","name":tool.name,"args":args,"raw":text,"tool":tool}

        return {"type":"unknown","name":cmd,"args":args,"raw":text}