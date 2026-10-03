"""Generate invented sample data for Sample Co., period 2026-09.

Every vendor, person, project, customer and amount here is made up. Seeded vendors use exact,
hand-checkable amounts so each accounting rule is exercised (see SEEDED CASES below); the rest are
filler vendors generated from a fixed random seed.

Run:  python scripts/make_sample_data.py [--out data/sample]
"""
from __future__ import annotations

import argparse
import calendar
import csv
import json
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SEED = 20260930
YEAR = 2026
PERIOD = "2026-09"
OWNERS = ["Dana Whitlock", "Priya Ostrander", "Marcus Feld", "Lena Okafor", "Tomas Reyhill"]

ACCOUNTS = {
    13100: "Prepaid Expenses", 13101: "Prepaid Software", 16000: "CIP - Buildouts",
    16005: "Capex Accrual Clearing", 16010: "Furniture & Equipment", 20500: "Accrued Expenses",
    60100: "Professional Services", 60200: "Consulting Fees", 60510: "Sales Commissions",
    60520: "Partner Commissions", 61100: "Software Subscriptions", 61200: "Cloud Hosting", 61300: "Telecom",
    61500: "Legal Fees", 61600: "Legal - Litigation", 62100: "Facilities Services", 62200: "Utilities",
    62300: "Rent & Parking", 63100: "Insurance", 63200: "Recruiting", 63300: "Benefits Administration",
    64100: "Marketing Services", 64200: "Events", 64300: "Printing", 65100: "Travel", 65200: "Office Supplies",
    65300: "Training", 66100: "Depreciation", 70100: "Interest Expense",
}
DEPTS = {"D100": "Finance", "D200": "Engineering", "D300": "Sales", "D400": "Marketing", "D500": "Operations",
         "D600": "People", "D700": "Facilities"}
LOCATIONS = {"L10": "Main Office", "L20": "West Campus", "L30": "Remote", "L40": "Harbor Street Studio"}
ITEMS = {"I-SVC": "Services", "I-SW": "Software", "I-FAC": "Facilities", "I-LEGAL": "Legal Services",
         "I-CAPEX": "Capital Project", "I-MKT": "Marketing", "I-INS": "Insurance", "I-TRV": "Travel"}
PROJECTS = {"P-1001": "Harbor Street Fit-Out", "P-1002": "West Campus Lab Expansion",
            "P-1003": "Main Office Phone Booths", "P-L01": "Matter - Halcyon Ridge contract dispute",
            "P-L02": "Matter - Ferngate lease review"}
CUSTOMERS = {"C-INT": "Internal", "C-201": "Halcyon Ridge Partners", "C-202": "Ferngate Holdings"}

