"""MessageSanitization"""
import re
class MessageSanitizer:
    PATTERNS = [r"sk-[a-zA-Z0-9]{20,}", r"password=[^\s]+", r"Bearer\s+[a-zA-Z0-9._-]+"]
    @classmethod
    def sanitize(cls, text):
        for p in cls.PATTERNS:
            text = re.sub(p, "[REDACTED]", text)
        return text
