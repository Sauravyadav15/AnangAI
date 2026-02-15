import sys
from pathlib import Path

# Add backend directory to Python path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

# Import the FastAPI app
from main import app
from mangum import Mangum

# Wrap FastAPI app with Mangum
# Vercel will pass requests to this handler
# The path will be like "/health" when accessing "/api/health"
# But FastAPI routes expect "/api/health", so we need to adjust
def handler(event, context):
    # Adjust the path to include /api/ prefix
    if 'path' in event:
        original_path = event['path']
        if not original_path.startswith('/api/'):
            event['path'] = f'/api{original_path}' if original_path.startswith('/') else f'/api/{original_path}'
    
    # Use Mangum to handle the request
    mangum_handler = Mangum(app, lifespan="off")
    return mangum_handler(event, context)

