"""ErrorClassifier — 错误分类"""
from enum import Enum
from typing import Dict, Optional

class ErrorClass(str, Enum):
    API = "api_error"; AUTH = "auth_error"; TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"; TOOL = "tool_error"; MEMORY = "memory_error"
    UNKNOWN = "unknown"

class ErrorClassifier:
    PATTERNS = [
        ("401", ErrorClass.AUTH), ("403", ErrorClass.AUTH),
        ("429", ErrorClass.RATE_LIMIT), ("timeout", ErrorClass.TIMEOUT),
        ("rate limit", ErrorClass.RATE_LIMIT), ("api key", ErrorClass.AUTH),
    ]
    @classmethod
    def classify(cls, error: str) -> ErrorClass:
        for pattern, cls_type in cls.PATTERNS:
            if pattern in error.lower():
                return cls_type
        return ErrorClass.UNKNOWN
    @classmethod
    def should_retry(cls, error: str) -> bool:
        return cls.classify(error) in (ErrorClass.TIMEOUT, ErrorClass.RATE_LIMIT)
