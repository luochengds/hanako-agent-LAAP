#!/usr/bin/env python3
"""LAAP V5 — CLI entry (兼容直接调用和 python -m laap)"""
import os, sys
# 从 cli/laap_main.py 找到 D:\LAAP 根目录
_here = os.path.dirname(os.path.abspath(__file__))  # .../laap/cli/
_laap_root = os.path.dirname(os.path.dirname(_here))  # D:\LAAP
if _laap_root not in sys.path:
    sys.path.insert(0, _laap_root)
os.chdir(_laap_root)
from laap.__main__ import main


if __name__ == "__main__":
    sys.exit(main())
