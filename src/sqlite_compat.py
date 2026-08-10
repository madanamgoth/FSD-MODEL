"""
sqlite_compat.py
----------------
Oracle Linux (and other old distros) ship sqlite3 < 3.35.
Chroma requires >= 3.35. If pysqlite3-binary is installed, use it
instead of the system sqlite3. No-op on Windows if the package is missing.
Must be imported BEFORE chromadb.
"""

from __future__ import annotations

try:
    import pysqlite3
    import sys

    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass
