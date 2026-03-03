from pathlib import Path
import sys

# Ensure backend package is importable when running in Vercel's api/ runtime.
BACKEND_PATH = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from main import app
