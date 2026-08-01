
"""
LAAP — 3D Avatar Renderer Integration
Uses mmdpy (Python MMD/PMX model renderer) to display a 3D avatar
that talks, expresses emotions, and can be controlled from the TUI.

Architecture:
  TUI (Textual) → AvatarBridge (multiprocessing.Queue)
    → Avatar3DProcess (separate GLFW window)
      → mmdpy world + model
      → EmotionSystem → facial morphs
      → TTS audio → lipsync
"""
from __future__ import annotations

import logging

import os, sys, json, time, logging, threading, queue, multiprocessing as mp
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("laap.ui.avatar_3d")

# ── IPC Protocol ──
# Commands sent from TUI to 3D process
CMD_LOAD_MODEL = "load_model"       # {"path": str}
CMD_SET_EMOTION = "set_emotion"     # {"name": str, "intensity": float}
CMD_LIPSYNC = "lipsync"             # {"amplitude": float} 0-1
CMD_SPEAK = "speak"                 # {"text": str, "duration": float}
CMD_IDLE = "idle"                   # {"state": str}
CMD_QUIT = "quit"
CMD_SET_MORPH = "set_morph"         # {"name": str, "value": float}
CMD_SET_BONE = "set_bone"           # {"name": str, "rotation": [x,y,z]}


class AvatarBridge:
    """
    Bridge between TUI and the 3D avatar process.
    Manages a separate process running the GLFW/OpenGL renderer.
    """

    def __init__(self):
        self._proc: Optional[mp.Process] = None
        self._cmd_queue: Optional[mp.Queue] = None
        self._status_queue: Optional[mp.Queue] = None
        self._running = False
        self._model_loaded = False
        self._status = {"model": "", "emotion": "neutral", "fps": 0}

    def start(self, model_path: str = ""):
        """Launch the 3D avatar renderer in a separate process."""
        if self._running:
            return
        self._cmd_queue = mp.Queue(maxsize=32)
        self._status_queue = mp.Queue(maxsize=8)
        self._proc = mp.Process(
            target=_avatar_process_main,
            args=(self._cmd_queue, self._status_queue, model_path),
            daemon=True,
        )
        self._proc.start()
        self._running = True
        logger.info("3D Avatar process started")

        # Start status listener
        self._status_thread = threading.Thread(target=self._poll_status, daemon=True)
        self._status_thread.start()

    def stop(self):
        """Stop the 3D avatar process."""
        if self._running and self._cmd_queue:
            self._cmd_queue.put({"cmd": CMD_QUIT})
            if self._proc:
                self._proc.join(timeout=3)
        self._running = False

    def load_model(self, path: str):
        """Load a PMX/PMD model file."""
        if self._cmd_queue:
            self._cmd_queue.put({"cmd": CMD_LOAD_MODEL, "path": path})
            self._model_loaded = True

    def set_emotion(self, name: str, intensity: float = 0.5):
        """Set facial expression based on emotion name."""
        if self._cmd_queue:
            self._cmd_queue.put({"cmd": CMD_SET_EMOTION, "name": name, "intensity": intensity})

    def set_morph(self, name: str, value: float):
        """Set a specific morph weight directly."""
        if self._cmd_queue:
            self._cmd_queue.put({"cmd": CMD_SET_MORPH, "name": name, "value": value})

    def lipsync(self, amplitude: float):
        """Drive mouth movement from audio amplitude (0-1)."""
        if self._cmd_queue:
            self._cmd_queue.put({"cmd": CMD_LIPSYNC, "amplitude": amplitude})

    def speak(self, text: str, duration: float):
        """Trigger speaking animation for given duration."""
        if self._cmd_queue:
            self._cmd_queue.put({"cmd": CMD_SPEAK, "text": text[:50], "duration": duration})

    def idle(self, state: str = "breathing"):
        """Set idle animation state."""
        if self._cmd_queue:
            self._cmd_queue.put({"cmd": CMD_IDLE, "state": state})

    def get_status(self) -> Dict:
        """Get current avatar status."""
        return dict(self._status)

    def _poll_status(self):
        """Background thread: read status updates from 3D process."""
        while self._running and self._status_queue:
            try:
                status = self._status_queue.get(timeout=0.5)
                self._status.update(status)
            except queue.Empty as e:
                logger.debug(f"操作失败: {e}")
            except Exception:
                break

    @property
    def is_running(self) -> bool:
        return self._running and (self._proc is not None and self._proc.is_alive())


def _avatar_process_main(cmd_queue: mp.Queue, status_queue: mp.Queue, initial_model: str = ""):
    """
    Main function for the 3D avatar process.
    Runs GLFW event loop for rendering mmdpy models.
    """
    try:
        _run_avatar_loop(cmd_queue, status_queue, initial_model)
    except Exception as e:
        try:
            status_queue.put({"error": str(e)})
        except Exception as e:
            logger.debug(f"操作失败: {e}")
