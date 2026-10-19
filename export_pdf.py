"""
Generate MOTPing Expired & Expiring Vehicles PDF Report
Uses Microsoft Edge headless to print a high-grade HTML template to PDF.
"""
import os
import sys
import json
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "mot_fleet_state.json")
REPORT_HTML = os.path.join(BASE_DIR, "report_temp.html")
DESKTOP_PDF = os.path.join(os.path.expanduser("~/Desktop"), "MOT_Expired_and_Expiring_Report.pdf")
LOCAL_PDF = os.path.join(BASE_DIR, "MOT_Expired_and_Expiring_Report.pdf")

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

def find_edge():
    for p in EDGE_PATHS:
        if os.path.exists(p):
            return p
    return None

def build_report_html(state):
    vehicles = state.get("vehicles", [])
    
    expired = []
    expiring = []
    
    for v in vehicles:
        lc = v.get("last_check") or {}
        days = lc.get("days_until_mot")
        status = lc.get("mot_status")
        is_exp = lc.get("is_mot_expired")
        booked = v.get("booked", False)
        
        item = {
            "vrn": v.get("vrn", ""),
            "make": lc.get("make") or "UNKNOWN",
            "year": lc.get("year") or "-",
            "fuel": lc.get("fuel_type") or "-",
            "color": lc.get("color") or "-",
            "cc": lc.get("cylinder_capacity") or "-",
            "expiry": lc.get("mot_expiry_date") or "N/A",
            "tax": (lc.get("tax_due_date") or "Unknown") + (f" ({lc.get('tax_status')})" if lc.get('tax_status') else ""),
            "days": days,
            "notes": v.get("notes") or "",
            "booked": booked
        }
        
        if is_exp or status == "Expired":
            expired.append(item)
        elif days is not None and days <= 30:
            expiring.append(item)
            
    # Sort expired by days (most overdue first)
    expired.sort(key=lambda x: x["days"] if x["days"] is not None else -999)
    # Sort expiring by days (closest expiry first)
    expiring.sort(key=lambda x: x["days"] if x["days"] is not None else 999)
    
    gen_time = datetime.now().strftime("%d %B %Y at %H:%M")
    
    def render_row(v, is_expired):
        badge_style = "background: #f87171; color: #7f1d1d;" if is_expired else "background: #fbbf24; color: #78350f;"
        booked_badge = '<span style="background: #2563eb; color: #ffffff; padding: 2px 7px; border-radius: 4px; font-size: 10px; font-weight: 700; margin-left: 6px; text-transform: uppercase;">BOOKED</span>' if v['booked'] else ''
        
        days_label = f"{abs(v['days'])}d overdue" if is_expired and v['days'] is not None else (f"{v['days']}d left" if v['days'] is not None else "Expired")
        
        return f"""
        <tr>
          <td style="white-space: nowrap;">
            <div style="background: #facc15; color: #111827; font-family: 'Consolas', 'Courier New', monospace; font-weight: 800; font-size: 13px; letter-spacing: 1.2px; padding: 4px 8px; border-radius: 4px; display: inline-block; border: 1px solid #ca8a04;">
              {v['vrn']}
            </div>
            {booked_badge}
          </td>
          <td>
            <div style="font-weight: 700; color: #0f172a; font-size: 13px;">{v['make']}</div>
            <div style="font-size: 11px; color: #64748b;">{v['year']} &bull; {v['fuel']} &bull; {v['cc']} &bull; {v['color']}</div>
          </td>
          <td style="white-space: nowrap;">
            <span style="{badge_style} font-weight: 700; font-size: 11px; padding: 3px 8px; border-radius: 4px; display: inline-block;">
              {days_label}
            </span>
          </td>
          <td style="font-size: 12px; font-weight: 600; color: #1e293b; white-space: nowrap;">
            {v['expiry']}
          </td>
          <td style="font-size: 11px; color: #475569; white-space: nowrap;">
            {v['tax']}
          </td>
          <td style="font-size: 11px; color: #334155; line-height: 1.4;">
            {v['notes']}
          </td>
        </tr>
        """

    expired_rows = "".join(render_row(v, True) for v in expired)
    expiring_rows = "".join(render_row(v, False) for v in expiring)

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>MOTPing Fleet Compliance Report</title>
  <style>
    @page {{
      size: A4 landscape;
      margin: 12mm 14mm 12mm 14mm;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      color: #0f172a;
      background: #ffffff;
      margin: 0;
      padding: 0;
      font-size: 12px;
      line-height: 1.4;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 2px solid #0f172a;
      padding-bottom: 12px;
      margin-bottom: 16px;
    }}
    .brand-title {{
      font-size: 24px;
      font-weight: 800;
      letter-spacing: -0.5px;
      color: #0f172a;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .brand-pill {{
      background: #facc15;
      color: #000;
      font-size: 11px;
      font-weight: 800;
      padding: 2px 8px;
      border-radius: 4px;
      letter-spacing: 0.5px;
    }}
    .meta-box {{
      text-align: right;
      font-size: 11px;
      color: #64748b;
    }}
    .summary-strip {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-bottom: 20px;
    }}
    .summary-card {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 10px 14px;
    }}
    .summary-label {{
      font-size: 10px;
      font-weight: 700;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .summary-val {{
      font-size: 20px;
      font-weight: 800;
      color: #0f172a;
      margin-top: 2px;
    }}
    .section-title {{
      font-size: 14px;
      font-weight: 700;
      color: #0f172a;
      margin: 18px 0 8px 0;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .badge-count {{
      font-size: 11px;
      padding: 2px 7px;
      border-radius: 10px;
      font-weight: 700;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 18px;
      font-size: 11.5px;
    }}
    th {{
      background: #f1f5f9;
      color: #334155;
      text-transform: uppercase;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.05em;
      padding: 8px 10px;
      border-bottom: 1px solid #cbd5e1;
      text-align: left;
    }}
    td {{
      padding: 8px 10px;
      border-bottom: 1px solid #e2e8f0;
      vertical-align: middle;
    }}
    tr:nth-child(even) td {{
      background: #fafafa;
    }}
    .footer {{
      margin-top: 14px;
      padding-top: 10px;
      border-top: 1px solid #e2e8f0;
      font-size: 10px;
      color: #94a3b8;
      display: flex;
      justify-content: space-between;
    }}
  </style>
</head>
<body>
  <div class="header">
    <div>
      <div class="brand-title">
        MOTPING <span class="brand-pill">FLEET COMPLIANCE</span>
      </div>
      <div style="font-size: 12px; color: #475569; margin-top: 2px;">
        Urgent Action Fleet Notice &bull; Expired &amp; Expiring Vehicle MOT Telemetry
      </div>
    </div>
    <div class="meta-box">
      <div><strong>Generated:</strong> {gen_time}</div>
      <div><strong>Total Fleet Scope:</strong> {len(vehicles)} vehicles tracked</div>
      <div><strong>Requiring Booking:</strong> {len(expired) + len(expiring)} vehicles</div>
    </div>
  </div>

  <div class="summary-strip">
    <div class="summary-card" style="border-left: 4px solid #0f172a;">
      <div class="summary-label">Total Monitored</div>
      <div class="summary-val">{len(vehicles)}</div>
    </div>
    <div class="summary-card" style="border-left: 4px solid #ef4444;">
      <div class="summary-label">Expired / Unlawful</div>
      <div class="summary-val" style="color: #dc2626;">{len(expired)}</div>
    </div>
    <div class="summary-card" style="border-left: 4px solid #f59e0b;">
      <div class="summary-label">Expiring (&le; 30 Days)</div>
      <div class="summary-val" style="color: #d97706;">{len(expiring)}</div>
    </div>
    <div class="summary-card" style="border-left: 4px solid #10b981;">
      <div class="summary-label">Valid / Legal</div>
      <div class="summary-val" style="color: #059669;">{len(vehicles) - len(expired) - len(expiring)}</div>
    </div>
  </div>

  <div class="section-title">
    <span style="color: #dc2626;">&#x25CF;</span> Expired MOT &bull; Action Required
    <span class="badge-count" style="background: #fee2e2; color: #991b1b;">{len(expired)} Vehicles</span>
  </div>
  <table>
    <thead>
      <tr>
        <th style="width: 110px;">Registration</th>
        <th style="width: 170px;">Vehicle Spec</th>
        <th style="width: 90px;">Status</th>
        <th style="width: 110px;">MOT Expiry</th>
        <th style="width: 120px;">Road Tax</th>
        <th>Driver / Yard Notes</th>
      </tr>
    </thead>
    <tbody>
      {expired_rows if expired_rows else '<tr><td colspan="6" style="text-align:center;color:#64748b;padding:12px;">Zero vehicles currently expired.</td></tr>'}
    </tbody>
  </table>

  <div class="section-title" style="page-break-before: auto;">
    <span style="color: #d97706;">&#x25CF;</span> Expiring Soon (&le; 30 Days) &bull; Urgent Booking Required
    <span class="badge-count" style="background: #fef3c7; color: #92400e;">{len(expiring)} Vehicles</span>
  </div>
  <table>
    <thead>
      <tr>
        <th style="width: 110px;">Registration</th>
        <th style="width: 170px;">Vehicle Spec</th>
        <th style="width: 90px;">Remaining</th>
        <th style="width: 110px;">MOT Expiry</th>
        <th style="width: 120px;">Road Tax</th>
        <th>Driver / Yard Notes</th>
      </tr>
    </thead>
    <tbody>
      {expiring_rows if expiring_rows else '<tr><td colspan="6" style="text-align:center;color:#64748b;padding:12px;">Zero vehicles expiring within 30 days.</td></tr>'}
    </tbody>
  </table>

  <div class="footer">
    <div>MOTPing Fleet Management &bull; Live DVLA Test &amp; Tax Telemetry</div>
    <div>Legal Notice: Driving without a valid MOT certificate carries a fine of up to &pound;1,000 unless driving to a pre-booked test.</div>
  </div>
</body>
</html>"""
    return html

def generate_pdf():
    if not os.path.exists(STATE_FILE):
        print(f"Error: {STATE_FILE} not found.")
        return False
        
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
        
    html_content = build_report_html(state)
    with open(REPORT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    edge_bin = find_edge()
    if not edge_bin:
        print("Microsoft Edge not found for headless PDF generation.")
        return False
        
    html_url = f"file:///{REPORT_HTML.replace(os.sep, '/')}"
    cmd = [
        edge_bin,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={LOCAL_PDF}",
        html_url
    ]
    
    print(f"Executing: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    
    if os.path.exists(LOCAL_PDF) and os.path.getsize(LOCAL_PDF) > 0:
        # Also copy to desktop for user convenience
        try:
            import shutil
            shutil.copy2(LOCAL_PDF, DESKTOP_PDF)
            print(f"Copied report to Desktop: {DESKTOP_PDF}")
        except Exception as e:
            print(f"Note: Could not copy to desktop: {e}")
        print(f"Generated PDF: {LOCAL_PDF} ({os.path.getsize(LOCAL_PDF)} bytes)")
        return True
    else:
        print(f"Failed to generate PDF. Edge stderr: {res.stderr}")
        return False

if __name__ == "__main__":
    success = generate_pdf()
    sys.exit(0 if success else 1)
