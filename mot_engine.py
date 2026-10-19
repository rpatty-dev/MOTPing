"""
MOTPing - Core Scraper & DVLA / DVSA Telemetry Engine
Reversed from UK GOV.UK vehicle enquiry flow (RFC 3805 / web capture).
Zero third-party dependencies: Pure Python standard library (urllib, http.cookiejar, re).
"""

import urllib.request
import urllib.parse
import http.cookiejar
import re
from datetime import datetime

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def query_dvla_vehicle(vrn: str, timeout: float = 12.0) -> dict:
    """
    Performs 3-step CSRF-authenticated session flow against vehicleenquiry.service.gov.uk:
    1. GET / -> extract authenticity_token and session cookies
    2. POST /vehicle-enquiry/save?locale=en with VRN -> follow to /ConfirmVehicle?locale=en
    3. POST /vehicle-enquiry/save?locale=en with confirmed=Yes -> land on /VehicleFound?locale=en
    Returns parsed dictionary of MOT, Tax, and Vehicle specifications.
    """
    clean_vrn = re.sub(r'[^A-Za-z0-9]', '', vrn).upper()
    if not clean_vrn:
        return {"error": "Invalid VRN supplied"}

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-GB,en;q=0.9',
        'Origin': 'https://vehicleenquiry.service.gov.uk',
        'DNT': '1',
        'Upgrade-Insecure-Requests': '1',
    }

    try:
        # Step 1: GET Start page to acquire CSRF token & session cookies
        req1 = urllib.request.Request('https://vehicleenquiry.service.gov.uk/', headers=headers)
        with opener.open(req1, timeout=timeout) as resp1:
            html1 = resp1.read().decode('utf-8', errors='ignore')

        form1_list = [f for f in html1.split('<form') if 'wizard_vehicle_enquiry_capture_vrn' in f]
        if not form1_list:
            return {"error": "Failed to parse initial DVLA form"}
        
        t1_match = re.search(r'name="authenticity_token"\s+value="([^"]+)"', form1_list[0])
        if not t1_match:
            return {"error": "Failed to extract initial CSRF authenticity token"}
        token1 = t1_match.group(1)

        # Step 2: POST VRN to acquire confirmation form
        h2 = headers.copy()
        h2['Referer'] = 'https://vehicleenquiry.service.gov.uk/'
        h2['Content-Type'] = 'application/x-www-form-urlencoded'
        
        d1 = urllib.parse.urlencode({
            'authenticity_token': token1,
            'wizard_vehicle_enquiry_capture_vrn[vrn]': clean_vrn
        }).encode('utf-8')

        req2 = urllib.request.Request(
            'https://vehicleenquiry.service.gov.uk/vehicle-enquiry/save?locale=en',
            data=d1,
            headers=h2
        )
        with opener.open(req2, timeout=timeout) as resp2:
            html2 = resp2.read().decode('utf-8', errors='ignore')

        if "Vehicle not found" in html2 or "Check the registration is correct" in html2:
            return {
                "vrn": clean_vrn,
                "found": False,
                "error": "Vehicle registration not found on DVLA record"
            }

        form2_list = [f for f in html2.split('<form') if 'wizard_vehicle_enquiry_capture_confirm_vehicle' in f]
        if not form2_list:
            return {
                "vrn": clean_vrn,
                "found": False,
                "error": "Confirmation step missing from DVLA response"
            }

        t2_match = re.search(r'name="authenticity_token"\s+value="([^"]+)"', form2_list[0])
        action2_match = re.search(r'action="([^"]+)"', form2_list[0])
        token2 = t2_match.group(1) if t2_match else ""
        action2 = action2_match.group(1) if action2_match else "/vehicle-enquiry/save?locale=en"
        target_url = 'https://vehicleenquiry.service.gov.uk' + action2 if action2.startswith('/') else action2

        # Step 3: POST Confirm vehicle = Yes to land on /VehicleFound
        h3 = headers.copy()
        h3['Referer'] = resp2.geturl()
        h3['Content-Type'] = 'application/x-www-form-urlencoded'

        d2 = urllib.parse.urlencode({
            'authenticity_token': token2,
            'wizard_vehicle_enquiry_capture_confirm_vehicle[confirmed]': 'Yes'
        }).encode('utf-8')

        req3 = urllib.request.Request(target_url, data=d2, headers=h3)
        with opener.open(req3, timeout=timeout) as resp3:
            html3 = resp3.read().decode('utf-8', errors='ignore')

        return parse_dvla_response(clean_vrn, html3)

    except Exception as e:
        return {
            "vrn": clean_vrn,
            "found": False,
            "error": f"Network or scraping error: {str(e)}"
        }

def parse_dvla_response(vrn: str, html: str) -> dict:
    """Parses MOT status, expiry date, tax due date, and full vehicle specifications."""
    data = {
        "vrn": vrn,
        "found": True,
        "scraped_at": datetime.now().isoformat(),
        "make": None,
        "year": None,
        "fuel_type": None,
        "color": None,
        "cylinder_capacity": None,
        "co2_emissions": None,
        "tax_status": "Unknown",
        "tax_due_date": None,
        "mot_status": "Unknown",
        "mot_expiry_date": None,
        "days_until_mot": None,
        "is_mot_expired": False,
        "attributes": {}
    }

    # Extract all Summary Rows (<dt> / <dd>)
    rows = re.findall(r'<div class="govuk-summary-list__row"[^>]*>\s*<dt>(.*?)</dt>\s*<dd>(.*?)</dd>', html, re.DOTALL)
    for raw_k, raw_v in rows:
        k = re.sub(r'<[^>]+>', '', raw_k).strip()
        v = re.sub(r'<[^>]+>', '', raw_v).strip()
        if k and v:
            data["attributes"][k] = v

    data["make"] = data["attributes"].get("Vehicle make")
    data["year"] = data["attributes"].get("Year of manufacture")
    data["fuel_type"] = data["attributes"].get("Fuel type")
    data["color"] = data["attributes"].get("Vehicle colour")
    data["cylinder_capacity"] = data["attributes"].get("Cylinder capacity")
    data["co2_emissions"] = data["attributes"].get("CO₂ emissions")

    # Tax Status & Due Date
    tax_status_m = re.search(r'Vehicle [A-Z0-9\s]+ is (Taxed|Untaxed|SORN)', html, re.IGNORECASE)
    if tax_status_m:
        data["tax_status"] = tax_status_m.group(1).capitalize()
    elif "Taxed" in html:
        data["tax_status"] = "Taxed"

    tax_due_m = re.search(r'Tax due:\s*(?:<[^>]+>\s*)*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})', html)
    if tax_due_m:
        data["tax_due_date"] = tax_due_m.group(1)

    # MOT Status & Expiry Date
    if "does not have a valid MOT certificate" in html or "No MOT" in html:
        data["mot_status"] = "Expired"
        data["is_mot_expired"] = True
    elif "MOT valid" in html or "Valid until" in html or "Expires" in html:
        data["mot_status"] = "Valid"
        data["is_mot_expired"] = False

    mot_exp_m = re.search(r'(?:Expired|Expires|Valid until):\s*(?:<[^>]+>\s*)*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})', html)
    if mot_exp_m:
        data["mot_expiry_date"] = mot_exp_m.group(1)
        try:
            exp_dt = datetime.strptime(data["mot_expiry_date"], "%d %B %Y")
            diff = (exp_dt.date() - datetime.now().date()).days
            data["days_until_mot"] = diff
            data["is_mot_expired"] = diff < 0
            if diff < 0:
                data["mot_status"] = "Expired"
        except Exception:
            pass

    return data
