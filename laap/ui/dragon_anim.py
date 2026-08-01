"""
LAAP - Golden Chinese Dragon Animation
Multi-frame animated dragon with dynamic progress indicators.
"""
from rich.text import Text
from rich.style import Style
from laap.ui.dragon_art import GOLD, GOLD_BRIGHT, GOLD_DIM, GOLD_LIGHT, CRIMSON, EYE_GLOW

# Golden Dragon ASCII frames (3-frame animation)
FRAME_1 = [
    "                 ⣀⣤⣶⣿⣿⣶⣤⣀",
    "             ⣠⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣤",
    "          ⣰⣿⣿⣿⣿⡿⠛⠉⠉⠛⢿⣿⣿⣿⣿⣷⡀",
    "         ⣼⣿⣿⣿⡿⠁⢀⣤⣤⣤⡀⠈⢿⣿⣿⣿⣿⣷⡀",
    "        ⣾⣿⣿⣿⠏⢠⣿⣿⣿⣿⣿⣦⠈⣿⣿⣿⣿⣿⡄",
    "       ⢸⣿⣿⣿⠃⢸⣿⣿⣿⣿⣿⣿⡇⢸⣿⣿⣿⣿⣿⣿",
    "       ⣿⣿⣿⣿⢰⣿⣿⣿⣿⣿⣿⣿⡇⢸⣿⣿⣿⣿⣿⣿",
]

FRAME_2 = [
    "              ⢀⣀⣤⣶⣿⣿⣿⣿⣶⣤⣀⡀",
    "          ⣠⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣦",
    "        ⣰⣿⣿⣿⣿⣿⡿⠛⠉⠉⠉⠙⢿⣿⣿⣿⣿⣿⣷⡀",
    "       ⣼⣿⣿⣿⡿⠋⠀⣠⣾⣿⣿⣷⡄⠈⢿⣿⣿⣿⣿⣷⡀",
    "      ⣾⣿⣿⣿⠏⠀⣰⣿⣿⣿⣿⣿⣿⣆⠈⣿⣿⣿⣿⣿⡄",
    "     ⢸⣿⣿⣿⠃⢰⣿⣿⣿⣿⣿⣿⣿⣿⡆⢸⣿⣿⣿⣿⣿⣿",
    "     ⣿⣿⣿⣿⢰⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⢸⣿⣿⣿⣿⣿⣿",
]

FRAME_3 = [
    "               ⣀⣤⣶⣿⣿⣿⣿⣶⣤⣀",
    "           ⣠⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣤",
    "        ⣰⣿⣿⣿⣿⣿⡿⠛⠉⠉⠙⠛⢿⣿⣿⣿⣿⣿⣷⡀",
    "       ⣼⣿⣿⣿⡿⠋⢀⣠⣾⣿⣿⣿⣷⣄⠈⠙⢿⣿⣿⣿⣿⣷⡀",
    "      ⣾⣿⣿⣿⠏⣠⣿⣿⣿⣿⣿⣿⣿⣿⣧⠈⣿⣿⣿⣿⣿⡄",
    "  ⣶⣶⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣶⣶⣶",
    "  ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
    "  ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
]

DRAGON_FRAMES_GOLD = [FRAME_1, FRAME_2, FRAME_3]

# Spinner characters and colors
SPIN_CHARS = ["\u25d0", "\u25d3", "\u25d1", "\u25d2", "\u25b0", "\u25b1"]
SPIN_COLORS = [GOLD_DIM, GOLD, GOLD_BRIGHT, GOLD_LIGHT, GOLD_BRIGHT, GOLD]
