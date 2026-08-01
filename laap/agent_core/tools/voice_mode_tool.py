"""VoiceTool — 语音合成/识别"""
import json
class VoiceTool:
    def synthesize(self, text, voice="default"):
        return json.dumps({"audio_url": f"tts://{hash(text)%10000}", "text": text[:50], "voice": voice})
    def transcribe(self, audio_url):
        return json.dumps({"text": "[transcribed audio]"})
TOOL_DEFS = [
    {"name":"synthesize_speech","fn":VoiceTool().synthesize,"desc":"语音合成","params":{"text":{"type":"string"},"voice":{"type":"string"}},"req":["text"]},
    {"name":"transcribe_audio","fn":VoiceTool().transcribe,"desc":"语音识别","params":{"audio_url":{"type":"string"}},"req":["audio_url"]},
]
