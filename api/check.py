"""
Vercel Serverless Function: /api/check.py
Queries DVLA/DVSA vehicle and MOT telemetry in real-time.
"""
from http.server import BaseHTTPRequestHandler
import urllib.parse
import json
import os
import sys

# Ensure current folder / parent folder is in python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from mot_engine import query_dvla_vehicle
except ImportError:
    # Direct import fallback if in same or different layout
    import mot_engine
    query_dvla_vehicle = mot_engine.query_dvla_vehicle

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        vrn = params.get("vrn", [""])[0].strip()

        if not vrn:
            self.send_json({"error": "Missing 'vrn' query parameter"}, 400)
            return

        result = query_dvla_vehicle(vrn)
        self.send_json(result)

    def send_json(self, payload, code=200):
        body = json.dumps(payload, indent=2).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
