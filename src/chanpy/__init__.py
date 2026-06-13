"""chanpy 缠论库 — 初始化时将包目录加入 sys.path。

chanpy 内部使用裸模块导入（如 from BuySellPoint.BS_Point import CBS_Point），
需要将 chanpy 包目录加入 sys.path，使内部模块可被正确解析。

使用方式：import chanpy，然后通过裸导入访问子模块，
如 from chanpy.Chan import CChan（内部会通过 sys.path 找到 Chan.py）。
"""
import sys
from pathlib import Path

_chanpy_dir = str(Path(__file__).resolve().parent)
if _chanpy_dir not in sys.path:
    sys.path.insert(0, _chanpy_dir)