def _run_avatar_loop(cmd_queue: mp.Queue, status_queue: mp.Queue, initial_model: str):
    """GLFW render loop with mmdpy."""
    import glfw
    import numpy as np
    from pyrr import Matrix44

    # ── Window Setup ──
    if not glfw.init():
        return

    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)

    window = glfw.create_window(480, 640, "LAAP - Digital Lifeform Avatar", None, None)
    if not window:
        glfw.terminate()
        return

    glfw.make_context_current(window)
    glfw.swap_interval(1)  # VSync

    # ── mmdpy Setup ──
    world, model = _setup_mmdpy(initial_model)

    # ── State ──
    mouth_open = 0.0
    current_emotion = "neutral"
    emotion_intensity = 0.0
    speaking = False
    speak_end_time = 0.0
    frame_count = 0
    last_fps_time = time.time()

    # Initial status
    status_queue.put({"status": "ready", "model": initial_model or "(none)"})

    # ── Main Loop ──
    while not glfw.window_should_close(window):
        now = time.time()

        # Process commands
        try:
            while True:
                cmd = cmd_queue.get_nowait()
                _process_cmd(cmd, model, status_queue)
                if cmd.get("cmd") == CMD_QUIT:
                    glfw.set_window_should_close(window, True)
                elif cmd.get("cmd") == CMD_SPEAK:
                    speaking = True
                    speak_end_time = now + cmd.get("duration", 2.0)
                elif cmd.get("cmd") == CMD_LIPSYNC:
                    mouth_open = cmd.get("amplitude", 0.0)
                elif cmd.get("cmd") == CMD_SET_EMOTION:
                    current_emotion = cmd.get("name", "neutral")
                    emotion_intensity = cmd.get("intensity", 0.5)
                    _apply_emotion_to_model(model, current_emotion, emotion_intensity)
        except queue.Empty as e:
            logger.debug(f"操作失败: {e}")
        if speaking:
            if now > speak_end_time:
                speaking = False
                mouth_open = 0.0
            else:
                # Simulate mouth movement
                mouth_open = 0.3 + 0.4 * abs(np.sin(now * 8.0))
                _apply_morph(model, "あ", mouth_open)

        # Idle breathing animation
        _apply_idle_animation(model, now)

        # Render
        glfw.poll_events()

        # Clear
        glClear = getattr(__import__('OpenGL.GL', fromlist=['glClear']), 'GL', None)
        if glClear:
            import OpenGL.GL as gl
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)

        # Update world
        if world:
            world.run()

        glfw.swap_buffers(window)

        # FPS
        frame_count += 1
        if frame_count % 60 == 0:
            fps = 60.0 / (now - last_fps_time)
            last_fps_time = now
            try:
                status_queue.put({"fps": round(fps, 1), "emotion": current_emotion})
            except Exception as e:
                logger.debug(f"操作失败: {e}")
    if world:
        world.close()
    glfw.terminate()


def _setup_mmdpy(model_path: str):
    """Initialize mmdpy world and load model."""
    try:
        import mmdpy
        import mmdpy_world
    except ImportError:
        logger.warning("mmdpy not installed - 3D avatar disabled")
        return None, None

    world = mmdpy_world.world("mmdpy", 480, 640)
    model = mmdpy.model()

    if model_path and os.path.exists(model_path):
        if model.load(model_path):
            world.push(model)
            logger.info(f"Loaded model: {model_path}")
        else:
            logger.warning(f"Failed to load model: {model_path}")

    return world, model


def _process_cmd(cmd: dict, model, status_queue: mp.Queue):
    """Process a command from the TUI."""
    cmd_type = cmd.get("cmd")
    if cmd_type == CMD_LOAD_MODEL and model:
        path = cmd.get("path", "")
        if os.path.exists(path):
            if model.load(path):
                logger.info(f"Model loaded: {path}")
                status_queue.put({"model": os.path.basename(path)})
    elif cmd_type == CMD_SET_MORPH and model:
        _apply_morph(model, cmd.get("name", ""), cmd.get("value", 0.0))


def _apply_morph(model, name: str, value: float):
    """Apply a morph (facial expression) to the model."""
    if model is None:
        return
    try:
        if hasattr(model, "set_morph"):
            model.set_morph(name, value)
        elif hasattr(model, "morph"):
            model.morph(name, value)
    except Exception as e:
        logger.debug(f"操作失败: {e}")
def _apply_emotion_to_model(model, emotion: str, intensity: float):
    """Map LAAP emotion names to MMD morph names."""
    # Standard MMD morph names (Japanese)
    morph_map = {
        "joy": {"喜び": 0.8, "笑い": 0.6, "まばたき": 0.3},
        "sadness": {"悲しみ": 0.8, "眉下げ": 0.5, "泣き": 0.4},
        "anger": {"怒り": 0.8, "眉上げ": 0.5, "睨み": 0.4},
        "surprise": {"驚き": 0.8, "口開け": 0.6, "眉上げ": 0.5},
        "fear": {"恐れ": 0.7, "眉上げ": 0.4, "震え": 0.3},
        "disgust": {"嫌悪": 0.6, "眉下げ": 0.4, "睨み": 0.3},
        "neutral": {"無表情": 0.0},
    }
    morphs = morph_map.get(emotion, {"無表情": 0.0})
    for morph_name, val in morphs.items():
        _apply_morph(model, morph_name, val * intensity)


def _apply_idle_animation(model, now: float):
    """Natural idle breathing and blinking."""
    import numpy as np
    # Blink every 3-5 seconds
    blink_cycle = now % 5.0
    if 0.02 < blink_cycle < 0.12:
        _apply_morph(model, "まばたき", 1.0)
    else:
        _apply_morph(model, "まばたき", 0.0)