# vendor_id: (name, dept, location, item)
VENDORS = {
    "V1001": ("Northwind Consulting", "D100", "L10", "I-SVC"),
    "V1002": ("Blue Harbor Insurance", "D100", "L10", "I-INS"),
    "V1003": ("Copperwren Facilities", "D700", "L10", "I-FAC"),
    "V1004": ("Meadowlark Staffing", "D500", "L10", "I-SVC"),
    "V1005": ("Tallreed Cloud Hosting", "D200", "L30", "I-SW"),
    "V1006": ("Ironfern Security Services", "D700", "L20", "I-FAC"),
    "V1007": ("Quillfeather Translation", "D400", "L30", "I-SVC"),
    "V1008": ("Saltmarsh Logistics", "D500", "L20", "I-SVC"),
    "V1009": ("Brambleway Office Supply", "D500", "L10", "I-SVC"),
    "V1010": ("Lanternfish Data Labs", "D200", "L30", "I-SW"),
    "V1011": ("Junebrook Utilities", "D700", "L10", "I-FAC"),
    "V1012": ("Foxglove Marketing Studio", "D400", "L10", "I-MKT"),
    "V1013": ("Pebblecreek Janitorial", "D700", "L10", "I-FAC"),
    "V1014": ("Cinderwick Telecom", "D200", "L10", "I-SVC"),
    "V1015": ("Mossgate Software Licensing", "D200", "L30", "I-SW"),
    "V1016": ("Driftwood Travel Desk", "D300", "L10", "I-TRV"),
    "V1017": ("Thistlewick Benefits Admin", "D600", "L10", "I-SVC"),
    "V1018": ("Larkspur Recruiting", "D600", "L10", "I-SVC"),
    "V1019": ("Cobaltbay Printing", "D400", "L10", "I-MKT"),
    "V1020": ("Wrenfield Payroll Services", "D600", "L10", "I-SVC"),
    "V1021": ("Orchard Lane Catering", "D600", "L10", "I-SVC"),
    "V1022": ("Starfinch Analytics", "D400", "L30", "I-MKT"),
    "V1023": ("Hollowpine Equipment Rental", "D700", "L20", "I-FAC"),
    "V1024": ("Kettlebrook Engineering", "D200", "L20", "I-SVC"),
    "V1025": ("Silverfen Training Co", "D600", "L30", "I-SVC"),
    "V1026": ("Amberfield Research Panel", "", "", "I-SVC"),
    "V1027": ("Granite Hollow Property Mgmt", "D700", "L20", "I-FAC"),
    "V1028": ("Ravenquill Courier", "D500", "L10", "I-SVC"),
    "V1029": ("Bellwort Wellness Programs", "D600", "L10", "I-SVC"),
    "V1030": ("Fernmoss Event Services", "D400", "L10", "I-MKT"),
    "V1031": ("Marigold Lane Design", "D400", "L10", "I-MKT"),
    "V1032": ("Oakmere Audit Advisory", "D100", "L10", "I-SVC"),
    "V1033": ("Sunpeg Parking Services", "D700", "L10", "I-FAC"),
    "V1034": ("Tidepool Recycling", "D700", "L20", "I-FAC"),
    "V1035": ("Willowmere Coffee Service", "D700", "L10", "I-SVC"),
    "V1036": ("Rivetstone HVAC", "D700", "L20", "I-FAC"),
    "V1037": ("Mistberry Survey Tools", "D400", "L30", "I-MKT"),
    "V1038": ("Hearthvault Records Storage", "D100", "L20", "I-FAC"),
    "V1039": ("Kestrel Point Lending", "D100", "L10", "I-SVC"),
    "V1040": ("Pinwheel Shuttle Co", "D500", "L10", "I-SVC"),
    "V1041": ("Brightlark Referral Partners", "D300", "L10", "I-SVC"),
    "V1042": ("Gildenrow Software", "D200", "L30", "I-SW"),
    "V1043": ("Corvid Lane Data", "D200", "L30", "I-SW"),
    "V1044": ("Sablewing Couriers", "D500", "L20", "I-SVC"),
    "V1045": ("Duskmeadow Print Lab", "D400", "L10", "I-MKT"),
    "V1046": ("Hazelnook Staffing", "D500", "L20", "I-SVC"),
    "V1047": ("Kestrelmoor Consulting", "D100", "L10", "I-SVC"),
    "V2001": ("Ashgrove & Pell LLP", "D100", "L10", "I-LEGAL"),
    "V2002": ("Brindle Hart Legal", "D100", "L10", "I-LEGAL"),
    "V2003": ("Quarrington Vale LLP", "D100", "L10", "I-LEGAL"),
    "V3001": ("Quarrystep Builders", "D700", "L40", "I-CAPEX"),
    "V3002": ("Lumenvale Electrical", "D700", "L20", "I-CAPEX"),
    "V3003": ("Oakthread Millwork", "D700", "L20", "I-CAPEX"),
    "V9001": ("Corporate Card Program", "D100", "L10", "I-TRV"),
}

GL: list[dict] = []
_doc = [0]


def mend(m: int, y: int = YEAR) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def nxt(m: int, day: int, y: int = YEAR) -> date:
    """A day in the month after (y, m)."""
    return date(y + 1, 1, day) if m == 12 else date(y, m + 1, day)


def money(x) -> str:
    return f"{Decimal(str(x)).quantize(Decimal('0.01'))}"


def bill(vid, acct, amount, posted: date, svc_from=None, svc_to=None, memo="", journal="APJ", doc=None,
         blank_dims=False, vendor_override=None):
    _doc[0] += 1
    name, dept, loc, _ = VENDORS.get(vid, ("", "", "", "")) if vid else ("", "", "", "")
    GL.append({
        "entry_date": posted.isoformat(), "gl_account": acct, "gl_account_name": ACCOUNTS[acct],
        "vendor_id": vid if vendor_override is None else vendor_override, "vendor_name": name,
        "department_name": "" if blank_dims else DEPTS.get(dept, ""),
        "location_name": "" if blank_dims else LOCATIONS.get(loc, ""),
        "signed_amount": money(amount), "gl_journal_id": journal, "journal_posting_date": posted.isoformat(),
        "service_period_from": svc_from.isoformat() if svc_from else "",
        "service_period_to": svc_to.isoformat() if svc_to else "",
        "service_month": "", "service_date_source": "",
        "description": memo or f"{name} invoice".strip(), "document_id": doc or f"INV-{_doc[0]:05d}",
    })


