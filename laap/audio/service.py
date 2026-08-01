"""LAAP 统一音频服务。

接线：voice.input → ASR → agent → TTS → voice.tts / audio.stream
"""

from __future__ import annotations

import base64
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from laap.agi.cognitive_bus import CognitiveBus, get_bus as get_cognitive_bus
from laap.events.bus import EventBus, bus as global_event_bus

from .models import VoiceInputPayload
from .providers.factory import get_asr_provider, get_tts_provider
from .utils import guess_mime_from_audio

logger = logging.getLogger("laap.audio.service")


class AudioService:
    """后端统一音频服务。

    订阅 EventBus 的 ``voice.input`` 事件，执行：
      1. ASR 识别 -> 发布 ``voice.recognized``
      2. 将识别文本作为 ``user.input`` 交给 LAAP Agent
      3. 对 Agent 回复做 TTS -> 发布 ``voice.tts`` / ``audio.stream``
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        cognitive_bus: Optional[CognitiveBus] = None,
        agent: Optional[Any] = None,
        max_workers: int = 4,
    ) -> None:
        self.event_bus = event_bus or global_event_bus
        self.cognitive_bus = cognitive_bus or get_cognitive_bus("aris")
        self._agent = agent
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="laap_audio")
        self._subscribed = False

    def start(self) -> None:
        if self._subscribed:
            return
        self.event_bus.subscribe("voice.input", self._on_voice_input)
        self._subscribed = True
        self.cognitive_bus.register_module(
            "audio_service",
            version="0.1.0",
            capabilities=["asr", "tts", "voice_pipeline"],
        )
        logger.info("AudioService 已启动")

    def stop(self) -> None:
        if not self._subscribed:
            return
        self.event_bus.unsubscribe("voice.input", self._on_voice_input)
        self._subscribed = False
        self._executor.shutdown(wait=False)
        logger.info("AudioService 已停止")

    def _on_voice_input(self, event) -> None:
        """EventBus 回调，在线程池中执行耗时音频链路。"""
        self._executor.submit(self._handle_voice_input, event.data)

    def _handle_voice_input(self, data: Dict[str, Any]) -> None:
        try:
            payload = VoiceInputPayload.from_payload(data)
            if not payload.audio:
                logger.warning("voice.input 未携带音频数据")
                return

            # ── 1. ASR ──
            asr_config = {
                "provider": payload.asr.provider,
                "model": payload.asr.model,
                "base_url": payload.asr.base_url,
                "creds": payload.asr.creds,
                "language": "zh",
            }
            asr = get_asr_provider(asr_config)
            recognized = asr.recognize(payload.audio, mime_type=payload.mime_type)
            if not recognized:
                logger.warning("ASR 未识别到文本")
                return

            self.event_bus.publish_simple(
                "voice.recognized",
                {"text": recognized, "provider": payload.asr.provider},
                source="audio_service",
            )
            self.event_bus.publish_simple(
                "user.input",
                {"text": recognized, "source": "voice", "llmConfig": payload.llm},
                source="audio_service",
            )

            # ── 2. Agent ──
            response = self._get_agent_response(recognized, payload.llm)
            self.event_bus.publish_simple(
                "agent.output",
                {"text": response, "source": "voice"},
                source="audio_service",
            )

            # ── 3. TTS ──
            tts_config = {
                "provider": payload.tts.provider,
                "model": payload.tts.model,
                "base_url": payload.tts.base_url,
                "creds": payload.tts.creds,
            }
            tts = get_tts_provider(tts_config)
            audio = tts.synthesize(response, voice=payload.tts.model)
            audio_b64 = base64.b64encode(audio).decode("ascii")
            mime_type = guess_mime_from_audio(audio) or tts.default_mime_type

            self.event_bus.publish_simple(
                "voice.tts",
                {
                    "speaking": True,
                    "text": response,
                    "audioBase64": audio_b64,
                    "mimeType": mime_type,
                    "provider": payload.tts.provider,
                },
                source="audio_service",
            )
            self.event_bus.publish_simple(
                "audio.stream",
                {"audioBase64": audio_b64, "mimeType": mime_type},
                source="audio_service",
            )
        except Exception as e:
            logger.exception("语音流水线处理失败")
            self.event_bus.publish_simple(
                "voice.error",
                {"error": str(e)},
                source="audio_service",
            )

    def _get_agent_response(self, text: str, llm_config: Dict[str, Any]) -> str:
        """获取 LAAP Agent 回复。"""
        agent = self._ensure_agent(llm_config)
        try:
            return agent.chat(text) or ""
        except Exception as e:
            logger.warning(f"Agent 调用失败，回退到 echo: {e}")
            return f"我听到了：{text}"

    def _ensure_agent(self, llm_config: Dict[str, Any]):
        if self._agent is not None:
            return self._agent
        try:
            from laap.agent_core.agent import Agent, AgentConfig
            config = AgentConfig(
                name="ArisVoice",
                llm_provider=llm_config.get("provider", "deepseek"),
                llm_model=llm_config.get("model", "deepseek-v4-flash"),
                enable_tools=True,
                verbose=False,
            )
            self._agent = Agent(config=config, mode="kernel")
            logger.info(f"AudioService 创建默认 Agent: {config.llm_provider}/{config.llm_model}")
        except Exception as e:
            logger.warning(f"创建默认 Agent 失败: {e}")
            self._agent = _EchoAgent()
        return self._agent


class _EchoAgent:
    """当无法实例化真实 Agent 时的轻量回退。"""

    def chat(self, message: str) -> str:
        return f"我听到了：{message}"


# 模块级单例
_audio_service_instance: Optional[AudioService] = None


def get_audio_service(
    event_bus: Optional[EventBus] = None,
    cognitive_bus: Optional[CognitiveBus] = None,
) -> AudioService:
    global _audio_service_instance
    if _audio_service_instance is None:
        _audio_service_instance = AudioService(
            event_bus=event_bus,
            cognitive_bus=cognitive_bus,
        )
        _audio_service_instance.start()
    return _audio_service_instance
