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
import zipfile
import xml.etree.ElementTree as ET
import re
from mot_engine import query_dvla_vehicle

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "mot_fleet_state.json")

def parse_vehicles_from_excel(path):
    if not os.path.exists(path):
        return []
    try:
        with zipfile.ZipFile(path, 'r') as z:
            shared = []
            if 'xl/sharedStrings.xml' in z.namelist():
                tree = ET.fromstring(z.read('xl/sharedStrings.xml'))
                for si in tree.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si'):
                    t = si.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')
                    shared.append(t.text if t is not None and t.text else '')

            tree = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
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
                reg = cells.get('B', '').replace(' ', '').upper()
                driver = cells.get('F', '')
                comment = cells.get('K', '')
                if reg and len(reg) >= 4 and not reg.startswith('REG') and reg not in seen:
                    seen.add(reg)
                    notes_parts = [p for p in [vehicle, driver, comment] if p]
                    vehicles.append({'vrn': reg, 'notes': ' | '.join(notes_parts), 'last_check': None})
            return vehicles
    except Exception as e:
        print(f"Error parsing excel: {e}")
        return []

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
        path = parsed.path

        # 1. Single or Batch Vehicle Add
        if path == "/api/vehicles":
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            try:
                data = json.loads(body)
                items = data.get("vehicles") if isinstance(data, dict) and "vehicles" in data else ([data] if isinstance(data, dict) else data)
                state = load_fleet_state()
                existing_map = {v["vrn"]: v for v in state.get("vehicles", [])}
                added_count = 0
                updated_count = 0

                for item in items:
                    raw_vrn = item.get("vrn") or item.get("reg") or ""
                    vrn = re.sub(r'[^A-Za-z0-9]', '', raw_vrn).upper()
                    notes = item.get("notes") or ""
                    if not vrn:
                        continue
                    if vrn in existing_map:
                        if notes:
                            existing_map[vrn]["notes"] = notes
                        updated_count += 1
                    else:
                        new_veh = {"vrn": vrn, "notes": notes, "last_check": None}
                        state.setdefault("vehicles", []).append(new_veh)
                        existing_map[vrn] = new_veh
                        added_count += 1

                save_fleet_state(state)
                self.send_json({
                    "success": True,
                    "added": added_count,
                    "updated": updated_count,
                    "total": len(state.get("vehicles", []))
                })
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        # 2. Import Directly from Local Excel Path
        if path == "/api/import-excel":
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            try:
                data = json.loads(body) if body else {}
                excel_path = data.get("path", r"Z:\Vehicles - Plant\vehicles\Vehicles log 19.xlsx")
                if not os.path.exists(excel_path):
                    self.send_json({"error": f"File not found: {excel_path}"}, 404)
                    return

                extracted = parse_vehicles_from_excel(excel_path)
                state = load_fleet_state()
                existing_map = {v["vrn"]: v for v in state.get("vehicles", [])}
                added = 0
                for item in extracted:
                    vrn = item["vrn"]
                    if vrn in existing_map:
                        if item["notes"]:
                            existing_map[vrn]["notes"] = item["notes"]
                    else:
                        state.setdefault("vehicles", []).append(item)
                        existing_map[vrn] = item
                        added += 1

                save_fleet_state(state)
                self.send_json({
                    "success": True,
                    "parsed": len(extracted),
                    "added": added,
                    "total": len(state.get("vehicles", [])),
                    "path": excel_path
                })
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/vehicles":
            params = urllib.parse.parse_qs(parsed.query)
            vrn = re.sub(r'[^A-Za-z0-9]', '', params.get("vrn", [""])[0]).upper()
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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --ground: #000000;
      --surface: #0e0f11;
      --raised: #18191c;
      --border: #222429;
      --rule: #17181c;
      --control: #383a42;
      --text: #ffffff;
      --muted: #a1a1aa;
      --faint: #71717a;
      
      --accent: #10b981;
      --positive: #10b981;
      --negative: #ef4444;
      --warning: #f59e0b;
      
      --pill-pos-bg: #064e3b;
      --pill-pos-ink: #34d399;
      --pill-neg-bg: #450a0a;
      --pill-neg-ink: #f87171;
      --pill-warn-bg: #451a03;
      --pill-warn-ink: #fbbf24;
      --pill-neutral-bg: #18191c;
      --pill-neutral-ink: #a1a1aa;

      --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      --mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--ground);
      color: var(--text);
      font-family: var(--font);
      font-size: 14px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }

    .num { font-variant-numeric: tabular-nums; }

    /* Shell Layout */
    .shell {
      max-width: 1280px;
      margin: 0 auto;
      padding: 32px 24px 64px;
    }

    /* Top Navigation Bar */
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding-bottom: 24px;
      border-bottom: 1px solid var(--rule);
      margin-bottom: 28px;
    }
    .brand-wrap {
      display: flex;
      align-items: center;
      gap: 16px;
    }
    .logo-img {
      height: 38px;
      width: auto;
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    /* KPI Summary Strip */
    .kpi-strip {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      margin-bottom: 28px;
      overflow: hidden;
    }
    .kpi-cell {
      padding: 20px 24px;
    }
    .kpi-cell + .kpi-cell {
      border-left: 1px solid var(--border);
    }
    .kpi-label {
      font-size: 11px;
      font-weight: 600;
      color: var(--muted);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .kpi-value {
      font-size: 28px;
      font-weight: 600;
      line-height: 1.2;
      margin-top: 6px;
      font-variant-numeric: tabular-nums;
      display: flex;
      align-items: baseline;
      gap: 6px;
    }
    .kpi-sub {
      font-size: 12px;
      color: var(--faint);
      margin-top: 4px;
    }

    /* Panels */
    .panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px 24px;
      margin-bottom: 28px;
    }
    .panel-header {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      margin-bottom: 16px;
    }
    .panel-title {
      font-size: 15px;
      font-weight: 600;
      color: var(--text);
    }
    .panel-desc {
      font-size: 13px;
      color: var(--muted);
    }

    /* Form Controls */
    .intake-row {
      display: grid;
      grid-template-columns: 180px 1fr auto;
      gap: 12px;
    }
    .input {
      background: var(--ground);
      border: 1px solid var(--control);
      border-radius: 8px;
      padding: 10px 14px;
      color: var(--text);
      font-family: var(--font);
      font-size: 14px;
      outline: none;
      transition: border-color 0.15s ease;
    }
    .input:focus {
      border-color: #ffffff;
    }
    .input-plate {
      font-family: var(--mono);
      font-size: 15px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 1.5px;
      background: #fef08a;
      color: #0f172a;
      border: 1px solid #ca8a04;
    }
    .input-plate::placeholder {
      color: #854d0e;
      font-weight: 500;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      height: 40px;
      padding: 0 16px;
      border-radius: 8px;
      font-family: var(--font);
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      border: 1px solid transparent;
      transition: all 0.15s ease;
      white-space: nowrap;
    }
    .btn-primary {
      background: #ffffff;
      color: #000000;
    }
    .btn-primary:hover {
      background: #e4e4e7;
    }
    .btn-secondary {
      background: var(--raised);
      color: var(--text);
      border-color: var(--border);
    }
    .btn-secondary:hover {
      background: #27272a;
    }
    .btn-sm {
      height: 28px;
      padding: 0 10px;
      font-size: 12px;
      border-radius: 6px;
    }
    .btn-danger {
      background: transparent;
      color: #f87171;
      border-color: #450a0a;
    }
    .btn-danger:hover {
      background: #450a0a;
    }

    /* List Filter Toolbar */
    .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 12px;
    }
    .search-box {
      width: 280px;
    }

    /* Telemetry Table */
    .table-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow: hidden;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
    }
    th {
      background: #090a0c;
      padding: 12px 18px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--faint);
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }
    td {
      padding: 14px 18px;
      border-bottom: 1px solid var(--rule);
      vertical-align: middle;
      font-size: 13.5px;
    }
    tr:last-child td {
      border-bottom: none;
    }
    tr:hover td {
      background: rgba(255, 255, 255, 0.015);
    }

    /* Clean Yellow Number Plate Badge (NO GB) */
    .uk-plate {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: #facc15;
      color: #111827;
      font-family: var(--mono);
      font-weight: 800;
      font-size: 13.5px;
      letter-spacing: 1.2px;
      padding: 3px 10px;
      border-radius: 4px;
      border: 1px solid #ca8a04;
      box-shadow: 0 1px 2px rgba(0,0,0,0.35);
      text-transform: uppercase;
    }

    /* Status Pills */
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 3px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      white-space: nowrap;
    }
    .pill-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: currentColor;
    }
    .pill-pos {
      background: var(--pill-pos-bg);
      color: var(--pill-pos-ink);
    }
    .pill-neg {
      background: var(--pill-neg-bg);
      color: var(--pill-neg-ink);
    }
    .pill-warn {
      background: var(--pill-warn-bg);
      color: var(--pill-warn-ink);
    }
    .pill-neutral {
      background: var(--pill-neutral-bg);
      color: var(--pill-neutral-ink);
    }

    .vehicle-spec {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .spec-primary {
      font-weight: 600;
      color: var(--text);
    }
    .spec-secondary {
      font-size: 12px;
      color: var(--muted);
    }

    .actions-cell {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
    }

    /* Modal / Detail Drawer & Bulk Import */
    .modal-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.85);
      z-index: 100;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .modal-overlay.active {
      display: flex;
    }
    .modal-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      width: 100%;
      max-width: 620px;
      padding: 24px;
    }
    .modal-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid var(--rule);
      padding-bottom: 16px;
      margin-bottom: 20px;
    }
    .spec-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 14px;
      margin-bottom: 20px;
    }
    .spec-item {
      background: var(--ground);
      border: 1px solid var(--rule);
      border-radius: 8px;
      padding: 12px;
    }
    .spec-item-label {
      font-size: 11px;
      color: var(--faint);
      text-transform: uppercase;
      font-weight: 600;
    }
    .spec-item-val {
      font-size: 14.5px;
      font-weight: 600;
      margin-top: 4px;
      color: var(--text);
    }

    .textarea-bulk {
      width: 100%;
      height: 180px;
      background: var(--ground);
      border: 1px solid var(--control);
      border-radius: 8px;
      padding: 12px;
      color: var(--text);
      font-family: var(--mono);
      font-size: 13px;
      resize: vertical;
      outline: none;
      margin-bottom: 16px;
      line-height: 1.6;
    }
    .textarea-bulk:focus {
      border-color: #ffffff;
    }

    .progress-bar-wrap {
      background: var(--ground);
      border: 1px solid var(--border);
      border-radius: 6px;
      height: 8px;
      overflow: hidden;
      margin-top: 8px;
    }
    .progress-fill {
      background: var(--accent);
      height: 100%;
      width: 0%;
      transition: width 0.2s ease;
    }

    @media (max-width: 860px) {
      .kpi-strip {
        grid-template-columns: repeat(2, 1fr);
      }
      .kpi-cell:nth-child(2) {
        border-right: none;
      }
      .kpi-cell:nth-child(3), .kpi-cell:nth-child(4) {
        border-top: 1px solid var(--border);
      }
      .intake-row {
        grid-template-columns: 1fr;
      }
      .toolbar {
        flex-direction: column;
        align-items: stretch;
      }
      .search-box {
        width: 100%;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <!-- Topbar Navigation -->
    <header class="topbar">
      <div class="brand-wrap">
        <img src="/logo.svg" alt="MOTPing" class="logo-img" />
      </div>
      <div class="header-actions">
        <button class="btn btn-secondary btn-sm" onclick="syncExcel()">Sync Excel Log</button>
        <button class="btn btn-secondary btn-sm" onclick="openBulkModal()">Paste Bulk Plates</button>
        <button class="btn btn-primary btn-sm" id="btnScanAll" onclick="scanAllLive()">Scan All Expiries</button>
      </div>
    </header>

    <!-- KPI Metric Strip -->
    <section class="kpi-strip">
      <div class="kpi-cell">
        <div class="kpi-label">Monitored Fleet</div>
        <div class="kpi-value" id="kpiTotal">0 <small>plates</small></div>
        <div class="kpi-sub">Active fleet intake</div>
      </div>
      <div class="kpi-cell">
        <div class="kpi-label">MOT Valid</div>
        <div class="kpi-value" style="color: #34d399;" id="kpiValid">0 <small>road legal</small></div>
        <div class="kpi-sub">Valid test certificates</div>
      </div>
      <div class="kpi-cell">
        <div class="kpi-label">Expiring Soon</div>
        <div class="kpi-value" style="color: #fbbf24;" id="kpiExpiring">0 <small>&le; 30 days</small></div>
        <div class="kpi-sub">Urgent booking required</div>
      </div>
      <div class="kpi-cell">
        <div class="kpi-label">Expired / Attention</div>
        <div class="kpi-value" style="color: #f87171;" id="kpiExpired">0 <small>overdue</small></div>
        <div class="kpi-sub">Unroadworthy or lapsed</div>
      </div>
    </section>

    <!-- Scan Progress (hidden by default) -->
    <div id="scanProgressCard" style="display: none; margin-bottom: 24px;" class="panel">
      <div style="display: flex; justify-content: space-between; align-items: baseline;">
        <span style="font-weight: 600;" id="scanProgressText">Scanning DVLA telemetry...</span>
        <span style="font-size: 12px; color: var(--muted);" id="scanProgressCount">0 / 0</span>
      </div>
      <div class="progress-bar-wrap">
        <div class="progress-fill" id="scanProgressFill"></div>
      </div>
    </div>

    <!-- Plate Intake Panel -->
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2 class="panel-title">Add Vehicle to Watchlist</h2>
          <p class="panel-desc">Automatic query against DVLA vehicle & test certificate records.</p>
        </div>
      </div>
      <form class="intake-row" onsubmit="addVehicle(event)">
        <input type="text" id="vrnInput" class="input input-plate" placeholder="REG PLATE" maxlength="10" autocomplete="off" required />
        <input type="text" id="notesInput" class="input" placeholder="Notes (e.g. Ford Transit • Driver Name • Fleet #04)" />
        <button type="submit" class="btn btn-primary">+ Track Plate</button>
      </form>
    </section>

    <!-- Fleet Telemetry Table -->
    <section>
      <div class="toolbar">
        <div>
          <h2 style="font-size: 18px; font-weight: 600;">Fleet Vehicles</h2>
          <p style="font-size: 13px; color: var(--muted); margin-top: 2px;" id="listCount">Displaying tracked vehicles</p>
        </div>
        <input type="text" id="searchInput" class="input search-box" placeholder="Filter by plate, make, or notes..." oninput="filterFleet()" />
      </div>

      <div class="table-card">
        <table>
          <thead>
            <tr>
              <th>Plate</th>
              <th>Vehicle Specification</th>
              <th>MOT Status</th>
              <th>MOT Expiry</th>
              <th>Road Tax</th>
              <th>Notes / Driver</th>
              <th style="text-align: right;">Action</th>
            </tr>
          </thead>
          <tbody id="fleetBody">
            <tr><td colspan="7" style="text-align: center; color: var(--muted); padding: 32px;">Loading fleet telemetry...</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>

  <!-- Bulk Paste Modal -->
  <div class="modal-overlay" id="bulkModal" onclick="closeBulkModal(event)">
    <div class="modal-card" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div>
          <h3 style="font-size: 17px; font-weight: 600;">Paste Vehicle List</h3>
          <p style="font-size: 13px; color: var(--muted); margin-top: 4px;">Paste raw registration plates or lines with notes (e.g. from Excel, CSV, or WhatsApp).</p>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="closeBulkModal()">✕</button>
      </div>
      <textarea id="bulkInput" class="textarea-bulk" placeholder="BJ12 XDH, Caolan Ohare&#10;BMZ 2393 - VW Transporter&#10;AFZ 7814&#10;P3 RCV"></textarea>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 12px; color: var(--faint);">Accepts comma, tab, dash or line separated formats.</span>
        <div style="display: flex; gap: 8px;">
          <button class="btn btn-secondary btn-sm" onclick="closeBulkModal()">Cancel</button>
          <button class="btn btn-primary btn-sm" onclick="submitBulkPlates()">Import Plates</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Telemetry Detail Drawer / Modal -->
  <div class="modal-overlay" id="detailDrawer" onclick="closeDrawer(event)">
    <div class="modal-card" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div>
          <span class="uk-plate" id="drawerVrn">REG</span>
          <h3 style="font-size: 17px; font-weight: 600; margin-top: 8px;" id="drawerTitle">Vehicle Telemetry</h3>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="closeDrawer()">✕</button>
      </div>
      <div class="spec-grid">
        <div class="spec-item">
          <div class="spec-item-label">Make & Model</div>
          <div class="spec-item-val" id="specMake">-</div>
        </div>
        <div class="spec-item">
          <div class="spec-item-label">Year of Manufacture</div>
          <div class="spec-item-val" id="specYear">-</div>
        </div>
        <div class="spec-item">
          <div class="spec-item-label">Engine Capacity</div>
          <div class="spec-item-val" id="specCc">-</div>
        </div>
        <div class="spec-item">
          <div class="spec-item-label">Fuel Type</div>
          <div class="spec-item-val" id="specFuel">-</div>
        </div>
        <div class="spec-item">
          <div class="spec-item-label">Color</div>
          <div class="spec-item-val" id="specColor">-</div>
        </div>
        <div class="spec-item">
          <div class="spec-item-label">CO2 Emissions</div>
          <div class="spec-item-val" id="specCo2">-</div>
        </div>
        <div class="spec-item">
          <div class="spec-item-label">MOT Expiry Date</div>
          <div class="spec-item-val num" id="specMot">-</div>
        </div>
        <div class="spec-item">
          <div class="spec-item-label">Road Tax Due Date</div>
          <div class="spec-item-val num" id="specTax">-</div>
        </div>
      </div>
      <div style="display: flex; justify-content: flex-end;">
        <button class="btn btn-primary btn-sm" onclick="closeDrawer()">Done</button>
      </div>
    </div>
  </div>

  <script>
    let fleetCache = [];
    let telemetryCache = {};
    let isScanningAll = false;

    async function loadFleet() {
      try {
        const res = await fetch('/api/fleet');
        const data = await res.json();
        fleetCache = data.vehicles || [];
        // Load any cached telemetry from file
        for (const v of fleetCache) {
          if (v.last_check && v.last_check.found) {
            telemetryCache[v.vrn] = v.last_check;
          }
        }
        renderFleet();
      } catch (e) {
        document.getElementById('fleetBody').innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--negative); padding: 24px;">Failed to load fleet registry.</td></tr>';
      }
    }

    function renderFleet() {
      const tbody = document.getElementById('fleetBody');
      const query = (document.getElementById('searchInput').value || '').toLowerCase().trim();
      tbody.innerHTML = '';

      const filtered = fleetCache.filter(v => {
        const t = telemetryCache[v.vrn] || {};
        return v.vrn.toLowerCase().includes(query) ||
               (v.notes && v.notes.toLowerCase().includes(query)) ||
               (t.make && t.make.toLowerCase().includes(query));
      });

      document.getElementById('kpiTotal').innerHTML = fleetCache.length + ' <small>plates</small>';
      document.getElementById('listCount').textContent = `Tracking ${fleetCache.length} vehicles (${filtered.length} matching filter)`;

      if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--muted); padding: 32px;">No vehicles found matching criteria.</td></tr>';
        return;
      }

      for (const v of filtered) {
        const row = document.createElement('tr');
        row.id = 'row-' + v.vrn;
        
        row.innerHTML = `
          <td>
            <span class="uk-plate">${v.vrn}</span>
          </td>
          <td id="spec-${v.vrn}">
            <div class="vehicle-spec">
              <span class="spec-primary" id="make-${v.vrn}">Queued...</span>
              <span class="spec-secondary" id="attr-${v.vrn}">Ready for scan</span>
            </div>
          </td>
          <td id="status-${v.vrn}">
            <span class="pill pill-neutral"><span class="pill-dot"></span>Idle</span>
          </td>
          <td id="mot-${v.vrn}" class="num" style="font-weight: 600;">-</td>
          <td id="tax-${v.vrn}" class="num">-</td>
          <td style="color: var(--muted); font-size: 13px;">${v.notes || '<span style="color:var(--faint);">—</span>'}</td>
          <td style="text-align: right;">
            <div class="actions-cell">
              <button class="btn btn-secondary btn-sm" onclick="openDetails('${v.vrn}')">Inspect</button>
              <button class="btn btn-secondary btn-sm" onclick="checkPlate('${v.vrn}')">Scan</button>
              <button class="btn btn-danger btn-sm" onclick="removePlate('${v.vrn}')">✕</button>
            </div>
          </td>
        `;
        tbody.appendChild(row);

        if (telemetryCache[v.vrn]) {
          applyTelemetry(v.vrn, telemetryCache[v.vrn]);
        }
      }

      updateKpis();
    }

    async function checkPlate(vrn) {
      const statusEl = document.getElementById('status-' + vrn);
      if (statusEl) {
        statusEl.innerHTML = '<span class="pill pill-neutral"><span class="pill-dot" style="background:#38bdf8;"></span>Querying</span>';
      }

      try {
        const res = await fetch('/api/check?vrn=' + encodeURIComponent(vrn));
        const data = await res.json();
        telemetryCache[vrn] = data;
        applyTelemetry(vrn, data);
        updateKpis();
        return data;
      } catch (e) {
        if (statusEl) {
          statusEl.innerHTML = '<span class="pill pill-neg"><span class="pill-dot"></span>Error</span>';
        }
        return null;
      }
    }

    function applyTelemetry(vrn, data) {
      const makeEl = document.getElementById('make-' + vrn);
      const attrEl = document.getElementById('attr-' + vrn);
      const statusEl = document.getElementById('status-' + vrn);
      const motEl = document.getElementById('mot-' + vrn);
      const taxEl = document.getElementById('tax-' + vrn);

      if (!makeEl) return;

      if (data.found) {
        makeEl.textContent = (data.make || 'Vehicle Spec Identified');
        attrEl.textContent = [data.year, data.fuel_type, data.cylinder_capacity, data.color].filter(Boolean).join(' • ');

        let pill = '<span class="pill pill-pos"><span class="pill-dot"></span>Valid</span>';
        if (data.is_mot_expired) {
          pill = '<span class="pill pill-neg"><span class="pill-dot"></span>Expired</span>';
        } else if (data.days_until_mot !== null && data.days_until_mot <= 30) {
          pill = `<span class="pill pill-warn"><span class="pill-dot"></span>${data.days_until_mot}d left</span>`;
        }
        statusEl.innerHTML = pill;

        motEl.innerHTML = data.mot_expiry_date ? `${data.mot_expiry_date}` : '<span style="color:var(--faint);">No Test</span>';
        
        let taxDisplay = data.tax_due_date || 'N/A';
        if (data.tax_status) taxDisplay += ` <small style="color:var(--muted)">(${data.tax_status})</small>`;
        taxEl.innerHTML = taxDisplay;
      } else {
        makeEl.textContent = 'Vehicle Not Found';
        attrEl.textContent = 'DVLA record could not be matched';
        statusEl.innerHTML = '<span class="pill pill-neg"><span class="pill-dot"></span>Not Found</span>';
      }
    }

    function updateKpis() {
      let valid = 0, expiring = 0, expired = 0;
      for (const v of fleetCache) {
        const t = telemetryCache[v.vrn];
        if (t && t.found) {
          if (t.is_mot_expired) {
            expired++;
          } else if (t.days_until_mot !== null && t.days_until_mot <= 30) {
            expiring++;
          } else {
            valid++;
          }
        }
      }
      document.getElementById('kpiValid').innerHTML = valid + ' <small>road legal</small>';
      document.getElementById('kpiExpiring').innerHTML = expiring + ' <small>&le; 30 days</small>';
      document.getElementById('kpiExpired').innerHTML = expired + ' <small>overdue</small>';
    }

    function filterFleet() {
      renderFleet();
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
      await loadFleet();
      checkPlate(vrn.replace(/\\s+/g, '').toUpperCase());
    }

    async function removePlate(vrn) {
      if (!confirm(`Remove registration ${vrn} from fleet monitoring?`)) return;
      await fetch('/api/vehicles?vrn=' + encodeURIComponent(vrn), { method: 'DELETE' });
      delete telemetryCache[vrn];
      loadFleet();
    }

    async function syncExcel() {
      const defaultPath = "Z:\\\\Vehicles - Plant\\\\vehicles\\\\Vehicles log 19.xlsx";
      const path = prompt("Enter Excel file path to import:", defaultPath);
      if (!path) return;

      try {
        const res = await fetch('/api/import-excel', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ path: path.replace(/\\\\/g, '\\') })
        });
        const data = await res.json();
        if (data.success) {
          alert(`Successfully imported from Excel!\nFound: ${data.parsed} vehicles\nNew additions: ${data.added}\nTotal in Fleet: ${data.total}`);
          loadFleet();
        } else {
          alert('Import failed: ' + (data.error || 'Unknown error'));
        }
      } catch (e) {
        alert('Network or server error while syncing Excel: ' + e);
      }
    }

    function openBulkModal() {
      document.getElementById('bulkModal').classList.add('active');
    }

    function closeBulkModal() {
      document.getElementById('bulkModal').classList.remove('active');
    }

    async function submitBulkPlates() {
      const text = document.getElementById('bulkInput').value;
      if (!text.trim()) return;

      const lines = text.split(/\\r?\\n/);
      const vehicles = [];
      const plateRegex = /([A-Za-z]{1,3}[0-9]{1,4}[A-Za-z]{0,3}|[A-Za-z]{2}[0-9]{2}\\s?[A-Za-z]{3})/i;

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        
        // Match VRN and parse remaining as notes
        const match = trimmed.match(plateRegex);
        if (match) {
          const rawVrn = match[0].replace(/\\s+/g, '').toUpperCase();
          const notes = trimmed.replace(match[0], '').replace(/^[,\\-\\t\\s|]+|[,\\-\\t\\s|]+$/g, '').trim();
          vehicles.push({ vrn: rawVrn, notes: notes });
        }
      }

      if (vehicles.length === 0) {
        alert("No valid UK registration plates found in pasted text.");
        return;
      }

      try {
        const res = await fetch('/api/vehicles', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ vehicles: vehicles })
        });
        const data = await res.json();
        alert(`Bulk Import Complete!\nAdded: ${data.added}\nUpdated: ${data.updated}\nTotal Fleet: ${data.total}`);
        closeBulkModal();
        document.getElementById('bulkInput').value = '';
        loadFleet();
      } catch (e) {
        alert('Error submitting bulk plates: ' + e);
      }
    }

    async function scanAllLive() {
      if (isScanningAll) return;
      isScanningAll = true;

      const btn = document.getElementById('btnScanAll');
      btn.disabled = true;
      btn.textContent = 'Scanning Fleet...';

      const progCard = document.getElementById('scanProgressCard');
      const progText = document.getElementById('scanProgressText');
      const progCount = document.getElementById('scanProgressCount');
      const progFill = document.getElementById('scanProgressFill');

      progCard.style.display = 'block';

      const total = fleetCache.length;
      let count = 0;

      for (const v of fleetCache) {
        count++;
        progText.textContent = `Scanning ${v.vrn} (${count} of ${total})...`;
        progCount.textContent = `${count} / ${total}`;
        progFill.style.width = Math.round((count / total) * 100) + '%';

        await checkPlate(v.vrn);
        // Small delay to be respectful of DVLA rate limits
        await new Promise(r => setTimeout(r, 600));
      }

      progText.textContent = 'Fleet Telemetry Scan Complete!';
      setTimeout(() => {
        progCard.style.display = 'none';
        btn.disabled = false;
        btn.textContent = 'Scan All Expiries';
        isScanningAll = false;
      }, 2500);
    }

    function openDetails(vrn) {
      const data = telemetryCache[vrn] || {};
      document.getElementById('drawerVrn').textContent = vrn;
      document.getElementById('drawerTitle').textContent = data.make || 'Vehicle Telemetry';
      document.getElementById('specMake').textContent = data.make || 'Unknown';
      document.getElementById('specYear').textContent = data.year || 'Unknown';
      document.getElementById('specCc').textContent = data.cylinder_capacity || 'N/A';
      document.getElementById('specFuel').textContent = data.fuel_type || 'N/A';
      document.getElementById('specColor').textContent = data.color || 'N/A';
      document.getElementById('specCo2').textContent = data.co2_emissions || 'N/A';
      document.getElementById('specMot').textContent = data.mot_expiry_date || 'N/A';
      document.getElementById('specTax').textContent = (data.tax_due_date || 'N/A') + (data.tax_status ? ` (${data.tax_status})` : '');
      document.getElementById('detailDrawer').classList.add('active');
    }

    function closeDrawer(e) {
      document.getElementById('detailDrawer').classList.remove('active');
    }

    // Initial load
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