def monthly(vid, acct, amount, months, post="next", day=5, field=True, memo=None):
    """One bill per service month. post='same' posts on `day` of the service month, 'next' the month after."""
    for m in months:
        amt = amount(m) if callable(amount) else amount
        posted = date(YEAR, m, day) if post == "same" else nxt(m, day)
        bill(vid, acct, amt, posted, date(YEAR, m, 1) if field else None, mend(m) if field else None,
             memo=(memo(m) if callable(memo) else memo) or "")


MON = calendar.month_abbr


# ---------------------------------------------------------------------------------------------
# SEEDED CASES (amounts are exact so tests can check them by hand)
# ---------------------------------------------------------------------------------------------
ROSTER: list[dict] = []
BUDGET: list[dict] = []
JE_DIMS: list[dict] = []


def roster(vid, acct, vtype, owner, spread=None, liability=0):
    ROSTER.append({"vendor_name": VENDORS[vid][0], "vendor_id": vid, "gl_account": acct,
                   "gl_account_name": ACCOUNTS[acct], "vendor_type": vtype, "budget_ytd_spread": spread,
                   "gl_actual_ytd": 0, "liability_prior_year_remaining": money(liability), "owner": owner})


def budget(vid, acct, annual, phasing=None):
    annual = Decimal(str(annual))
    if phasing is None:
        each = (annual / 12).quantize(Decimal("0.01"))
        months = [each] * 11 + [annual - each * 11]
    else:
        months = [Decimal(str(x)) for x in phasing]
    BUDGET.append({"vendor_id": vid, "vendor_name": VENDORS[vid][0] if vid else "", "gl_account": acct,
                   "gl_account_name": ACCOUNTS[acct], "months": months, "annual": annual})


def dims(vid, acct, source="prior_je", item=None):
    _, dept, loc, it = VENDORS[vid]
    JE_DIMS.append({"vendor_id": vid, "gl_account": acct, "dept": dept, "location": loc, "item": item or it,
                    "source": source})


