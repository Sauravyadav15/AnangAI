import sys
import os
from pathlib import Path

# Add backend directory to Python path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

# Import the FastAPI app
from main import app
from mangum import Mangum

# Wrap FastAPI app with Mangum for Vercel serverless functions
handler = Mangum(app, lifespan="off")

