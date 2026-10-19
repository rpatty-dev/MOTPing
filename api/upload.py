"""
Vercel Serverless Function: /api/upload.py
Handles file intake (drag & drop Excel .xlsx, .csv, .txt) and parses registration plates.
"""
from http.server import BaseHTTPRequestHandler
import json
import io
import re
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

def extract_vehicles_from_xlsx(file_obj):
    try:
        with zipfile.ZipFile(file_obj, 'r') as z:
            shared = []
            if 'xl/sharedStrings.xml' in z.namelist():
                tree = ET.fromstring(z.read('xl/sharedStrings.xml'))
                for si in tree.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si'):
                    t = si.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')
                    shared.append(t.text if t is not None and t.text else '')

            sheet_names = [f for f in z.namelist() if f.startswith('xl/worksheets/sheet') and f.endswith('.xml')]
            if not sheet_names:
                return []
            
            sheet_target = 'xl/worksheets/sheet1.xml' if 'xl/worksheets/sheet1.xml' in sheet_names else sheet_names[0]
            tree = ET.fromstring(z.read(sheet_target))
            rows = tree.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetData/{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row')
            
            seen = set()
            vehicles = []
            for r in rows[1:]:
                cells = {}
                for c in r.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                    ref = c.attrib.get('r', '')
                    col = re.sub(r'[0-9]', '', ref)
                    v = c.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                    t = c.attrib.get('t')
                    val = ''
                    if v is not None and v.text:
                        val = shared[int(v.text)] if t == 's' else v.text
                    cells[col] = val.strip()
                vehicle = cells.get('A', '')
                raw_reg = cells.get('B', '')
                reg = re.sub(r'[^A-Za-z0-9]', '', raw_reg).upper()
                driver = cells.get('F', '')
                comments = cells.get('H', '')

                if 2 <= len(reg) <= 8 and reg not in seen:
                    seen.add(reg)
                    notes_parts = [p for p in [vehicle, driver, comments] if p]
                    vehicles.append({'vrn': reg, 'notes': ' | '.join(notes_parts), 'last_check': None, 'booked': False})
            return vehicles
    except Exception as e:
        print(f"Error parsing excel: {e}")
        return []

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            raw_body = self.rfile.read(content_length)

            content_type = self.headers.get('Content-Type', '')
            file_data = raw_body
            filename = "upload"

            if 'boundary=' in content_type:
                boundary = content_type.split('boundary=')[1].strip()
                parts = raw_body.split(f'--{boundary}'.encode())
                for p in parts:
                    if b'filename=' in p:
                        header_part, file_part = p.split(b'\r\n\r\n', 1)
                        file_data = file_part.rstrip(b'\r\n--')
                        header_str = header_part.decode('latin1', errors='ignore')
                        fn_match = re.search(r'filename="([^"]+)"', header_str)
                        if fn_match:
                            filename = fn_match.group(1)
                        break

            vehicles = []
            if filename.lower().endswith('.xlsx') or file_data[:4] == b'PK\x03\x04':
                vehicles = extract_vehicles_from_xlsx(io.BytesIO(file_data))
            else:
                text = file_data.decode('utf-8', errors='ignore')
                seen = set()
                for line in text.splitlines():
                    cleaned = line.strip()
                    if not cleaned or cleaned.startswith('#'):
                        continue
                    tokens = [t.strip() for t in re.split(r'[,;\t|]', cleaned) if t.strip()]
                    if tokens:
                        vrn = re.sub(r'[^A-Za-z0-9]', '', tokens[0]).upper()
                        if 2 <= len(vrn) <= 8 and vrn not in seen:
                            seen.add(vrn)
                            notes = ' '.join(tokens[1:]) if len(tokens) > 1 else ''
                            vehicles.append({'vrn': vrn, 'notes': notes, 'last_check': None, 'booked': False})

            self.send_json({"added": len(vehicles), "vehicles": vehicles})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def send_json(self, payload, code=200):
        body = json.dumps(payload, indent=2).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
