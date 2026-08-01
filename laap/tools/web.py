"""
LAAP — Web 浏览与搜索工具

赋予 Agent 从互联网获取信息的能力。
内置 WebFetch、WebSearch 功能，类似 Claude Code 的 Web 工具。
"""

from __future__ import annotations
import json, logging
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

from laap.tools.base import ToolResult

logger = logging.getLogger("laap.tools.web")


def register_all(registry):
    """注册所有 Web 工具 - 幂等安全"""
    _registered = getattr(registry, '_web_tools_registered', False)
    if _registered:
        return
    registry._web_tools_registered = True

    @registry.tool(name="web_fetch", category="web",
                   description="获取网页内容并转为 Markdown。用于阅读文档、文章等。")
    def web_fetch(url: str, prompt: Optional[str] = None,
                  timeout: int = 30) -> str:
        """抓取网页内容

        Args:
            url: 网页 URL
            prompt: 可选的提取提示
            timeout: 超时秒数
        Returns:
            网页的 Markdown 内容
        """
        import httpx
        from html.parser import HTMLParser

        class MarkdownConverter(HTMLParser):
            def __init__(self):
                super().__init__()
                self.result = []
                self._skip = False
                self._list_level = 0

            def handle_starttag(self, tag, attrs):
                tag = tag.lower()
                if tag in ('script', 'style', 'nav', 'footer', 'header'):
                    self._skip = True
                if tag in ('h1',): self.result.append('\n# ')
                elif tag in ('h2',): self.result.append('\n## ')
                elif tag in ('h3',): self.result.append('\n### ')
                elif tag == 'p': self.result.append('\n\n')
                elif tag in ('li',): self.result.append('\n- ')
                elif tag == 'br': self.result.append('\n')
                elif tag == 'hr': self.result.append('\n---\n')
                elif tag == 'pre': self.result.append('\n```\n')
                elif tag == 'code': self.result.append('`')

            def handle_endtag(self, tag):
                tag = tag.lower()
                if tag in ('script', 'style', 'nav', 'footer', 'header'):
                    self._skip = False
                elif tag in ('h1', 'h2', 'h3'): self.result.append('  ')
                elif tag == 'pre': self.result.append('\n```\n')
                elif tag == 'code': self.result.append('`')
                elif tag in ('p', 'li', 'tr'): self.result.append('\n')

            def handle_data(self, data):
                if not self._skip:
                    self.result.append(data)

        try:
            resp = httpx.get(url, timeout=timeout,
                             follow_redirects=True,
                             headers={"User-Agent": "LAAP/1.0"})
            resp.raise_for_status()
            converter = MarkdownConverter()
            converter.feed(resp.text)
            content = ''.join(converter.result)
            lines = [l.strip() for l in content.split('\n') if l.strip()]
            content = '\n'.join(lines)
            max_chars = 8000
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n... (截断，共 {len(resp.text)} 字符原始 HTML)"
            source = resp.headers.get('content-type', '')
            return f"来源: {url}\n类型: {source}\n\n{content[:2000]}\n...(共 {len(content)} 字符)"
        except Exception as e:
            return f"抓取失败: {url}\n错误: {e}"

    @registry.tool(name="web_search", category="web",
                   description="搜索互联网。返回搜索结果列表（标题+URL+摘要）。")
    def web_search(query: str, max_results: int = 5) -> str:
        """搜索互联网

        Args:
            query: 搜索关键词
            max_results: 最大结果数
        Returns:
            搜索结果
        """
        try:
            import httpx
            resp = httpx.get(
                f"https://html.duckduckgo.com/html/",
                params={"q": query},
                timeout=15,
                headers={"User-Agent": "LAAP/1.0"},
            )
            resp.raise_for_status()

            from html.parser import HTMLParser
            class SearchParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.results = []
                    self._current = {}
                    self._in_result = False
                    self._in_title = False
                    self._in_snippet = False

                def handle_starttag(self, tag, attrs):
                    attrs_dict = dict(attrs)
                    cls = attrs_dict.get('class', '')
                    if 'result__a' in cls and tag == 'a':
                        self._in_title = True
                        self._current['url'] = attrs_dict.get('href', '')
                    if 'result__snippet' in cls:
                        self._in_snippet = True

                def handle_data(self, data):
                    if self._in_title:
                        self._current['title'] = data.strip()
                    if self._in_snippet:
                        self._current['snippet'] = data.strip()

                def handle_endtag(self, tag):
                    if self._in_title and tag == 'a':
                        self._in_title = False
                        if 'title' in self._current:
                            self.results.append(self._current)
                            self._current = {}
                    if self._in_snippet and tag == 'a':
                        self._in_snippet = False

            parser = SearchParser()
            parser.feed(resp.text)
            lines = []
            for i, r in enumerate(parser.results[:max_results], 1):
                title = r.get('title', '无标题')
                url = r.get('url', '')[:80]
                snippet = r.get('snippet', '')[:100]
                lines.append(f"{i}. [{title}]({url})")
                if snippet:
                    lines.append(f"   {snippet}")
            return "\n".join(lines) if lines else "未找到结果"

        except ImportError:
            return "需要安装 httpx: pip install httpx"
        except Exception as e:
            return f"搜索失败: {e}"


