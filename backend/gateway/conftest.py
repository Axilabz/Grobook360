import sys
from pathlib import Path

# backend/ provides `shared`; gateway/ provides `app` and MUST win on sys.path
# (the monolith also has a top-level `app` package in backend/). Gateway tests
# therefore run in their own pytest process: `cd backend/gateway && pytest`.
_here = Path(__file__).resolve().parent
_backend = str(_here.parent)
if _backend in sys.path:
    sys.path.remove(_backend)
sys.path.append(_backend)
if str(_here) in sys.path:
    sys.path.remove(str(_here))
sys.path.insert(0, str(_here))
