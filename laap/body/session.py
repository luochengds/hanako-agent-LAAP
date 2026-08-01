"""LAAP — Conversation-level session manager.

Provides multi-turn dialogue support with topic shift detection, key fact
extraction, and context compression. Integrates optionally with the existing
episodic memory backends (``LongTermMemory.store_episodic`` or
``HierarchicalMemory.remember``).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.body.session")


@dataclass
class Message:
    """A single turn in a conversation session."""

    role: str  # user / assistant / system
    content: str
    timestamp: float = field(default_factory=time.time)
    topic: str = ""
    facts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "topic": self.topic,
            "facts": list(self.facts),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", time.time()),
            topic=data.get("topic", ""),
            facts=list(data.get("facts", [])),
        )


class SessionManager:
    """Manages a single conversation session.

    Features:
    - Ordered message history.
    - Lightweight keyword-based topic shift detection.
    - Heuristic key-fact extraction.
    - Context compression by summarising older topic blocks and archiving them
      to an optional episodic memory backend.
    """

    def __init__(
        self,
        session_id: str,
        episodic_memory: Optional[Any] = None,
        max_messages: int = 50,
        max_tokens: int = 4000,
    ):
        self.session_id = session_id
        self.episodic_memory = episodic_memory
        self.max_messages = max(max_messages, 2)
        self.max_tokens = max(max_tokens, 100)

        self.history: List[Message] = []
        self.summaries: List[Message] = []
        self.current_topic: str = ""

    # ── Message handling ─────────────────────────────────────────

    def add_message(self, role: str, content: str) -> Message:
        """Append a message to the session history."""
        msg = Message(role=role, content=content)
        msg.facts = self.extract_facts(content)

        if role == "user":
            if self.detect_topic_shift(content):
                # Start a new topic block; old block will be compressed if needed.
                if self.current_topic:
                    logger.debug(
                        "Topic shift detected in session %s: '%s' -> new topic",
                        self.session_id[:8],
                        self.current_topic[:40],
                    )
                self.current_topic = self._derive_topic(content)
            elif not self.current_topic:
                self.current_topic = self._derive_topic(content)
            msg.topic = self.current_topic
        elif self.history:
            # Assistant/system messages inherit the current topic.
            msg.topic = self.current_topic

        self.history.append(msg)
        self._maybe_compress()
        return msg

    # ── Topic detection ──────────────────────────────────────────

    def detect_topic_shift(self, message_text: str) -> bool:
        """Return True if the message appears to diverge from the current topic.

        Uses a simple keyword overlap heuristic so no external embedding model
        is required by default.
        """
        text = message_text.lower()
        current = self.current_topic.lower()

        if not current:
            return False  # First topic is never a "shift".

        # Vague continuation cues (pronouns / "more" / "continue") should not
        # trigger a shift even when keyword overlap is low.
        continuation_cues = {"it", "this", "that", "them", "they", "more",
                             "continue", "go on", "tell me", "explain",
                             "它", "这", "那", "他们", "她们", "它们",
                             "继续", "详细", "再说", "更多"}
        if any(cue in text for cue in continuation_cues):
            return False

        current_tokens = self._topic_tokens(current)
        new_tokens = self._topic_tokens(text)
        if not current_tokens or not new_tokens:
            return False

        overlap = len(current_tokens & new_tokens)
        union = len(current_tokens | new_tokens)
        similarity = overlap / union if union else 0.0

        # Low overlap and no explicit continuation cue => shift.
        return similarity < 0.15 and overlap < 2

    def get_current_topic(self) -> str:
        """Return the current conversation topic."""
        return self.current_topic

    # ── Fact extraction ──────────────────────────────────────────

    def extract_facts(self, message_text: str) -> List[str]:
        """Extract likely factual statements from a message.

        This is intentionally lightweight: regex/heuristic patterns in both
        English and Chinese.
        """
        facts: List[str] = [s.strip() for s in re.split(r"[.!?。！？]", message_text) if s.strip()]
        results: List[str] = []

        # English fact patterns
        en_patterns = [
            r"\bmy name is\s+(.{2,60})",
            r"\bi am\s+(.{2,60})",
            r"\bi work (?:at|for)\s+(.{2,60})",
            r"\bi live in\s+(.{2,60})",
            r"\bi (?:like|love|prefer|need|want)\s+(.{2,80})",
        ]
        # Chinese fact patterns
        zh_patterns = [
            r"(?:我|用户|他|她|它)叫(.{2,30})",
            r"(?:我|用户|他|她|它)(?:是|在|住在|工作于|任职于|喜欢|需要|想要|必须)(.{2,60})",
            r"(?:名字|名称|身份|职业|年龄|地址|邮箱|电话)(?:是|为|:|：)\s*(.{2,40})",
        ]

        for sentence in facts:
            sentence_lower = sentence.lower()
            matched = False
            for pattern in en_patterns + zh_patterns:
                for m in re.finditer(pattern, sentence_lower, re.IGNORECASE):
                    extracted = m.group(1).strip(" ,.，。！？")
                    if extracted and len(extracted) >= 2:
                        results.append(extracted)
                        matched = True
            # Keep short declarative sentences as fallback facts.
            if not matched and len(sentence) >= 5 and len(sentence) <= 120:
                # Simple declarative heuristic: contains "is/am/are/是".
                if re.search(r"\b(is|am|are|was|were)\b|是", sentence_lower):
                    results.append(sentence.strip())

        return results[:5]  # Cap to avoid noise.

    # ── Context compression ──────────────────────────────────────

    def compress_context(self) -> Optional[Message]:
        """Force compression of the oldest topic block.

        Returns the summary message that was created, or None if nothing to
        compress.
        """
        if not self.history:
            return None

        # Find the oldest contiguous block sharing the same topic.
        oldest_topic = self.history[0].topic
        cut_index = 0
        for idx, msg in enumerate(self.history):
            if msg.topic != oldest_topic:
                break
            cut_index = idx + 1

        # Always keep at least the most recent message in history.
        if cut_index >= len(self.history):
            cut_index = max(1, len(self.history) // 2)

        block = self.history[:cut_index]
        self.history = self.history[cut_index:]

        summary_text = self._summarize_block(block)
        summary = Message(role="system", content=summary_text, topic=oldest_topic)
        self.summaries.append(summary)

        self._archive_summary(summary)
        return summary

    def get_context_for_llm(self, limit: int = 10) -> List[Message]:
        """Return archived summaries followed by recent messages."""
        recent = self.history[-limit:] if limit > 0 else list(self.history)
        # Include summaries that fit within the remaining budget.
        budget = max(0, limit - len(recent))
        return self.summaries[-budget:] + recent

    # ── Serialization ────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "max_messages": self.max_messages,
            "max_tokens": self.max_tokens,
            "current_topic": self.current_topic,
            "history": [m.to_dict() for m in self.history],
            "summaries": [m.to_dict() for m in self.summaries],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionManager":
        instance = cls(
            session_id=data.get("session_id", ""),
            max_messages=data.get("max_messages", 50),
            max_tokens=data.get("max_tokens", 4000),
        )
        instance.current_topic = data.get("current_topic", "")
        instance.history = [Message.from_dict(m) for m in data.get("history", [])]
        instance.summaries = [Message.from_dict(m) for m in data.get("summaries", [])]
        return instance

    # ── Internal helpers ─────────────────────────────────────────

    def _maybe_compress(self) -> None:
        """Compress history when it exceeds message or token limits."""
        if len(self.history) > self.max_messages:
            self.compress_context()
            return

        total_tokens = sum(self._estimate_tokens(m.content) for m in self.history)
        if total_tokens > self.max_tokens:
            self.compress_context()

    def _archive_summary(self, summary: Message) -> None:
        """Send a compressed summary to episodic memory if available."""
        if self.episodic_memory is None:
            return

        try:
            if hasattr(self.episodic_memory, "store_episodic"):
                self.episodic_memory.store_episodic(
                    content=summary.content,
                    title=f"session:{self.session_id}:topic:{summary.topic}",
                    tags=["session_summary", "episodic", summary.topic or "general"],
                    importance=0.5,
                    source="session_manager",
                )
            elif hasattr(self.episodic_memory, "remember"):
                self.episodic_memory.remember(
                    content=summary.content,
                    tags=["session_summary", "episodic", summary.topic or "general"],
                    importance=0.5,
                )
        except Exception as e:
            logger.debug("Failed to archive summary to episodic memory: %s", e)

    def _summarize_block(self, block: List[Message]) -> str:
        """Create a short text summary of a message block."""
        topic = block[0].topic or "general"
        fact_lines: List[str] = []
        for msg in block:
            for fact in msg.facts:
                if fact not in fact_lines:
                    fact_lines.append(fact)

        participants = {m.role for m in block}
        fact_part = "; ".join(fact_lines[:5])
        if fact_part:
            return f"[Summary: {topic}] Turn covered {len(block)} messages. Facts: {fact_part}."
        return f"[Summary: {topic}] Compressed {len(block)} messages from roles {','.join(sorted(participants))}."

    @staticmethod
    def _topic_tokens(text: str) -> set:
        """Extract meaningful tokens for topic comparison."""
        # Drop common stop words in both languages.
        stops = {
            "the", "a", "an", "is", "are", "was", "were", "to", "of", "and",
            "in", "on", "at", "for", "with", "about", "it", "this", "that",
            "我", "你", "他", "她", "它", "我们", "你们", "他们", "的", "了",
            "在", "是", "和", "有", "就", "不", "会", "要", "还", "可以",
        }
        # Split on non-alphanumeric boundaries; keep tokens longer than 1 char.
        tokens = re.findall(r"[a-z0-9]+|\u4e00-\u9fff", text.lower())
        return {t for t in tokens if len(t) > 1 and t not in stops}

    @staticmethod
    def _derive_topic(text: str) -> str:
        """Derive a short topic label from the first few content words."""
        # Prefer noun-like keywords.
        candidates = re.findall(r"[a-z]{3,}|\u4e00-\u9fff", text.lower())
        if not candidates:
            return text[:30].strip()
        return " ".join(candidates[:6])

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Very rough token estimate (4 chars ~ 1 token)."""
        return max(1, len(text) // 4)
