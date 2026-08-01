"""
LAAP LipSync + Motion Engine
- Audio-driven lip sync (FFT frequency analysis → VRM blendshapes)
- Emotion-driven gesture generation
- Text-driven motion prediction
- Natural idle animation with physics
"""

import logging
logger = logging.getLogger(__name__)

import json, math, random, time
from pathlib import Path

MOTIONS_FILE = Path(__file__).parent.parent / "laap" / "web" / "static" / "motions" / "motion_presets.json"

# ═══ Viseme Mapping (Phoneme → VRM Blendshape) ═══
# For Chinese phonemes mapped to VRM mouth shapes
VISEME_MAP = {
    # Vowels
    'a': {'a': 1.0, 'i': 0.0, 'u': 0.0},
    'o': {'a': 0.7, 'i': 0.0, 'u': 0.3},
    'e': {'a': 0.3, 'i': 0.5, 'u': 0.0},
    'i': {'a': 0.0, 'i': 1.0, 'u': 0.0},
    'u': {'a': 0.0, 'i': 0.0, 'u': 1.0},
    'ü': {'a': 0.0, 'i': 0.3, 'u': 0.8},
    # Consonants
    'b': {'a': 0.2, 'i': 0.0, 'u': 0.1},
    'p': {'a': 0.3, 'i': 0.0, 'u': 0.1},
    'm': {'a': 0.1, 'i': 0.0, 'u': 0.2},
    'f': {'a': 0.0, 'i': 0.2, 'u': 0.0},
    'd': {'a': 0.2, 'i': 0.0, 'u': 0.0},
    't': {'a': 0.3, 'i': 0.0, 'u': 0.0},
    'n': {'a': 0.1, 'i': 0.0, 'u': 0.1},
    'l': {'a': 0.1, 'i': 0.0, 'u': 0.0},
    'g': {'a': 0.3, 'i': 0.0, 'u': 0.0},
    'k': {'a': 0.4, 'i': 0.0, 'u': 0.0},
    'h': {'a': 0.2, 'i': 0.0, 'u': 0.1},
    'j': {'a': 0.0, 'i': 0.5, 'u': 0.0},
    'q': {'a': 0.0, 'i': 0.6, 'u': 0.0},
    'x': {'a': 0.0, 'i': 0.4, 'u': 0.0},
    'zh': {'a': 0.1, 'i': 0.0, 'u': 0.3},
    'ch': {'a': 0.2, 'i': 0.0, 'u': 0.3},
    'sh': {'a': 0.0, 'i': 0.0, 'u': 0.2},
    'r': {'a': 0.0, 'i': 0.2, 'u': 0.1},
    'z': {'a': 0.1, 'i': 0.0, 'u': 0.1},
    'c': {'a': 0.2, 'i': 0.0, 'u': 0.1},
    's': {'a': 0.0, 'i': 0.0, 'u': 0.1},
    'y': {'a': 0.0, 'i': 0.5, 'u': 0.2},
    'w': {'a': 0.2, 'i': 0.0, 'u': 0.5},
}

# ═══ Emotion→Motion Mapping ═══
EMOTION_MOTIONS = {
    "joy": {"motion": "emote_joy", "intensity_mult": 1.2, "hold_frames": 30},
    "sadness": {"motion": "emote_sad", "intensity_mult": 1.0, "hold_frames": 45},
    "anger": {"motion": "emote_angry", "intensity_mult": 1.3, "hold_frames": 25},
    "surprise": {"motion": "emote_surprise", "intensity_mult": 1.5, "hold_frames": 20},
    "curiosity": {"motion": "gesture_think", "intensity_mult": 1.0, "hold_frames": 40},
    "gratitude": {"motion": "gesture_encourage", "intensity_mult": 1.1, "hold_frames": 35},
    "pride": {"motion": "emote_joy", "intensity_mult": 0.8, "hold_frames": 30},
    "anxiety": {"motion": "emote_sad", "intensity_mult": 0.6, "hold_frames": 30},
    "love": {"motion": "emote_shy", "intensity_mult": 1.4, "hold_frames": 40},
    "neutral": {"motion": "idle_gentle", "intensity_mult": 0.5, "hold_frames": 0},
}

