"""
MOTPing REST API & Web Dashboard Service
Standard library HTTP server with JSON REST API and responsive fleet dashboard.
Endpoints:
  GET /api/check?vrn=ABC1234  -> Query live DVLA data for single vehicle
  GET /api/fleet              -> Return cached fleet inventory status
  POST /api/vehicles          -> Add vehicle to watch list
  DELETE /api/vehicles?vrn=X  -> Remove vehicle from watch list
  GET /                       -> Interactive Web Dashboard
"""

import http.server
import socketserver
import urllib.parse
import json
import os
import sys
from mot_engine import query_dvla_vehicle

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "mot_fleet_state.json")

def load_fleet_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "vehicles": [
            {"vrn": "P3RCV", "notes": "Mercedes Saloon", "last_check": None}
        ]
    }

def save_fleet_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Error saving fleet state: {e}")

class MOTPingHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Concise logging
        print(f"[{self.log_date_time_string()}] {self.command} {self.path} - {args[1]}")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        # 1. API: Single Vehicle Lookup
        if path == "/api/check":
            vrn = params.get("vrn", [""])[0].strip()
            if not vrn:
                self.send_json({"error": "Missing 'vrn' query parameter"}, 400)
                return
            result = query_dvla_vehicle(vrn)
            self.send_json(result)
            return

        # 2. API: Fleet Inventory List
        if path == "/api/fleet":
            state = load_fleet_state()
            self.send_json(state)
            return

        # 3. Static Logo
        if path == "/logo.svg":
            logo_path = os.path.join(BASE_DIR, "logo.svg")
            if os.path.exists(logo_path):
                with open(logo_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        # 4. Interactive Web Dashboard
        if path == "/" or path == "/index.html":
            self.serve_dashboard()
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"404 Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/vehicles":
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            try:
                data = json.loads(body)
                vrn = data.get("vrn", "").replace(" ", "").upper()
                notes = data.get("notes", "")
                if not vrn:
                    self.send_json({"error": "VRN is required"}, 400)
                    return

                state = load_fleet_state()
                existing = [v for v in state.get("vehicles", []) if v["vrn"] == vrn]
                if existing:
                    existing[0]["notes"] = notes
                else:
                    state.setdefault("vehicles", []).append({
                        "vrn": vrn,
                        "notes": notes,
                        "last_check": None
                    })
                save_fleet_state(state)
                self.send_json({"success": True, "message": f"Vehicle {vrn} added to watchlist."})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/vehicles":
            params = urllib.parse.parse_qs(parsed.query)
            vrn = params.get("vrn", [""])[0].replace(" ", "").upper()
            state = load_fleet_state()
            state["vehicles"] = [v for v in state.get("vehicles", []) if v["vrn"] != vrn]
            save_fleet_state(state)
            self.send_json({"success": True, "message": f"Vehicle {vrn} removed from watchlist."})
            return
        self.send_response(404)
        self.end_headers()

    def send_json(self, data, code=200):
        body = json.dumps(data, indent=2).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_dashboard(self):
        html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MOTPing — Fleet MOT & Tax Telemetry</title>
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #111827;
      --border: #1f2937;
      --text: #f9fafb;
      --muted: #9ca3af;
      --accent: #10b981;
      --danger: #ef4444;
      --warning: #f59e0b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); padding: 24px; }
    .container { max-width: 1040px; margin: 0 auto; }
    header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid var(--border); }
    .logo-img { height: 46px; }
    .badge { font-family: monospace; font-size: 11px; padding: 3px 8px; border-radius: 4px; font-weight: bold; text-transform: uppercase; }
    .badge-valid { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
    .badge-expired { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
    .badge-warning { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
    
    .panel { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 24px; }
    .input-row { display: flex; gap: 12px; margin-top: 14px; }
    input { background: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 10px 14px; color: #fff; font-size: 14px; outline: none; }
    input:focus { border-color: var(--accent); }
    .vrm-input { font-family: monospace; font-size: 16px; font-weight: bold; text-transform: uppercase; width: 160px; letter-spacing: 1px; }
    button { background: var(--accent); color: #022c22; font-weight: bold; border: none; padding: 10px 18px; border-radius: 6px; cursor: pointer; transition: 0.2s; }
    button:hover { opacity: 0.9; }
    
    table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13.5px; }
    th { text-align: left; padding: 12px; color: var(--muted); border-bottom: 1px solid var(--border); font-size: 11px; text-transform: uppercase; font-family: monospace; }
    td { padding: 14px 12px; border-bottom: 1px solid #1f2937; }
    tr:hover td { background: rgba(255, 255, 255, 0.02); }
    .vrm-pill { background: #fef08a; color: #1e293b; font-family: monospace; font-weight: 900; font-size: 14px; padding: 4px 10px; border-radius: 4px; display: inline-block; letter-spacing: 0.5px; border: 1px solid #ca8a04; }
    .del-btn { background: transparent; color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3); padding: 4px 8px; font-size: 11px; border-radius: 4px; }
    .del-btn:hover { background: rgba(239, 68, 68, 0.15); }
    .check-btn { background: #1e293b; color: #38bdf8; border: 1px solid #334155; padding: 4px 8px; font-size: 11px; border-radius: 4px; margin-right: 6px; }
    .check-btn:hover { background: #334155; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <img src="/logo.svg" alt="MOTPing Logo" class="logo-img" />
      <div>
        <span class="badge badge-valid">DVLA Direct Engine</span>
      </div>
    </header>

    <div class="panel">
      <h3 style="font-size: 16px;">Add Vehicle to MOT & Tax Watchlist</h3>
      <p style="color: var(--muted); font-size: 13px; margin-top: 4px;">Track MOT expiry dates and road tax statuses across your entire fleet.</p>
      <form id="addForm" class="input-row" onsubmit="addVehicle(event)">
        <input type="text" id="vrnInput" class="vrm-input" placeholder="e.g. P3 RCV" required />
        <input type="text" id="notesInput" placeholder="Vehicle Notes / Driver (optional)" style="flex: 1;" />
        <button type="submit">+ Track Plate</button>
      </form>
    </div>

    <div class="panel">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <h3 style="font-size: 16px;">Monitored Fleet</h3>
        <button onclick="refreshAll()" style="background: #1e293b; color: #94a3b8; border: 1px solid #334155; font-size: 12px; padding: 6px 12px;">Refresh All</button>
      </div>
      <table id="fleetTable">
        <thead>
          <tr>
            <th>Registration</th>
            <th>Make / Model</th>
            <th>MOT Status</th>
            <th>MOT Expiry</th>
            <th>Tax Due</th>
            <th>Notes</th>
            <th style="text-align: right;">Action</th>
          </tr>
        </thead>
        <tbody id="fleetBody">
          <tr><td colspan="7" style="text-align: center; color: var(--muted); padding: 20px;">Loading fleet telemetry...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <script>
    async function loadFleet() {
      const res = await fetch('/api/fleet');
      const data = await res.json();
      const tbody = document.getElementById('fleetBody');
      tbody.innerHTML = '';
      
      for (const v of data.vehicles || []) {
        const row = document.createElement('tr');
        row.id = 'row-' + v.vrn;
        row.innerHTML = `
          <td><span class="vrm-pill">${v.vrn}</span></td>
          <td id="make-${v.vrn}" style="color: var(--muted);">Checking...</td>
          <td id="status-${v.vrn}"><span class="badge" style="background:#1e293b; color:#94a3b8;">Scanning</span></td>
          <td id="mot-${v.vrn}">...</td>
          <td id="tax-${v.vrn}">...</td>
          <td style="color: var(--muted);">${v.notes || '-'}</td>
          <td style="text-align: right;">
            <button class="check-btn" onclick="checkPlate('${v.vrn}')">Scan</button>
            <button class="del-btn" onclick="removePlate('${v.vrn}')">Remove</button>
          </td>
        `;
        tbody.appendChild(row);
        checkPlate(v.vrn);
      }
    }

    async function checkPlate(vrn) {
      document.getElementById('status-' + vrn).innerHTML = '<span class="badge" style="background:#1e293b; color:#38bdf8;">Querying...</span>';
      try {
        const res = await fetch('/api/check?vrn=' + encodeURIComponent(vrn));
        const data = await res.json();
        if (data.found) {
          document.getElementById('make-' + vrn).textContent = (data.make || 'Unknown') + ' (' + (data.color || '') + ')';
          
          let badge = '<span class="badge badge-valid">Valid</span>';
          if (data.is_mot_expired) {
            badge = '<span class="badge badge-expired">Expired</span>';
          } else if (data.days_until_mot !== null && data.days_until_mot <= 30) {
            badge = '<span class="badge badge-warning">' + data.days_until_mot + 'd left</span>';
          }
          document.getElementById('status-' + vrn).innerHTML = badge;
          document.getElementById('mot-' + vrn).innerHTML = '<b>' + (data.mot_expiry_date || 'N/A') + '</b>';
          document.getElementById('tax-' + vrn).textContent = (data.tax_due_date || 'N/A') + ' (' + (data.tax_status || '') + ')';
        } else {
          document.getElementById('status-' + vrn).innerHTML = '<span class="badge badge-expired">Not Found</span>';
        }
      } catch (e) {
        document.getElementById('status-' + vrn).innerHTML = '<span class="badge badge-expired">Error</span>';
      }
    }

    async function addVehicle(e) {
      e.preventDefault();
      const vrn = document.getElementById('vrnInput').value.trim();
      const notes = document.getElementById('notesInput').value.trim();
      if (!vrn) return;
      await fetch('/api/vehicles', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ vrn, notes })
      });
      document.getElementById('vrnInput').value = '';
      document.getElementById('notesInput').value = '';
      loadFleet();
    }

    async function removePlate(vrn) {
      if (!confirm('Remove plate ' + vrn + ' from monitoring?')) return;
      await fetch('/api/vehicles?vrn=' + encodeURIComponent(vrn), { method: 'DELETE' });
      loadFleet();
    }

    function refreshAll() {
      loadFleet();
    }

    loadFleet();
  </script>
</body>
</html>
"""
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def run_server(port=8080):
    handler = MOTPingHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"\n[MOTPing] Web App & REST API active at http://localhost:{port}")
        print(f"[MOTPing] Endpoints:")
        print(f"  - Dashboard: http://localhost:{port}/")
        print(f"  - Query VRN: http://localhost:{port}/api/check?vrn=P3RCV")
        print(f"  - Fleet API: http://localhost:{port}/api/fleet")
        httpd.serve_forever()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)
