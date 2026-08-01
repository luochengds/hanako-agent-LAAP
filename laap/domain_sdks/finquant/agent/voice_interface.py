"""LAAP FinQuant Domain SDK — Voice interface (TTS + ASR).

Bridges the financial agent to spoken dialogue. Mirrors BaiLongma's
voice model: a pluggable ASR callable (Whisper / cloud / laap voicetools)
and a pluggable TTS backend (laap.audio.service providers: aliyun, doubao,
minimax, openai, microsoft, tencent, xunfei, elevenlabs, local).

Design:
- **TTS** is async, supports interruption (a new speak() cancels the
  current utterance), and streams audio chunks to a callback so the host
  UI can play them as they arrive (low voice latency).
- **ASR** is a single async callable the host injects: ``async def
  asr_callable() -> str``. The host decides whether that's push-to-talk
  (record until silence) or wake-word-triggered. This keeps the agent
  backend free of audio-device coupling.
- Falls back gracefully: if no TTS provider / no ASR callable is wired,
  the interface is inert and the agent runs in text mode.

Voice mode flow (one turn)::

    user_text = await voice.listen()        # ASR: mic → text
    reply = await agent.chat(user_text, voice=True)
    # agent.chat already called speak() internally for intermediate status;
    # the final reply is spoken here:
    await voice.speak(reply)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from laap.domain_sdks.finquant.agent.config import VoiceConfig

logger = logging.getLogger("laap.domain_sdks.finquant.agent.voice")

# Type alias: an async callable that returns a transcript string.
ASRCallable = Callable[[], Awaitable[str]]
# TTS chunk callback: receives bytes as they're produced.
TTSChunkCallback = Callable[[bytes], Awaitable[None]]


class VoiceInterface:
    """TTS/ASR facade for the financial agent.

    Args:
        config: Voice configuration (provider, voice, speed, mode).
        tts_engine: Optional pre-built TTS engine object. If None, the
            interface tries to build one from ``laap.audio.service``
            using ``config.tts_provider``.
        asr_callable: Optional async callable returning a transcript.
            If None, :meth:`listen` returns an empty string (text mode).
        chunk_callback: Optional async callback receiving TTS audio
            chunks for streaming playback.
    """

    def __init__(
        self,
        config: VoiceConfig,
        tts_engine: Any = None,
        asr_callable: Optional[ASRCallable] = None,
        chunk_callback: Optional[TTSChunkCallback] = None,
    ) -> None:
        self.config = config
        self._tts_engine = tts_engine
        self._asr_callable = asr_callable
        self._chunk_callback = chunk_callback
        self._tts_available: Optional[bool] = None
        self._tts_lock = asyncio.Lock()
        self._current_speak_task: Optional[asyncio.Task] = None
        # Event signalling that speech was interrupted.
        self._interrupt_event: Optional[asyncio.Event] = None

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize the TTS engine (lazy). Safe to call multiple times."""
        if self._tts_engine is not None or self._tts_available is not None:
            return
        try:
            from laap.audio.service import AudioService  # type: ignore

            svc = AudioService()
            self._tts_engine = svc
            self._tts_available = True
            logger.info(
                "VoiceInterface ready (tts=%s, asr=%s)",
                self.config.tts_provider,
                "yes" if self._asr_callable else "no",
            )
        except Exception as exc:
            logger.info("TTS engine unavailable (%s) — voice mode degraded to text-only", exc)
            self._tts_available = False

    # ── TTS ───────────────────────────────────────────────────────

    async def speak(self, text: str, interrupt: bool = True) -> None:
        """Speak ``text`` via TTS. Streams chunks to ``chunk_callback``.

        If ``interrupt`` is True (default), any in-flight speech is
        cancelled before the new utterance starts — mirrors BaiLongma's
        "new sentence preempts the old" voice UX.
        """
        if not text or not self.config.auto_speak:
            return
        if self._tts_available is False:
            return
        if self._tts_engine is None:
            await self.start()
            if self._tts_available is False:
                return

        if interrupt:
            await self._cancel_current()

        async with self._tts_lock:
            self._interrupt_event = asyncio.Event()
            try:
                await self._speak_streaming(text, self._interrupt_event)
            except Exception as exc:
                logger.warning("TTS speak failed: %s: %s", type(exc).__name__, exc)
            finally:
                self._interrupt_event = None

    async def _speak_streaming(self, text: str, interrupt_event: asyncio.Event) -> None:
        """Stream TTS audio chunks; bail out if interrupted."""
        synth = None
        try:
            # Try the laap.audio.service streaming interface first.
            synth = getattr(self._tts_engine, "stream_tts", None) or getattr(
                self._tts_engine, "synthesize_stream", None
            )
        except Exception:
            synth = None

        if synth is not None:
            try:
                async for chunk in synth(
                    text,
                    provider=self.config.tts_provider,
                    voice=self.config.tts_voice,
                    speed=self.config.tts_speed,
                ):
                    if interrupt_event.is_set():
                        return
                    if self._chunk_callback is not None:
                        try:
                            await self._chunk_callback(chunk)
                        except Exception:
                            pass
                return
            except Exception as exc:
                logger.debug("streaming TTS failed, falling back to sync: %s", exc)

        # Fallback: one-shot synthesis.
        synth_one = getattr(self._tts_engine, "synthesize", None) or getattr(
            self._tts_engine, "tts", None
        )
        if synth_one is None:
            logger.warning("TTS engine has no synthesize/stream_tts method")
            return
        try:
            audio = synth_one(
                text,
                provider=self.config.tts_provider,
                voice=self.config.tts_voice,
                speed=self.config.tts_speed,
            )
            if asyncio.iscoroutine(audio):
                audio = await audio
            if audio and self._chunk_callback is not None:
                # Send as a single chunk.
                try:
                    await self._chunk_callback(audio if isinstance(audio, bytes) else bytes(audio))
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("one-shot TTS failed: %s: %s", type(exc).__name__, exc)

    async def _cancel_current(self) -> None:
        """Interrupt any in-flight speak() task."""
        if self._interrupt_event is not None:
            self._interrupt_event.set()
        if self._current_speak_task is not None and not self._current_speak_task.done():
            self._current_speak_task.cancel()
            try:
                await self._current_speak_task
            except (asyncio.CancelledError, Exception):
                pass
        self._current_speak_task = None

    async def stop_speaking(self) -> None:
        """Stop any current speech (used on user interrupt / new turn)."""
        await self._cancel_current()

    # ── ASR ───────────────────────────────────────────────────────

    async def listen(self) -> str:
        """Capture speech and return the transcript.

        Delegates to the injected ``asr_callable``. If none is wired,
        returns an empty string (text-mode fallback). The host decides
        push-to-talk vs. wake-word semantics by choosing what the
        callable does internally.
        """
        if self._asr_callable is None:
            return ""
        try:
            text = await self._asr_callable()
            return (text or "").strip()
        except Exception as exc:
            logger.warning("ASR failed: %s: %s", type(exc).__name__, exc)
            return ""

    # ── Status ────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "tts_available": bool(self._tts_available),
            "tts_provider": self.config.tts_provider,
            "asr_available": self._asr_callable is not None,
            "mode": self.config.mode,
            "auto_speak": self.config.auto_speak,
        }

    @property
    def is_voice_capable(self) -> bool:
        """True if both TTS and ASR are wired (full-duplex voice)."""
        return bool(self._tts_available) and self._asr_callable is not None


__all__ = ["VoiceInterface", "ASRCallable", "TTSChunkCallback"]