# ═══ Gesture Generation Engine ═══
class GestureEngine:
    """Generates natural gestures from text content and emotional state"""
    
    def __init__(self):
        self.load_motions()
        self.gesture_cooldown = {}
        self.current_pose = "idle"
        self.speech_rate = 1.0
    
    def load_motions(self):
        try:
            with open(MOTIONS_FILE, 'r', encoding='utf-8') as f:
                self.motions = json.load(f)
        except:
            self.motions = {"motions": {}, "emotion_action_map": {}, "dialogue_gesture_keywords": {}}
    
    def analyze_text(self, text: str) -> dict:
        """Analyze text to determine gestures and expressions"""
        text_lower = text.lower()
        gestures = []
        
        # Keyword matching
        kw_map = self.motions.get("dialogue_gesture_keywords", {})
        for keyword, gesture in kw_map.items():
            if keyword in text_lower:
                gestures.append({
                    "type": "gesture",
                    "name": gesture,
                    "priority": 0.7,
                    "delay": random.uniform(0.3, 0.8)
                })
        
        # Sentence length → gesture frequency
        words = len(text)
        if words > 20:
            gestures.append({
                "type": "emphasize",
                "name": "talk_excited",
                "priority": 0.5,
                "delay": 1.5
            })
        
        # Question → head tilt
        if '?' in text or '？' in text:
            gestures.append({
                "type": "question",
                "name": "gesture_think",
                "priority": 0.6,
                "delay": 0.5
            })
        
        # Exclamation → excited
        if '!' in text or '！' in text:
            gestures.append({
                "type": "excited",
                "name": "talk_excited",
                "priority": 0.7,
                "delay": 0.3
            })
        
        return {
            "gestures": gestures,
            "estimated_duration": words * 0.3 + 1.0,  # seconds
        }
    
    def get_speech_animation(self, text: str, emotion: str = "neutral") -> dict:
        """Generate full speech animation plan"""
        analysis = self.analyze_text(text)
        
        # Start with emotion
        emotion_data = EMOTION_MOTIONS.get(emotion, EMOTION_MOTIONS["neutral"])
        
        plan = {
            "emotion_motion": emotion_data["motion"],
            "emotion_intensity": emotion_data["intensity_mult"],
            "gesture_sequence": [],
            "idle_after": "idle_gentle"
        }
        
        # Sort gestures by priority and add to sequence
        sorted_gestures = sorted(analysis["gestures"], key=lambda x: -x["priority"])
        for g in sorted_gestures[:3]:  # Max 3 gestures per speech
            plan["gesture_sequence"].append({
                "time": g["delay"],
                "motion": g["name"],
                "type": g["type"]
            })
        
        return plan
    
    def get_idle_animation(self) -> str:
        """Pick idle animation with some randomness"""
        return random.choice(["idle_gentle", "idle_cute", "idle_gentle", "idle_gentle"])

    def get_listening_animation(self) -> dict:
        """Animation while listening to user"""
        return {
            "head_tilt": random.uniform(-0.05, 0.05),
            "nod": random.random() < 0.3,
            "blink_interval": random.uniform(2, 4)
        }

# ═══ LipSync Engine (audio→mouth) ═══
class LipSyncEngine:
    """Processes audio FFT data into VRM mouth blendshape values"""
    
    def __init__(self):
        self.mouth_open = 0.0
        self.smooth_factor = 0.3
        self.frequency_bands = {
            "low": (0, 200),      # Bass → jaw open
            "mid": (200, 2000),   # Voice → mouth shape
            "high": (2000, 8000), # Sibilants → lip closure
        }
    
    def process_fft(self, fft_data: list, sample_rate: int = 24000) -> dict:
        """Process FFT frequency data to VRM blendshape values"""
        if not fft_data:
            return {"a": 0, "i": 0, "u": 0}
        
        n_bins = len(fft_data)
        band_energy = {}
        
        for band, (low, high) in self.frequency_bands.items():
            low_bin = int(low * n_bins / (sample_rate / 2))
            high_bin = min(int(high * n_bins / (sample_rate / 2)), n_bins - 1)
            if high_bin > low_bin:
                energy = sum(fft_data[low_bin:high_bin]) / (high_bin - low_bin)
            else:
                energy = 0
            band_energy[band] = min(1.0, energy / 128)
        
        # Map band energy to VRM blendshapes
        jaw_open = band_energy["low"] * 1.2
        mouth_width = band_energy["mid"] * 0.8
        lip_round = band_energy["high"] * 0.5
        
        # Smooth
        self.mouth_open += (jaw_open - self.mouth_open) * self.smooth_factor
        
        # Generate VRM blendshape values
        return {
            "a": min(1.0, jaw_open * 1.5),
            "i": min(1.0, mouth_width * 1.2),
            "u": min(1.0, lip_round * 1.0),
            "mouth_open": self.mouth_open
        }
    
    def process_audio_energy(self, energy: float) -> float:
        """Simple audio energy → mouth open value"""
        target = min(1.0, energy * 3.0)
        self.mouth_open += (target - self.mouth_open) * self.smooth_factor
        return self.mouth_open

