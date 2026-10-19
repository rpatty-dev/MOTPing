"""
MOTPing Alert Daemon & Automated Scheduled Monitor
Monitors all tracked license plates against DVLA/DVSA.
Dispatches Phone Push (ntfy), Email (SMTP), or both when MOT or Tax is due / expired.
"""

import os
import sys
import json
import time
import urllib.request
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from mot_engine import query_dvla_vehicle

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.toml")
CONFIG_EXAMPLE = os.path.join(BASE_DIR, "config.example.toml")
STATE_FILE = os.path.join(BASE_DIR, "mot_fleet_state.json")
LOG_FILE = os.path.join(BASE_DIR, "motping.log")

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{ts}] {msg}"
    print(formatted)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

def parse_simple_toml(path):
    config = {}
    current_section = config
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[[") and line.endswith("]]"):
                sec_name = line[2:-2].strip()
                if sec_name not in config:
                    config[sec_name] = []
                new_item = {}
                config[sec_name].append(new_item)
                current_section = new_item
                continue
            if line.startswith("[") and line.endswith("]"):
                sec_name = line[1:-1].strip()
                config[sec_name] = {}
                current_section = config[sec_name]
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip().strip('"').strip("'")
                v = v.split("#")[0].strip()
                if v.lower() == "true": val = True
                elif v.lower() == "false": val = False
                elif v.isdigit(): val = int(v)
                else:
                    try: val = float(v)
                    except ValueError: val = v.strip('"').strip("'")
                current_section[k] = val
    return config

def load_config():
    target = CONFIG_FILE if os.path.exists(CONFIG_FILE) else CONFIG_EXAMPLE
    if os.path.exists(target):
        return parse_simple_toml(target)
    return {
        "thresholds": {"warning_days": 30, "urgent_days": 14, "critical_days": 7},
        "notifications": {"email_enabled": True, "ntfy_enabled": True},
        "ntfy": {"topic": "my-fleet-mot-alerts", "server": "https://ntfy.sh"},
        "smtp": {"host": "smtp.example.com", "port": 587, "username": "", "password": "", "from_email": "alerts@example.com", "to_email": "admin@example.com"}
    }

CONFIG = load_config()

def send_ntfy_alert(title, message, priority="high", tags="car,warning"):
    ntfy_cfg = CONFIG.get("ntfy", {})
    topic = os.environ.get("MOTPING_NTFY_TOPIC", ntfy_cfg.get("topic", "my-fleet-mot-alerts"))
    server = os.environ.get("MOTPING_NTFY_SERVER", ntfy_cfg.get("server", "https://ntfy.sh")).rstrip("/")
    if not topic:
        return False
    url = f"{server}/{topic}"
    headers = {"Title": title, "Priority": priority, "Tags": tags}
    try:
        req = urllib.request.Request(url, data=message.encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        log(f"ntfy error: {e}")
        return False

def send_email_alert(subject, text_body, html_body):
    smtp_cfg = CONFIG.get("smtp", {})
    host = smtp_cfg.get("host", "smtp.example.com")
    port = int(smtp_cfg.get("port", 587))
    user = os.environ.get("MOTPING_SMTP_USER", smtp_cfg.get("username", ""))
    pwd = os.environ.get("MOTPING_SMTP_PASS", smtp_cfg.get("password", ""))
    recipient = smtp_cfg.get("to_email", "admin@example.com")
    sender = smtp_cfg.get("from_email", "MOTPing Alerts <alerts@example.com>")

    if not user or not pwd or pwd == "YOUR_SMTP_PASSWORD":
        return False

    msg = MIMEMultipart("alternative")
    msg['From'] = sender
    msg['To'] = recipient
    msg['Subject'] = subject
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        s = smtplib.SMTP(host, port, timeout=15)
        if smtp_cfg.get("use_tls", True):
            s.starttls()
        s.login(user, pwd)
        s.sendmail(user, [recipient], msg.as_string())
        s.quit()
        return True
    except Exception as e:
        log(f"SMTP error: {e}")
        return False

def dispatch_notification(title, message, html_body=None, priority="high", tags="car,warning"):
    notif_cfg = CONFIG.get("notifications", {})
    results = []
    if notif_cfg.get("ntfy_enabled", True):
        results.append(send_ntfy_alert(title, message, priority=priority, tags=tags))
    if notif_cfg.get("email_enabled", True):
        html = html_body if html_body else f"<h3>{title}</h3><pre>{message}</pre>"
        results.append(send_email_alert(title, message, html))
    return any(results) if results else False

def run_fleet_scan():
    log("Starting scheduled MOT & Tax scan across fleet...")
    if not os.path.exists(STATE_FILE):
        log("No fleet state found. Nothing to scan.")
        return

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    vehicles = state.get("vehicles", [])
    log(f"Found {len(vehicles)} vehicles in fleet database.")

    thresholds = CONFIG.get("thresholds", {"warning_days": 30, "urgent_days": 14, "critical_days": 7})
    warn_days = int(thresholds.get("warning_days", 30))

    alerts_triggered = []

    for v in vehicles:
        vrn = v["vrn"]
        log(f"Querying DVLA live telemetry for {vrn}...")
        info = query_dvla_vehicle(vrn)
        v["last_check"] = info
        time.sleep(1.0) # Graceful polling pause

        if not info.get("found"):
            log(f"Could not find vehicle details for {vrn}.")
            continue

        make = info.get("make") or "Vehicle"
        mot_exp = info.get("mot_expiry_date")
        days = info.get("days_until_mot")
        is_exp = info.get("is_mot_expired")

        if is_exp:
            title = f"CRITICAL: MOT EXPIRED - {vrn} ({make})"
            msg = f"Vehicle {vrn} ({make}) has an EXPIRED MOT as of {mot_exp}!\nDo not drive this vehicle until an MOT test is passed."
            log(f"TRIGGER: {vrn} MOT expired.")
            dispatch_notification(title, msg, priority="urgent", tags="rotating_light,car,x")
            alerts_triggered.append(f"{vrn} (EXPIRED: {mot_exp})")
        elif days is not None and days <= warn_days:
            urgency = "URGENT" if days <= 7 else "WARNING"
            title = f"[{urgency}] MOT Due in {days} Days - {vrn} ({make})"
            msg = f"Vehicle {vrn} ({make}) MOT expires on {mot_exp} ({days} days remaining).\nBook an MOT inspection test immediately."
            log(f"TRIGGER: {vrn} MOT due in {days} days.")
            priority = "urgent" if days <= 7 else "high"
            dispatch_notification(title, msg, priority=priority, tags="warning,car,calendar")
            alerts_triggered.append(f"{vrn} (Due in {days}d on {mot_exp})")

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    log(f"Fleet scan complete. Alerts dispatched: {len(alerts_triggered)}")

if __name__ == "__main__":
    run_fleet_scan()