def seeded():
    # 1. Annual vs YTD regression: annual 180,000, 9 months, spend 144,000 -> YTD 135,000, accrual 0, over 9,000
    roster("V1001", 60200, "Consulting", "Dana Whitlock"); budget("V1001", 60200, 180000); dims("V1001", 60200)
    monthly("V1001", 60200, 16000, range(1, 10), post="same", day=25)

    # 2. Two roster lines, one vendor: spend matched on vendor AND account; prepaid ignored (2 lines)
    roster("V1015", 61100, "Software", "Marcus Feld"); budget("V1015", 61100, 60000); dims("V1015", 61100)
    roster("V1015", 65300, "Training", "Marcus Feld"); budget("V1015", 65300, 12000); dims("V1015", 65300)
    monthly("V1015", 61100, 5000, range(1, 9), post="same", day=20)
    monthly("V1015", 65300, 3000, [3, 6], post="same", day=20)
    bill("V1015", 13101, 24000, date(2026, 2, 3), date(2026, 2, 1), date(2027, 1, 31), "Annual license renewal")

    # 3. Prepaid across year-end: 36,500 for 7/1/26-6/30/27 -> 184/365 current = 18,400.00, next 18,100.00
    roster("V1002", 63100, "Insurance", "Dana Whitlock"); budget("V1002", 63100, 40000); dims("V1002", 63100)
    monthly("V1002", 63100, 1000, range(1, 10), post="next", day=6, memo=lambda m: "Broker fee")
    bill("V1002", 13100, 36500, date(2026, 7, 3), date(2026, 7, 1), date(2027, 6, 30), "D&O policy 2026-27")

    # 4. Account rollup: Tallreed 61100 -> 61200 (spend and budget)
    roster("V1005", 61200, "Hosting", "Marcus Feld"); budget("V1005", 61200, 96000); budget("V1005", 61100, 6000)
    dims("V1005", 61200, source="latest_bill")
    monthly("V1005", 61200, 7000, range(1, 10), post="next", day=6)
    monthly("V1005", 61100, 1000, range(1, 10), post="next", day=6)

    # 5. Vendor rollup: Mistberry|64100 rolls into Starfinch|64100 (spend and budget)
    roster("V1022", 64100, "Marketing", "Priya Ostrander"); budget("V1022", 64100, 48000); budget("V1037", 64100, 12000)
    dims("V1022", 64100)
    monthly("V1022", 64100, 4000, range(1, 10), post="next", day=8)
    monthly("V1037", 64100, 500, range(1, 10), post="same", day=15)

    # 6. Service rule: Junebrook's August bill posts 9/5 with no dates -> forced to 2026-08
    roster("V1011", 62200, "Utilities", "Lena Okafor"); budget("V1011", 62200, 36000); dims("V1011", 62200)
    monthly("V1011", 62200, 3000, range(1, 8), post="next", day=5)
    bill("V1011", 62200, 3000, date(2026, 9, 5), memo="Utility charges")
    bill("V1011", 62200, 3000, date(2026, 10, 5), memo="Utility charges")  # after cutoff

    # 7. Service-month priority: field / memo / posting month
    roster("V1007", 60100, "Professional services", "Priya Ostrander"); budget("V1007", 60100, 18000)
    dims("V1007", 60100)
    bill("V1007", 60100, 1200, date(2026, 2, 2), date(2026, 1, 1), date(2026, 1, 31), "Translation - field dates")
    bill("V1007", 60100, 1500, date(2026, 4, 7), memo="Translation services - March 2026")
    bill("V1007", 60100, 1800, date(2026, 6, 12), memo="Translation services")
    bill("V1007", 60100, 900, date(2026, 8, 3), memo="Inv 07/2026 localization")

    # 8. Prior-year liability from config: opening 25,000 - 18,000 prior-year bills = 7,000
    roster("V1027", 62300, "Rent", "Lena Okafor", liability=25000); budget("V1027", 62300, 120000)
    dims("V1027", 62300)
    bill("V1027", 62300, 10000, date(2026, 1, 8), date(2025, 11, 1), date(2025, 11, 30), "Nov 2025 CAM true-up")
    bill("V1027", 62300, 8000, date(2026, 2, 6), date(2025, 12, 1), date(2025, 12, 31), "Dec 2025 CAM true-up")
    monthly("V1027", 62300, 10000, range(1, 10), post="next", day=3)

    # 9. Prior-year liability from the roster (no config opening): roster 4,000
    roster("V1032", 60100, "Audit", "Dana Whitlock", liability=4000); budget("V1032", 60100, 60000)
    dims("V1032", 60100)
    bill("V1032", 60100, 12000, date(2026, 2, 10), memo="FY2025 audit fieldwork - Dec 2025")
    bill("V1032", 60100, 30000, date(2026, 8, 12), date(2026, 7, 1), date(2026, 7, 31), "Interim audit")

    # 10. No prior-year liability: prior-year bill ignored (excluded column only)
    roster("V1029", 63300, "Benefits", "Tomas Reyhill"); budget("V1029", 63300, 24000); dims("V1029", 63300)
    bill("V1029", 63300, 5000, date(2026, 1, 9), date(2025, 12, 1), date(2025, 12, 31), "Dec 2025 program")
    monthly("V1029", 63300, 2000, range(1, 10), post="same", day=27)

    # 11. Accrual rule: forced to $0 ("Received monthly via receipts"), formula still shown
    roster("V1035", 65200, "Office", "Tomas Reyhill"); budget("V1035", 65200, 14400); dims("V1035", 65200)
    for m in range(1, 9):
        bill("V1035", 65200, 1100, mend(m), memo="Coffee service receipt", journal="UNB")

    # 12. Removed roster line (Cobaltbay) - booked last month, not rebooked
    roster("V1019", 64300, "Printing", "Priya Ostrander"); budget("V1019", 64300, 30000); dims("V1019", 64300)
    monthly("V1019", 64300, 2500, range(1, 8), post="next", day=9)

    # 13. Dept split + removed GL document
    roster("V1003", 62100, "Facilities", "Lena Okafor"); budget("V1003", 62100, 120000); dims("V1003", 62100)
    monthly("V1003", 62100, lambda m: 9999.99 if m <= 2 else 10000, range(1, 9), post="next", day=4)
    bill("V1003", 62100, 10000, date(2026, 9, 18), date(2026, 8, 1), date(2026, 8, 31), "Duplicate of Aug",
         doc="INV-CW-0099")

    # 14. Budget override (Hollowpine) and excluded budget line (Marigold -> roster spread)
    roster("V1023", 62100, "Equipment", "Lena Okafor"); budget("V1023", 62100, 30000); dims("V1023", 62100)
    monthly("V1023", 62100, 3500, range(1, 9), post="next", day=6)
    roster("V1031", 64100, "Design", "Priya Ostrander", spread=7500); budget("V1031", 64100, 24000)
    dims("V1031", 64100)
    monthly("V1031", 64100, 2000, [2, 5, 8], post="next", day=11)

    # 15-26. Standing rules (baseline 2026-08, active from 2026-09)
    roster("V1014", 61300, "Telecom", "Marcus Feld"); budget("V1014", 61300, 48000); dims("V1014", 61300)
    bill("V1014", 61300, 30000, date(2026, 1, 15), date(2026, 1, 1), date(2026, 12, 31), "Annual telecom contract")
    bill("V1014", 61300, 450, date(2026, 9, 10), date(2026, 9, 1), date(2026, 9, 30), "Overage charges")

    roster("V1016", 65100, "Travel", "Tomas Reyhill"); budget("V1016", 65100, 24000); dims("V1016", 65100)
    for m in range(1, 9):
        bill("V1016", 65100, 2000, mend(m), memo=f"Travel desk receipts {MON[m]} 2026", journal="UNB")

    roster("V1030", 64200, "Events", "Priya Ostrander"); budget("V1030", 64200, 36000); dims("V1030", 64200)
    monthly("V1030", 64200, 4500, [2, 3], post="next", day=12)

    roster("V1036", 62100, "HVAC", "Lena Okafor"); budget("V1036", 62100, 36000); dims("V1036", 62100)
    bill("V1036", 62100, 27000, date(2026, 2, 5), date(2026, 2, 1), date(2026, 10, 31), "Service contract Feb-Oct")

    roster("V1013", 62100, "Janitorial", "Lena Okafor"); budget("V1013", 62100, 45600); dims("V1013", 62100)
    monthly("V1013", 62100, 3800, range(1, 8), post="next", day=3)
    bill("V1013", 62100, 3800, date(2026, 10, 2), date(2026, 8, 1), date(2026, 8, 31), "August janitorial")

    roster("V1033", 62300, "Parking", "Lena Okafor"); budget("V1033", 62300, 24000); dims("V1033", 62300)
    monthly("V1033", 62300, 2000, range(1, 8), post="same", day=20)
    bill("V1033", 62300, 1000, date(2026, 8, 20), date(2026, 8, 1), date(2026, 8, 15), "Parking 8/1-8/15")

    roster("V1038", 62100, "Storage", "Dana Whitlock"); budget("V1038", 62100, 9000); dims("V1038", 62100)

    roster("V1028", 65200, "Courier", "Tomas Reyhill"); budget("V1028", 65200, 12000); dims("V1028", 65200)
    monthly("V1028", 65200, 1500, range(1, 9), post="next", day=5)
    bill("V1028", 65200, 400, date(2026, 9, 28), date(2026, 9, 1), date(2026, 9, 15), "Courier 9/1-9/15")

    roster("V1021", 64200, "Catering", "Tomas Reyhill"); budget("V1021", 64200, 30000); dims("V1021", 64200)
    monthly("V1021", 64200, 2100, range(1, 10), post="same", day=22)

    roster("V1018", 63200, "Recruiting", "Tomas Reyhill"); budget("V1018", 63200, 72000); dims("V1018", 63200)
    monthly("V1018", 63200, 6000, range(1, 9), post="next", day=10)

    roster("V1004", 60100, "Staffing", "Marcus Feld"); budget("V1004", 60100, 240000); dims("V1004", 60100)
    monthly("V1004", 60100, 17000, range(1, 10), post="next", day=7)

    roster("V1012", 64100, "Marketing", "Priya Ostrander"); budget("V1012", 64100, 60000); dims("V1012", 64100)
    monthly("V1012", 64100, 5000, range(1, 10), post="same", day=18)
    bill("V1012", 64100, 25000, date(2026, 8, 25), date(2026, 8, 1), date(2026, 8, 31), "Fall campaign launch")

    # Generic paid-through rule removing a formula accrual >= 10K
    roster("V1010", 61100, "Software", "Marcus Feld"); budget("V1010", 61100, 300000); dims("V1010", 61100)
    monthly("V1010", 61100, 20000, range(1, 10), post="same", day=20)

    # Carried manual add (not on the roster) with a new bill this month
    bill("V1040", 65100, 5400, date(2026, 9, 15), date(2026, 7, 1), date(2026, 9, 30), "Shuttle Q3")

    # Billed for service after the cutoff (included in spend)
    roster("V1025", 65300, "Training", "")  # blank owner -> WIP
    budget("V1025", 65300, 24000); dims("V1025", 65300)
    monthly("V1025", 65300, 2000, range(1, 9), post="same", day=24)
    bill("V1025", 65300, 4000, date(2026, 9, 22), date(2026, 10, 1), date(2026, 10, 31), "October cohort")

    # Missing JE dimensions (no je_dims row, bills have no dept/location)
    roster("V1026", 60100, "Research", "Priya Ostrander"); budget("V1026", 60100, 30000)
    for m in (2, 5, 8):
        bill("V1026", 60100, 5000, nxt(m, 14), date(YEAR, m, 1), mend(m), "Research panel", blank_dims=True)

    # Scope exclusions
    bill("V1001", 60200, -2000, date(2026, 6, 30), memo="Reclass to 60100", journal="GJ")
    bill("V1001", 60100, 2000, date(2026, 6, 30), memo="Reclass from 60200", journal="GJ")
    for m in range(1, 10):
        bill("V9001", 65100, 850 + m * 10, mend(m), memo="Corporate card statement", journal="CCJ")
    bill("", 62100, 1250, date(2026, 5, 14), memo="Freight - unassigned", vendor_override="")
    bill("", 65200, 310, date(2026, 8, 19), memo="Misc supplies - no vendor", vendor_override="")
    for m in range(1, 10):
        bill("V1039", 70100, 4200, nxt(m, 1) if m < 9 else date(2026, 9, 30), memo="Loan interest")
    for m in (3, 6, 9):
        bill("V1041", 60520, 7500, date(2026, m, 28), memo="Partner referral commission")
    for vid, amt in (("V2001", 38000), ("V2002", 15500), ("V2003", 9000)):
        for m in range(1, 9):
            bill(vid, 61500, amt / 4, nxt(m, 15), date(YEAR, m, 1), mend(m), "Legal services")
    # capex bills (in scope as capex, not on the roster)
    bill("V3001", 16000, 100000, date(2026, 8, 20), memo="Harbor Street framing progress billing")
    bill("V3002", 16000, 80000, date(2026, 8, 22), memo="West Campus power progress billing")


