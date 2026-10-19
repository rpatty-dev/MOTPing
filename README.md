<div align="center">

<img src="logo.svg" alt="MOTPing Logo" width="460" />

<p align="center">
  <strong>Zero-dependency, pure-Python DVLA/DVSA vehicle MOT & road tax monitoring engine, REST API, and reminder sentinel.</strong>
</p>

<p align="center">
  <a href="#features">Features</a> &bull;
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#rest-api">REST API</a> &bull;
  <a href="#cli-usage">CLI Usage</a> &bull;
  <a href="#automated-alerts">Automated Alerts</a> &bull;
  <a href="#license">License</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-3776ab.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.8+" />
  <img src="https://img.shields.io/badge/Dependencies-Zero%20(Pure%20Stdlib)-success.svg?style=flat-square" alt="Zero Dependencies" />
  <img src="https://img.shields.io/badge/Source-DVLA%20%2F%20GOV.UK%20Direct-blue.svg?style=flat-square" alt="DVLA Direct" />
  <img src="https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square" alt="MIT License" />
</p>

</div>

---

## ⚡ What is MOTPing?

**MOTPing** is an open-source, zero-dependency vehicle compliance monitor reversed engineered directly from the official UK Driver and Vehicle Licensing Agency (DVLA / GOV.UK) vehicle enquiry portal.

It allows fleet operators, independent workshops, garages, and private vehicle owners to track an unlimited number of UK license plates, querying live MOT expiration dates, test statuses, and road tax due dates with zero third-party API costs or scraping services.

### Key Capabilities

- **Zero Third-Party Dependencies**: Built exclusively with Python standard libraries (`urllib`, `http.cookiejar`, `re`, `http.server`). No Selenium, no Playwright, no Chromium downloads.
- **Direct DVLA/DVSA CSRF Flow**: Implements an automated, multi-step cookiejar session engine to fetch official vehicle records directly.
- **Full REST API**: Micro-service endpoints to query any vehicle on demand or maintain a persistent fleet watch list.
- **Responsive Web Dashboard**: Clean dark-mode operations console for fleet managers and workshops.
- **Multi-Channel Reminders**: Automated background daemon that triggers phone push notifications via [ntfy.sh](https://ntfy.sh), SMTP email alerts, or both as vehicles approach 30-day, 14-day, or critical 7-day deadlines.
- **Instant CLI Utility**: Colorized terminal command to check any plate in milliseconds.

---

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/rpatty-dev/MOTPing.git
cd MOTPing
```

### 2. Instant Terminal Check

Check any UK vehicle registration immediately:

```bash
python cli.py "P3 RCV"
```

Output:

```text
======================================================================
  [MOT] MOTPing — Instant DVLA/DVSA MOT & Road Tax Telemetry
======================================================================

Querying DVLA live telemetry for: P3 RCV...

VEHICLE IDENTIFICATION:
  - Registration:   P3RCV
  - Make / Model:   MERCEDES-BENZ (SILVER)
  - Year:           2014
  - Engine:         2143 cc (DIESEL)
  - CO2 Emissions:  131 g/km

MOT TEST TELEMETRY:
  - Status:         EXPIRED
  - Expiry Date:    14 August 2026
  - Advisory:       CRITICAL: Vehicle does not have a valid MOT certificate! (Expired on 14 August 2026)

ROAD TAX STATUS:
  - Tax Status:     Taxed
  - Tax Due Date:   1 January 2027
======================================================================
```

### 3. Launch Web Dashboard & REST API

```bash
python server.py 8080
```

Open your browser at **`http://localhost:8080`**.

---

## 🌐 REST API Endpoints

### 1. Query Single Vehicle Live Telemetry

```http
GET /api/check?vrn=P3RCV
```

Response (`200 OK`):

```json
{
  "vrn": "P3RCV",
  "found": true,
  "scraped_at": "2026-10-19T09:46:59",
  "make": "MERCEDES-BENZ",
  "year": "2014",
  "fuel_type": "DIESEL",
  "color": "SILVER",
  "cylinder_capacity": "2143 cc",
  "co2_emissions": "131 g/km",
  "tax_status": "Taxed",
  "tax_due_date": "1 January 2027",
  "mot_status": "Expired",
  "mot_expiry_date": "14 August 2026",
  "days_until_mot": -66,
  "is_mot_expired": true
}
```

### 2. Get Monitored Fleet List

```http
GET /api/fleet
```

### 3. Add Vehicle to Fleet Watchlist

```http
POST /api/vehicles
Content-Type: application/json

{
  "vrn": "FT24 VAN",
  "notes": "Service Van #1 - Alex Miller"
}
```

### 4. Remove Vehicle from Watchlist

```http
DELETE /api/vehicles?vrn=FT24VAN
```

---

## 📱 Automated Reminder Alerts (ntfy & Email)

Copy the configuration template:

```bash
cp config.example.toml config.toml
```

Configure your thresholds and phone/email targets:

```toml
[thresholds]
warning_days = 30
urgent_days = 14
critical_days = 7

[notifications]
email_enabled = true
ntfy_enabled = true

[ntfy]
topic = "my-fleet-mot-alerts"
```

Run the automated scan:

```bash
python mot_monitor.py
```

#### Schedule Hourly or Daily via Cron:
```bash
0 8 * * * cd /opt/MOTPing && python3 mot_monitor.py >> /var/log/motping.log 2>&1
```

---

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.
