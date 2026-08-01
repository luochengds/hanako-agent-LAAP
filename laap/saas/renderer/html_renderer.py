"""
LAAP SaaS — LAAP-UI → HTML 渲染器

将 LAAP-UI 协议的 Component/LayoutTree 递归渲染为 HTML 字符串。
支持全部 22 种组件类型, 事件绑定, 样式系统, 和主题系统。

依赖: laap/protocol/laap_ui.py (1,219行)
"""

from __future__ import annotations

import html
import json
import logging
from typing import Dict, List, Optional, Set

from laap.protocol.laap_ui import (
    Component, ComponentType, EventBinding, LayoutTree,
    StyleDefinition, ThemeConfig, ThemeDefinition,
    LayoutType, FlexStyle, GridStyle, TextStyle,
)

logger = logging.getLogger("laap.saas.renderer")

# ── 安全属性白名单 ──────────────────────────────────────────────
SAFE_ATTRS: Set[str] = {
    "id", "class", "style", "title", "lang", "dir",
    "role", "aria-*", "data-*",
    "tabindex", "accesskey",
    "hidden", "draggable",
}

# ── 组件类型 → HTML 标签映射 ────────────────────────────────────
COMPONENT_TAG_MAP: Dict[ComponentType, str] = {
    ComponentType.ROOT: "div",
    ComponentType.CONTAINER: "div",
    ComponentType.TEXT: "span",
    ComponentType.IMAGE: "img",
    ComponentType.BUTTON: "button",
    ComponentType.INPUT: "input",
    ComponentType.PROGRESS: "progress",
    ComponentType.CHART: "div",
    ComponentType.LIST: "ul",
    ComponentType.FORM: "form",
    ComponentType.TABLE: "table",
    ComponentType.SLIDER: "input",
    ComponentType.ICON: "i",
    ComponentType.LINK: "a",
    ComponentType.VIDEO: "video",
    ComponentType.AUDIO: "audio",
    ComponentType.CARD: "div",
    ComponentType.BADGE: "span",
    ComponentType.TOOLTIP: "div",
    ComponentType.DROPDOWN: "select",
    ComponentType.NAVIGATION: "nav",
    ComponentType.FOOTER: "footer",
    ComponentType.HEADER: "header",
    ComponentType.SIDEBAR: "aside",
    ComponentType.MODAL_WINDOW: "div",
    ComponentType.TOAST: "div",
    ComponentType.SPINNER: "div",
    ComponentType.AVATAR: "div",
    ComponentType.DIVIDER: "hr",
    ComponentType.SPACE: "div",
    ComponentType.IFRAME: "iframe",
    ComponentType.CANVAS: "canvas",
    ComponentType.SVG: "svg",
    ComponentType.HTML: "div",
}

# ── Void 元素（自闭和标签） ──────────────────────────────────────
VOID_ELEMENTS: Set[str] = {"img", "input", "hr", "br", "progress", "canvas", "iframe"}

# ── 需要闭合的 void 元素 ─────────────────────────────────────────
SELF_CLOSING: Set[str] = {"img", "input", "hr", "br", "progress", "canvas", "iframe"}