def generic(rng: random.Random):
    """Filler vendors: bill monthly in arrears (Sep service posts in Oct, after the cutoff)."""
    filler = [
        ("V1006", 62100, 5200), ("V1008", 60100, 3100), ("V1009", 65200, 900), ("V1017", 63300, 2600),
        ("V1020", 63300, 4100), ("V1024", 60100, 7800), ("V1034", 62100, 1300), ("V1042", 61100, 3400),
        ("V1043", 61100, 2200), ("V1044", 65200, 700), ("V1045", 64300, 1600), ("V1046", 60100, 6200),
        ("V1047", 60200, 8800), ("V1024", 60200, 2500),
    ]
    for vid, acct, base in filler:
        owner = "" if vid == "V1043" else rng.choice(OWNERS)
        roster(vid, acct, ACCOUNTS[acct], owner)
        annual = round(base * 12 * rng.uniform(1.00, 1.15), -2)
        budget(vid, acct, annual)
        dims(vid, acct, source=rng.choice(["prior_je", "prior_je", "prior_je", "latest_bill"]))
        for m in range(1, 10):
            amt = round(base * rng.uniform(0.9, 1.1), 2)
            posted = nxt(m, rng.randint(3, 20))
            style = rng.random()
            if style < 0.7:
                bill(vid, acct, amt, posted, date(YEAR, m, 1), mend(m))
            elif style < 0.85:
                bill(vid, acct, amt, posted, memo=f"Services - {calendar.month_name[m]} {YEAR}")
            else:
                bill(vid, acct, amt, posted, memo="Monthly services")
    # budget with no vendor
    budget("", 65100, 36000)