# ═══ Procedural Motion Generator ═══
class ProceduralMotion:
    """Generates natural-looking procedural motions without presets"""
    
    @staticmethod
    def breathing(time: float) -> dict:
        """Natural breathing pattern"""
        breath = math.sin(time * 2.5) * 0.006
        chest = math.sin(time * 2.5 + 0.3) * 0.003
        return {"body_y": breath, "chest_y": chest}
    
    @staticmethod
    def idle_sway(time: float, personality: str = "gentle") -> dict:
        """Natural body sway"""
        speed = 0.5 if personality == "gentle" else 0.8
        amp = 0.003 if personality == "gentle" else 0.006
        return {
            "spine_x": math.sin(time * speed) * amp,
            "spine_z": math.sin(time * speed * 0.7) * amp * 0.7,
            "head_y": math.sin(time * 0.3) * 0.05,
        }
    
    @staticmethod
    def blink_interval(personality: str = "calm") -> tuple:
        """Get blink timing based on personality"""
        if personality == "excited":
            return (1.5, 3.0)  # faster blinks
        elif personality == "calm":
            return (3.0, 6.0)  # normal
        else:
            return (2.0, 4.0)
    
    @staticmethod
    def micro_expressions(time: float) -> dict:
        """Subtle micro-expressions for realism"""
        # Every 8-15 seconds, a tiny expression change
        phase = (time % 12) / 12
        if 0.45 < phase < 0.55:
            return {"brow_up": 0.05}
        return {}

# ═══ Complete Animation Controller ═══
class AnimationController:
    """Master controller combining all animation systems"""
    
    def __init__(self):
        self.gesture = GestureEngine()
        self.lipsync = LipSyncEngine()
        self.procedural = ProceduralMotion()
        self.state = "idle"
        self.current_motion = None
        self.motion_queue = []
        self.time = 0
    
    def update(self, delta: float, audio_energy: float = 0, 
               emotion: str = "neutral", text: str = "") -> dict:
        """Update all animation systems and return VRM commands"""
        self.time += delta
        
        result = {
            "bones": {},
            "blendshapes": {},
            "play_motion": None,
        }
        
        # 1. Procedural motions (always active)
        breath = self.procedural.breathing(self.time)
        sway = self.procedural.idle_sway(self.time)
        result["bones"].update(breath)
        result["bones"].update(sway)
        
        # 2. Lip sync
        mouth = self.lipsync.process_audio_energy(audio_energy)
        result["blendshapes"]["a"] = mouth
        result["blendshapes"]["i"] = mouth * 0.6
        result["blendshapes"]["u"] = mouth * 0.4
        
        # 3. Auto blink
        blink_interval = self.procedural.blink_interval()
        if random.random() < delta / blink_interval[1]:
            result["blinkshape"] = 1.0
        
        # 4. Process motion queue
        if self.motion_queue:
            next_motion = self.motion_queue[0]
            next_motion["time_left"] -= delta
            if next_motion["time_left"] <= 0:
                result["play_motion"] = next_motion["name"]
                self.motion_queue.pop(0)
        
        return result
    
    def speak(self, text: str, emotion: str = "neutral"):
        """Queue speech animations"""
        plan = self.gesture.get_speech_animation(text, emotion)
        self.motion_queue.append({"name": plan["emotion_motion"], "time_left": 0})
        for g in plan["gesture_sequence"]:
            self.motion_queue.append({"name": g["motion"], "time_left": g["time"]})
    
    def set_emotion(self, emotion: str):
        """Set emotional state for motion generation"""
        if emotion in EMOTION_MOTIONS:
            self.motion_queue.append({
                "name": EMOTION_MOTIONS[emotion]["motion"],
                "time_left": 0
            })

if __name__ == "__main__":
    # Test
    ac = AnimationController()
    plan = ac.gesture.get_speech_animation("你好！我在思考一个问题，你觉得呢？", "joy")
    logger.info(f"Speech animation plan:")
    logger.info(f"  Emotion: {plan['emotion_motion']}")
    logger.info(f"  Gestures: {[g['name'] for g in plan['gesture_sequence']]}")
    lip = LipSyncEngine()
    logger.info(f"\nLip sync test (energy=0.7):")
    logger.info(f"  {lip.process_audio_energy(0.7)}")