class HTMLRenderer:
    """LAAP-UI 组件树 → HTML 渲染器

    将 Component 树或 LayoutTree 递归渲染为 HTML 字符串。
    支持：
    - 全部 22+ 组件类型
    - StyleDefinition 转 inline CSS
    - FlexStyle/GridStyle 转 CSS
    - EventBinding 转 data-laap-event 属性
    - ThemeConfig 转 CSS 变量
    - 安全性: 属性白名单 + HTML 转义
    """

    def __init__(self, theme: Optional[ThemeConfig] = None):
        self.theme = theme or ThemeConfig()
        self._theme_def = ThemeDefinition(self.theme)
        self._compiled_css_vars = self._theme_def.compile()
        self._component_count = 0

    def render(self, tree: LayoutTree) -> str:
        """渲染完整的 LayoutTree 为 HTML 页面"""
        self._component_count = 0
        body_html = self._render_component(tree.root, depth=0)
        css_vars = self._css_vars_block()
        return f"""<!DOCTYPE html>
<html lang="zh-CN" data-laap-theme="{html.escape(self.theme.name)}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LAAP SaaS</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: {self.theme.typography.font_family}; }}
{css_vars}
</style>
</head>
<body data-laap="{self._component_count}">
{body_html}
</body>
</html>"""

    def render_fragment(self, component: Component) -> str:
        """渲染单个组件片段（不带页面骨架）"""
        return self._render_component(component, depth=0)

    def _render_component(self, comp: Component, depth: int = 0) -> str:
        """递归渲染单个 Component 为 HTML"""
        if not comp.visible:
            return ""

        self._component_count += 1
        tag = COMPONENT_TAG_MAP.get(comp.component_type, "div")

        # 构建 class
        classes = list(comp.classes)
        classes.append(f"laap-{comp.component_type.value}")
        class_str = " ".join(classes)

        # 构建 style
        style_str = self._build_style(comp)

        # 构建属性
        attrs = self._build_attributes(comp, tag, class_str, style_str)

        # 构建 data-laap-events（用于前端事件绑定）
        if comp.events:
            events_data = json.dumps(
                [{"t": e.event_type.value, "h": e.handler_id, "p": e.payload}
                 for e in comp.events],
                ensure_ascii=False
            )
            attrs += f' data-laap-events=\'{html.escape(events_data)}\''

        # 特殊组件内容构建
        inner = self._build_inner_content(comp, tag, depth)

        # 自闭和 vs 成对标签
        if tag in SELF_CLOSING:
            return f"<{tag}{attrs} />"
        else:
            children_html = ""
            for child in comp.children:
                if child.visible:
                    children_html += self._render_component(child, depth + 1)
            return f"<{tag}{attrs}>{inner}{children_html}</{tag}>"

    def _build_style(self, comp: Component) -> str:
        """构建 inline style 字符串"""
        styles = []

        # 基础样式
        if comp.style:
            s = comp.style
            # 遍历所有 StyleDefinition 字段
            for field_name in StyleDefinition.__dataclass_fields__:
                if field_name == "z_index":
                    val = getattr(s, field_name, 1)
                    if val != 1:
                        css_key = field_name.replace("_", "-")
                        styles.append(f"{css_key}: {val}")
                else:
                    val = getattr(s, field_name, None)
                    if val:
                        css_key = field_name.replace("_", "-")
                        styles.append(f"{css_key}: {val}")

        # Flex 样式
        if comp.flex_style and comp.layout_type in (LayoutType.FLEX, LayoutType.ROW, LayoutType.COLUMN):
            fs = comp.flex_style
            flex_map = {
                "flex_direction": "flex-direction",
                "flex_wrap": "flex-wrap",
                "justify_content": "justify-content",
                "align_items": "align-items",
                "align_content": "align-content",
                "flex_grow": "flex-grow",
                "flex_shrink": "flex-shrink",
                "flex_basis": "flex-basis",
                "gap": "gap",
                "order": "order",
            }
            for py_key, css_key in flex_map.items():
                val = getattr(fs, py_key, None)
                if val is not None:
                    styles.append(f"{css_key}: {val}")

        # Grid 样式
        if comp.grid_style and comp.layout_type == LayoutType.GRID:
            gs = comp.grid_style
            grid_map = {
                "grid_template_columns": "grid-template-columns",
                "grid_template_rows": "grid-template-rows",
                "grid_auto_columns": "grid-auto-columns",
                "grid_auto_rows": "grid-auto-rows",
                "grid_auto_flow": "grid-auto-flow",
                "row_gap": "row-gap",
                "column_gap": "column-gap",
                "justify_items": "justify-items",
                "align_items": "align-items",
                "justify_content": "justify-content",
                "align_content": "align-content",
                "grid_area": "grid-area",
                "grid_column": "grid-column",
                "grid_row": "grid-row",
            }
            for py_key, css_key in grid_map.items():
                val = getattr(gs, py_key, None)
                if val is not None:
                    styles.append(f"{css_key}: {val}")

        # 从 metadata.css 读取额外 CSS 属性
        if comp.metadata and "css" in comp.metadata:
            for css_key, css_val in comp.metadata["css"].items():
                styles.append(f"{css_key}: {css_val}")

        return "; ".join(styles)

    def _build_attributes(self, comp: Component, tag: str,
                          class_str: str, style_str: str) -> str:
        """构建 HTML 属性字符串"""
        attrs = f' id="{html.escape(comp.id)}"'

        if class_str:
            attrs += f' class="{html.escape(class_str)}"'
        if style_str:
            attrs += f' style="{html.escape(style_str)}"'
        if comp.tooltip:
            attrs += f' title="{html.escape(comp.tooltip)}"'
        if comp.aria_label:
            attrs += f' aria-label="{html.escape(comp.aria_label)}"'
        if comp.disabled:
            attrs += ' disabled'
        if comp.loading:
            attrs += ' data-loading="true"'
        if comp.test_id:
            attrs += f' data-testid="{html.escape(comp.test_id)}"'

        # 自定义属性
        for k, v in comp.attributes.items():
            if k in SAFE_ATTRS or k.startswith("aria-") or k.startswith("data-"):
                attrs += f' {html.escape(k)}="{html.escape(str(v))}"'

        # data-* 属性
        for k, v in comp.data_attributes.items():
            safe_k = k.replace("_", "-")
            attrs += f' data-{html.escape(safe_k)}="{html.escape(str(v))}"'

        return attrs

    def _build_inner_content(self, comp: Component, tag: str, depth: int) -> str:
        """构建特殊组件的内部内容"""
        inner = ""

        # 文本内容
        if comp.text_content is not None:
            inner = html.escape(comp.text_content)

        # 类型特定处理
        ct = comp.component_type

        if ct == ComponentType.TEXT and comp.text_content:
            inner = html.escape(comp.text_content)

        elif ct == ComponentType.IMAGE and comp.properties:
            src = comp.properties.get("src", "")
            alt = comp.properties.get("alt", "")
            if src:
                return ""  # 属性已处理, img 是 void 元素

        elif ct == ComponentType.LINK and comp.properties:
            href = comp.properties.get("href", "#")
            inner = html.escape(comp.text_content or "链接")

        elif ct == ComponentType.BUTTON and comp.properties:
            btn_text = comp.properties.get("text", comp.text_content or "")
            inner = html.escape(btn_text)

        elif ct == ComponentType.INPUT and comp.properties:
            input_type = comp.properties.get("type", "text")
            placeholder = comp.properties.get("placeholder", "")
            # input 是 void 元素, 不需要 inner

        elif ct == ComponentType.BADGE and comp.text_content:
            inner = html.escape(comp.text_content)

        elif ct == ComponentType.DIVIDER:
            # hr 是 void 元素
            pass

        elif ct == ComponentType.LIST:
            list_type = "ol" if comp.properties and comp.properties.get("list_type") == "ordered" else "ul"
            items = comp.properties.get("items", []) if comp.properties else []
            if items and not comp.children:
                inner = "".join(
                    f"<li>{html.escape(str(item))}</li>" for item in items
                )

        elif ct == ComponentType.TABLE:
            columns = comp.properties.get("columns", []) if comp.properties else []
            rows = comp.properties.get("rows", []) if comp.properties else []
            if columns or rows:
                thead = ""
                tbody = ""
                if columns:
                    thead = "<thead><tr>" + "".join(
                        f"<th>{html.escape(str(c.get('title', c.get('key', ''))))}</th>"
                        for c in columns
                    ) + "</tr></thead>"
                if rows:
                    tbody = "<tbody>" + "".join(
                        "<tr>" + "".join(
                            f"<td>{html.escape(str(row.get(c.get('key', ''), '')))}</td>"
                            for c in columns
                        ) + "</tr>"
                        for row in rows
                    ) + "</tbody>"
                inner = thead + tbody

        elif ct == ComponentType.FORM:
            inner = html.escape(comp.text_content or "")

        return inner

    def _css_vars_block(self) -> str:
        """生成 CSS 变量块"""
        lines = []
        for var_name, var_value in self._compiled_css_vars.items():
            lines.append(f"  {var_name}: {var_value};")
        return ":root {\n" + "\n".join(lines) + "\n}"


def render_page(tree: LayoutTree, theme: Optional[ThemeConfig] = None) -> str:
    """快捷方法: 渲染 LayoutTree 为完整 HTML 页面"""
    renderer = HTMLRenderer(theme=theme)
    return renderer.render(tree)


def render_component(component: Component, theme: Optional[ThemeConfig] = None) -> str:
    """快捷方法: 渲染单个 Component 为 HTML 片段"""
    renderer = HTMLRenderer(theme=theme)
    return renderer.render_fragment(component)


def render_page_from_json(json_str: str, theme: Optional[ThemeConfig] = None) -> str:
    """从 JSON 字符串反序列化后渲染"""
    tree = LayoutTree.from_json(json_str)
    return render_page(tree, theme)
