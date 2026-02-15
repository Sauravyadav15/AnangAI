import sys
import os
import json
from pathlib import Path

# Add backend directory to Python path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

# Set working directory to backend for file access
os.chdir(backend_path)

# Import the FastAPI app
try:
    from main import app
    from mangum import Mangum
    
    # Create Mangum handler once (more efficient)
    mangum_handler = Mangum(app, lifespan="off")
except Exception as e:
    print(f"Failed to import FastAPI app: {e}")
    import traceback
    traceback.print_exc()
    mangum_handler = None

def handler(event, context=None):
    """
    Vercel Python serverless function handler.
    Converts Vercel's event format to AWS Lambda format for Mangum.
    """
    try:
        if mangum_handler is None:
            return {
                'statusCode': 500,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({"error": "FastAPI app not loaded"})
            }
        
        # Debug: log the event structure (will appear in Vercel logs)
        print(f"Event type: {type(event)}")
        if isinstance(event, dict):
            print(f"Event keys: {list(event.keys())}")
        
        # Extract path from event - Vercel Python functions use AWS Lambda-compatible format
        # The path should already include /api/ from the route
        path = None
        method = 'GET'
        headers = {}
        body = None
        query_params = None
        
        # Handle different event formats
        if isinstance(event, dict):
            # Try to get path from various possible locations (Vercel uses different formats)
            if 'path' in event:
                path = event['path']
            elif 'rawPath' in event:
                path = event['rawPath']
            elif 'requestContext' in event:
                if 'http' in event['requestContext']:
                    path = event['requestContext']['http'].get('path')
                    method = event['requestContext']['http'].get('method', 'GET')
                elif 'path' in event['requestContext']:
                    path = event['requestContext']['path']
            
            # Get method
            if 'httpMethod' in event:
                method = event['httpMethod']
            elif 'requestContext' in event:
                if 'http' in event['requestContext']:
                    method = event['requestContext']['http'].get('method', 'GET')
                elif 'httpMethod' in event['requestContext']:
                    method = event['requestContext']['httpMethod']
            
            # Get headers (normalize to dict)
            if 'headers' in event:
                headers = event['headers'] if isinstance(event['headers'], dict) else {}
                # Ensure headers are lowercase (HTTP header standard)
                headers = {k.lower(): v for k, v in headers.items()}
            
            # Get body
            if 'body' in event:
                body = event['body']
                # If body is a string, keep it; if dict, convert to JSON string
                if isinstance(body, dict):
                    body = json.dumps(body)
            
            # Get query parameters
            if 'queryStringParameters' in event:
                query_params = event['queryStringParameters']
        
        # If path is still None, try to construct from available info
        if path is None:
            print("WARNING: Path not found in event!")
            print(f"Event structure: {json.dumps(event, default=str, indent=2)}")
            # For Vercel catch-all routes [...path], the path should be in the route
            # But if not found, we need to construct it
            # The route /api/(.*) -> /api/[...path] means the full path is /api/chat
            # Try to get from URL or use a sensible default
            if 'url' in event:
                from urllib.parse import urlparse
                parsed = urlparse(event['url'])
                path = parsed.path
            else:
                # This shouldn't happen, but if it does, log it
                print("ERROR: Cannot determine path from event!")
                path = '/api/chat'  # Fallback
        
        # CRITICAL: Ensure path starts with /api/ for FastAPI routes
        # Vercel's catch-all route should already include /api/, but double-check
        if not path.startswith('/api/'):
            if path.startswith('/'):
                path = f'/api{path}'
            else:
                path = f'/api/{path}'
        
        print(f"Final path: {path}, method: {method}")
        
        # Build Lambda-compatible event for Mangum
        lambda_event = {
            'httpMethod': method,
            'path': path,
            'headers': headers if headers else {},
            'body': body if body else None,
            'queryStringParameters': query_params,
            'requestContext': {
                'http': {
                    'method': method,
                    'path': path,
                }
            },
            'isBase64Encoded': False
        }
        
        # Handle the request with Mangum
        response = mangum_handler(lambda_event, context or {})
        
        # Ensure response is in correct format
        if isinstance(response, dict):
            status_code = response.get('statusCode', 200)
            response_headers = response.get('headers', {})
            response_body = response.get('body', '')
            
            # Ensure Content-Type header if not present
            if 'Content-Type' not in response_headers:
                response_headers['Content-Type'] = 'application/json'
            
            print(f"Response status: {status_code}")
            return {
                'statusCode': status_code,
                'headers': response_headers,
                'body': response_body
            }
        else:
            return response
            
    except Exception as e:
        print(f"Error in handler: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({"error": f"Internal server error: {str(e)}"})
        }
