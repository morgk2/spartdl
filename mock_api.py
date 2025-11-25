import json
import uuid
from typing import Dict, Any
from datetime import datetime

class MockSpotDLAPI:
    def __init__(self):
        self.tasks = {}
        
    def get_download_link(self, spotify_url: str, format: str = "mp3", quality: str = "best") -> Dict[str, Any]:
        """Mock implementation that returns a simulated YouTube URL"""
        # Extract track ID from Spotify URL for mock purposes
        track_id = spotify_url.split("/")[-1].split("?")[0] if "/" in spotify_url else "unknown"
        
        return {
            "spotify_url": spotify_url,
            "download_url": f"https://youtube.com/watch?v=mock_{track_id}",
            "format": format,
            "quality": quality,
            "note": "This is a mock YouTube URL. In production, this would be the actual YouTube URL.",
            "timestamp": datetime.now().isoformat()
        }
    
    def get_audio_download_link(self, spotify_url: str, format: str = "mp3", quality: str = "best") -> Dict[str, Any]:
        """Mock implementation that simulates downloading audio"""
        track_id = spotify_url.split("/")[-1].split("?")[0] if "/" in spotify_url else "unknown"
        filename = f"mock_track_{track_id}.{format}"
        
        return {
            "spotify_url": spotify_url,
            "audio_download_url": f"http://localhost:8000/temp-download/{filename}",
            "filename": filename,
            "format": format,
            "quality": quality,
            "file_size": 5242880,  # 5MB mock size
            "note": "This is a mock download link. In production, this would be the actual audio file.",
            "timestamp": datetime.now().isoformat()
        }

# Simple HTTP server using Python's built-in modules
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json

class APIHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.api = MockSpotDLAPI()
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {"message": "spotDL Mock API is running", "version": "1.0.0"}
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
        except:
            self.send_response(400)
            self.end_headers()
            return
        
        if self.path == '/get/download-link':
            response = self.api.get_download_link(
                data.get('spotify_url', ''),
                data.get('format', 'mp3'),
                data.get('quality', 'best')
            )
            self._send_json_response(200, response)
        
        elif self.path == '/get/audio-download-link':
            response = self.api.get_audio_download_link(
                data.get('spotify_url', ''),
                data.get('format', 'mp3'),
                data.get('quality', 'best')
            )
            self._send_json_response(200, response)
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def _send_json_response(self, status_code: int, data: dict):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

def run_server():
    server_address = ('', 8000)
    httpd = HTTPServer(server_address, APIHandler)
    print("Mock spotDL API running on http://localhost:8000")
    print("Available endpoints:")
    print("  POST /get/download-link - Get YouTube URL")
    print("  POST /get/audio-download-link - Get audio download link")
    print("\nExample usage:")
    print('curl -X POST http://localhost:8000/get/download-link -H "Content-Type: application/json" -d \'{"spotify_url": "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh"}\'')
    httpd.serve_forever()

if __name__ == "__main__":
    run_server()