def write_csv(path: Path, columns: list[str], rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    GL.clear(); ROSTER.clear(); BUDGET.clear(); JE_DIMS.clear(); _doc[0] = 0
    seeded()
    generic(rng)
    GL.sort(key=lambda r: (r["journal_posting_date"], r["document_id"]))

    # roster: GL actual YTD (informational) and the spread YTD for lines without one
    for r in ROSTER:
        r["gl_actual_ytd"] = money(sum(Decimal(g["signed_amount"]) for g in GL
                                       if g["vendor_id"] == r["vendor_id"] and g["gl_account"] == r["gl_account"]
                                       and g["journal_posting_date"] <= "2026-09-30"))
        if r["budget_ytd_spread"] is None:
            b = next((b for b in BUDGET if b["vendor_id"] == r["vendor_id"] and b["gl_account"] == r["gl_account"]), None)
            r["budget_ytd_spread"] = money(sum(b["months"][:9])) if b else "0.00"
        else:
            r["budget_ytd_spread"] = money(r["budget_ytd_spread"])

    gl_cols = ["entry_date", "gl_account", "gl_account_name", "vendor_id", "vendor_name", "department_name",
               "location_name", "signed_amount", "gl_journal_id", "journal_posting_date", "service_period_from",
               "service_period_to", "service_month", "service_date_source", "description", "document_id"]
    write_csv(out / "gl_detail.csv", gl_cols, GL)
    write_csv(out / "roster.csv", ["vendor_name", "vendor_id", "gl_account", "gl_account_name", "vendor_type",
                                   "budget_ytd_spread", "gl_actual_ytd", "liability_prior_year_remaining", "owner"],
              ROSTER)
    mcols = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    write_csv(out / "budget.csv", ["vendor_id", "vendor_name", "gl_account", "gl_account_name", *mcols, "annual"],
              [{**{k: b[k] for k in ("vendor_id", "vendor_name", "gl_account", "gl_account_name")},
                **{c: money(v) for c, v in zip(mcols, b["months"])}, "annual": money(b["annual"])} for b in BUDGET])
    legal = [
        {"vendor": "Ashgrove & Pell LLP", "vendor_id": "V2001", "amount": "42500.00", "customer": "C-201",
         "project": "P-L01", "dept": "D100", "location": "L10", "item": "I-LEGAL"},
        {"vendor": "Brindle Hart Legal", "vendor_id": "V2002", "amount": "18750.00", "customer": "", "project": "",
         "dept": "D100", "location": "L10", "item": "I-LEGAL"},
        {"vendor": "Quarrington Vale LLP", "vendor_id": "V2003", "amount": "27300.00", "customer": "C-202",
         "project": "P-L02", "dept": "D100", "location": "L10", "item": "I-LEGAL"},
    ]
    write_csv(out / "legal_rows.csv", ["vendor", "vendor_id", "amount", "customer", "project", "dept", "location",
                                       "item"], legal)
    capex = [
        # deal, project, loc, vendor_id, area, budgeted, cost, wr date, pct, fully, placed, invoiced
        ("Harbor Street Fit-Out", "P-1001", "L40", "V3001", "Framing & drywall", 120000, 118000, "2026-03-02", 100, "Y", "N", 100000),
        ("Harbor Street Fit-Out", "P-1001", "L40", "V3001", "Ceilings", 40000, 42000, "2026-05-11", 50, "N", "N", 10000),
        ("Harbor Street Fit-Out", "P-1001", "L40", "V3002", "Lighting", 60000, 60000, "2026-05-18", 80, "N", "N", 30000),
        ("West Campus Lab Expansion", "P-1002", "L20", "V3002", "Power distribution", 90000, 95500, "2026-04-06", 40, "N", "N", 50000),
        ("West Campus Lab Expansion", "P-1002", "L20", "V3002", "Panel upgrade", 25000, 25000, "2026-07-13", 20, "N", "N", 0),
        ("West Campus Lab Expansion", "P-1002", "L20", "V3003", "Casework", 70000, 68000, "2026-06-01", 25, "N", "N", 10000),
        ("West Campus Lab Expansion", "P-1002", "L20", "V3003", "Reception desk", 15000, None, "2026-08-24", None, "N", "N", 0),
        ("Main Office Phone Booths", "P-1003", "L10", "V3001", "Booth install", 30000, 33250, "2026-07-20", 60, "N", "N", 12000),
    ]
    write_csv(out / "capex_tracker.csv", ["deal", "project_id", "location_id", "vendor", "area", "budgeted_cost", "cost",
                                          "work_request_date", "pct_complete", "fully_complete", "placed_in_service",
                                          "invoiced_to_date", "vendor_id", "account_id", "dept_id"],
              [{"deal": d, "project_id": p, "location_id": loc, "vendor": VENDORS[v][0], "area": a,
                "budgeted_cost": money(b), "cost": "" if c is None else money(c), "work_request_date": wr,
                "pct_complete": "" if pc is None else pc, "fully_complete": fc, "placed_in_service": pis,
                "invoiced_to_date": money(inv), "vendor_id": v, "account_id": 16000, "dept_id": "D700"}
               for d, p, loc, v, a, b, c, wr, pc, fc, pis, inv in capex])
    (out / "capex_meta.json").write_text(json.dumps(
        {"unallocated_gl_total": "4250.00", "needs_attention_count": 2, "needs_attention_total": "4250.00"},
        indent=2), encoding="utf-8")

    dimrows = [{"dim_type": "account", "id": k, "name": v} for k, v in ACCOUNTS.items()]
    dimrows += [{"dim_type": "dept", "id": k, "name": v} for k, v in DEPTS.items()]
    dimrows += [{"dim_type": "location", "id": k, "name": v} for k, v in LOCATIONS.items()]
    dimrows += [{"dim_type": "item", "id": k, "name": v} for k, v in ITEMS.items()]
    dimrows += [{"dim_type": "project", "id": k, "name": v} for k, v in PROJECTS.items()]
    dimrows += [{"dim_type": "customer", "id": k, "name": v} for k, v in CUSTOMERS.items()]
    dimrows += [{"dim_type": "vendor", "id": k, "name": v[0]} for k, v in VENDORS.items()]
    write_csv(out / "dimension_names.csv", ["dim_type", "id", "name"], dimrows)
    write_csv(out / "je_dims.csv", ["vendor_id", "gl_account", "dept", "location", "item", "source"], JE_DIMS)

    # Placeholders so the engine can load the folder, then derive last month's JE from the engine itself.
    write_csv(out / "prior_je.csv", ["je_id", "acct", "vendor_id", "vendor", "dept", "amount"], [])
    (out / "prior_je_meta.json").write_text(json.dumps({"period": "2026-08", "reversed_total": "0"}), encoding="utf-8")
    write_csv(out / "mom_gl.csv", ["vendor_id", "vendor", "gl_account", "prior_bills", "prior_accrual",
                                   "prior_reversal", "current_bills", "current_reversal", "other"], [])
    derive_prior_months(out)
    print(f"Wrote sample data for {PERIOD} to {out} ({len(GL)} GL rows, {len(ROSTER)} roster lines)")


def derive_prior_months(out: Path):
    """Last month's booked JE = the engine's own August run (+ a line removed this month and the
    August manual add); July's JE gives the reversal posted on Aug 1."""
    from accrual_workbook.engine.config import load_config
    from accrual_workbook.engine.loader import load_inputs
    from accrual_workbook.engine.model import State, run

    cfg = load_config(ROOT / "config" / "rules.yaml")
    inputs = load_inputs(out)
    legal_by_month = {"2026-07": {"V2001": 35000, "V2002": 21000}, "2026-08": {"V2001": 39000, "V2002": 22000}}

    def booked(period: str, extra: list) -> dict:
        res = run(period, inputs, cfg, State())
        acc: dict = {}
        for ln in res["vendor_opex"]["lines"]:
            if ln["final_accrual"] > 0:
                acc[(ln["vendor_id"], ln["gl_account"])] = ln["final_accrual"]
        for vid, amt in legal_by_month[period].items():
            acc[(vid, 61500)] = Decimal(amt)
        for vid, acct, amt in extra:
            acc[(vid, acct)] = Decimal(amt)
        return acc

    aug = booked("2026-08", [("V1019", 64300, 2500), ("V1040", 65100, 1800)])
    jul = booked("2026-07", [("V1019", 64300, 2500)])
    dims_by_key = {(d["vendor_id"], d["gl_account"]): d["dept"] for d in JE_DIMS}
    pje = []
    for i, ((vid, acct), amt) in enumerate(sorted(aug.items()), 1):
        pje.append({"je_id": "ACCR-202608", "acct": acct, "vendor_id": vid, "vendor": VENDORS[vid][0],
                    "dept": dims_by_key.get((vid, acct), "D100"), "amount": money(amt)})
    capex_aug = [("V3001", 24000), ("V3002", 21000), ("V3003", 4000)]
    for vid, amt in capex_aug:
        pje.append({"je_id": "ACCR-202608", "acct": 16005, "vendor_id": vid, "vendor": VENDORS[vid][0],
                    "dept": "D700", "amount": money(amt)})
    write_csv(out / "prior_je.csv", ["je_id", "acct", "vendor_id", "vendor", "dept", "amount"], pje)
    total = sum(Decimal(p["amount"]) for p in pje)
    (out / "prior_je_meta.json").write_text(json.dumps({"period": "2026-08", "reversed_total": money(total)},
                                                       indent=2), encoding="utf-8")

    # MoM GL: bills posted in Aug / Sep (AP + receipts, expense accounts incl. legal), accruals booked and reversed
    def bills(month: str) -> dict:
        acc: dict = {}
        for g in GL:
            acct = int(g["gl_account"])
            if g["gl_journal_id"] not in ("APJ", "UNB") or not g["vendor_id"] or not (60000 <= acct <= 65999):
                continue
            if acct in (60510, 60520) or not g["journal_posting_date"].startswith(month):
                continue
            k = (g["vendor_id"], acct)
            acc[k] = acc.get(k, Decimal(0)) + Decimal(g["signed_amount"])
        return acc

    prior_bills, cur_bills = bills("2026-08"), bills("2026-09")
    keys = sorted(set(prior_bills) | set(cur_bills) | set(aug) | set(jul))
    rows = []
    for k in keys:
        rows.append({"vendor_id": k[0], "vendor": VENDORS[k[0]][0], "gl_account": k[1],
                     "prior_bills": money(prior_bills.get(k, 0)), "prior_accrual": money(aug.get(k, 0)),
                     "prior_reversal": money(jul.get(k, 0)), "current_bills": money(cur_bills.get(k, 0)),
                     "current_reversal": money(aug.get(k, 0)), "other": "0.00"})
    write_csv(out / "mom_gl.csv", ["vendor_id", "vendor", "gl_account", "prior_bills", "prior_accrual",
                                   "prior_reversal", "current_bills", "current_reversal", "other"], rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "sample"))
    main(Path(ap.parse_args().out))
