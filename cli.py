"""
MOTPing CLI - Instant Terminal MOT & Road Tax Inspector
"""

import sys
import os
import json

sys.stdout.reconfigure(encoding='utf-8')
from mot_engine import query_dvla_vehicle

def main():
    os.system("") # Enable ANSI console colors
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{CYAN}======================================================================{RESET}")
    print(f"{BOLD}  [MOT] MOTPing — Instant DVLA/DVSA MOT & Road Tax Telemetry{RESET}")
    print(f"{BOLD}{CYAN}======================================================================{RESET}\n")

    if len(sys.argv) < 2:
        print("Usage: python cli.py <LICENSE_PLATE>")
        print("Example: python cli.py P3RCV")
        print("         python cli.py \"FT24 VAN\"\n")
        sys.exit(0)

    vrn = " ".join(sys.argv[1:])
    print(f"Querying DVLA live telemetry for: {BOLD}{vrn.upper()}{RESET}...")
    data = query_dvla_vehicle(vrn)

    if not data.get("found"):
        print(f"\n{RED}Error: {data.get('error', 'Vehicle not found')}{RESET}\n")
        sys.exit(1)

    print(f"\n{BOLD}VEHICLE IDENTIFICATION:{RESET}")
    print(f"  - Registration:   {YELLOW}{BOLD}{data.get('vrn')}{RESET}")
    print(f"  - Make / Model:   {data.get('make', 'Unknown')} ({data.get('color', 'N/A')})")
    print(f"  - Year:           {data.get('year', 'N/A')}")
    print(f"  - Engine:         {data.get('cylinder_capacity', 'N/A')} ({data.get('fuel_type', 'N/A')})")
    print(f"  - CO2 Emissions:  {data.get('co2_emissions', 'N/A')}")

    print(f"\n{BOLD}MOT TEST TELEMETRY:{RESET}")
    mot_stat = data.get("mot_status")
    mot_exp = data.get("mot_expiry_date")
    days = data.get("days_until_mot")

    if data.get("is_mot_expired"):
        status_color = RED
        status_badge = "EXPIRED"
        note = f"{RED}CRITICAL: Vehicle does not have a valid MOT certificate! (Expired on {mot_exp}){RESET}"
    elif days is not None and days <= 30:
        status_color = YELLOW
        status_badge = f"WARNING ({days} DAYS REMAINING)"
        note = f"{YELLOW}Action Required: Book an MOT inspection test soon before {mot_exp}.{RESET}"
    else:
        status_color = GREEN
        status_badge = "VALID"
        note = f"{GREEN}MOT is in good standing until {mot_exp} ({days} days left).{RESET}"

    print(f"  - Status:         {status_color}{BOLD}{status_badge}{RESET}")
    print(f"  - Expiry Date:    {mot_exp or 'No record'}")
    print(f"  - Advisory:       {note}")

    print(f"\n{BOLD}ROAD TAX STATUS:{RESET}")
    tax_stat = data.get("tax_status")
    tax_due = data.get("tax_due_date")
    tax_color = GREEN if tax_stat == "Taxed" else RED
    print(f"  - Tax Status:     {tax_color}{BOLD}{tax_stat}{RESET}")
    print(f"  - Tax Due Date:   {tax_due or 'N/A'}")

    print(f"\n{CYAN}======================================================================{RESET}\n")

if __name__ == "__main__":
    main()