class _SearchParser(HTMLParser):
    """Parse DuckDuckGo HTML search results."""

    def __init__(self):
        super().__init__()
        self.results: List[Dict[str, str]] = []
        self._current: Dict[str, str] = {}
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")
        if tag == "a" and "result__a" in cls:
            self._in_title = True
            self._current["url"] = attrs_dict.get("href", "")
        if "result__snippet" in cls:
            self._in_snippet = True

    def handle_data(self, data):
        if self._in_title:
            self._current["title"] = data.strip()
        if self._in_snippet:
            self._current["snippet"] = data.strip()

    def handle_endtag(self, tag):
        if self._in_title and tag == "a":
            self._in_title = False
            if "title" in self._current:
                self.results.append(self._current)
                self._current = {}
        if self._in_snippet and tag == "a":
            self._in_snippet = False


def http_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 30) -> ToolResult:
    """Perform an HTTP GET request and return a ToolResult."""
    try:
        import httpx
        resp = httpx.get(
            url,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return ToolResult(
            success=True,
            output=resp.text,
            metadata={
                "status_code": resp.status_code,
                "url": str(resp.url),
                "method": "GET",
            },
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            output="",
            error=str(exc),
            metadata={"url": url, "method": "GET"},
        )


def http_post(
    url: str,
    data: Optional[Any] = None,
    json: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
) -> ToolResult:
    """Perform an HTTP POST request and return a ToolResult."""
    try:
        import httpx
        resp = httpx.post(
            url,
            data=data,
            json=json,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return ToolResult(
            success=True,
            output=resp.text,
            metadata={
                "status_code": resp.status_code,
                "url": str(resp.url),
                "method": "POST",
            },
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            output="",
            error=str(exc),
            metadata={"url": url, "method": "POST"},
        )


def web_search(query: str, max_results: int = 5) -> ToolResult:
    """Search the web using DuckDuckGo HTML and return a ToolResult."""
    try:
        import httpx
        resp = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=15,
            headers={"User-Agent": "LAAP/1.0"},
        )
        resp.raise_for_status()

        parser = _SearchParser()
        parser.feed(resp.text)

        results = parser.results[:max_results]
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "无标题")
            url = r.get("url", "")[:80]
            snippet = r.get("snippet", "")[:100]
            lines.append(f"{i}. [{title}]({url})")
            if snippet:
                lines.append(f"   {snippet}")

        output = "\n".join(lines) if lines else "未找到结果"
        return ToolResult(
            success=True,
            output=output,
            metadata={
                "query": query,
                "max_results": max_results,
                "returned": len(results),
                "results": results,
            },
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            output="",
            error=str(exc),
            metadata={"query": query, "max_results": max_results},
        )
