"""I18n — 国际化"""
from typing import Dict, Optional

TRANSLATIONS = {
    "zh": {"hello": "你好", "bye": "再见", "thinking": "思考中...", "done": "完成"},
    "en": {"hello": "Hello", "bye": "Goodbye", "thinking": "Thinking...", "done": "Done"},
    "ja": {"hello": "こんにちは", "bye": "さようなら", "thinking": "考え中...", "done": "完了"},
}

class I18n:
    def __init__(self, lang: str = "zh"):
        self.lang = lang
    def t(self, key: str) -> str:
        return TRANSLATIONS.get(self.lang, {}).get(key, TRANSLATIONS["zh"].get(key, key))
    def set_lang(self, lang: str):
        if lang in TRANSLATIONS:
            self.lang = lang
