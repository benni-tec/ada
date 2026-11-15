"""Writes shortages.csv: ~300 synthetic drug-shortage rows, fixed seed. Run from anywhere."""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

rng = random.Random(42)
DRUGS = {
    "amoxicillin": (["250 mg", "500 mg", "125 mg/5 ml"], ["capsule", "suspension"]),
    "metformin": (["500 mg", "850 mg", "1000 mg"], ["tablet"]),
    "salbutamol": (["100 mcg/dose"], ["inhaler"]),
    "insulin glargine": (["100 IU/ml"], ["pen", "vial"]),
    "ibuprofen": (["200 mg", "400 mg", "600 mg"], ["tablet", "suspension"]),
    "methylphenidate": (["10 mg", "20 mg", "36 mg"], ["tablet", "capsule"]),
    "furosemide": (["20 mg", "40 mg"], ["tablet", "injection"]),
    "cisplatin": (["50 mg/50 ml"], ["infusion"]),
    "levothyroxine": (["50 mcg", "100 mcg"], ["tablet"]),
    "amlodipine": (["5 mg", "10 mg"], ["tablet"]),
    "ceftriaxone": (["1 g", "2 g"], ["injection"]),
    "sertraline": (["50 mg", "100 mg"], ["tablet"]),
    "penicillin V": (["1 MIU", "1.5 MIU"], ["tablet", "suspension"]),
    "heparin": (["5000 IU/ml"], ["injection"]),
    "oseltamivir": (["30 mg", "75 mg"], ["capsule"]),
    "paracetamol": (["500 mg", "125 mg"], ["tablet", "suppository"]),
}
COUNTRIES = [
    "Switzerland",
    "Germany",
    "Austria",
    "France",
    "Italy",
    "Spain",
    "Netherlands",
    "Sweden",
]
STATUS = ["ongoing", "resolved", "resolved", "anticipated"]
REASONS = [
    ("manufacturing issue", 4),
    ("raw material shortage", 3),
    ("increased demand", 3),
    ("regulatory delay", 1),
    ("transport disruption", 1),
    ("discontinuation", 1),
    ("quality defect / recall", 2),
]
SOURCES = {
    "Switzerland": "BWL",
    "Germany": "BfArM",
    "Austria": "BASG",
    "France": "ANSM",
    "Italy": "AIFA",
    "Spain": "AEMPS",
    "Netherlands": "Farmanco",
    "Sweden": "Lakemedelsverket",
}
rows = []
for _ in range(300):
    drug = rng.choice(list(DRUGS))
    strengths, forms = DRUGS[drug]
    country = rng.choice(COUNTRIES)
    # winter-heavy starts, 2022-2026
    start = date(2022, 1, 1) + timedelta(days=rng.randrange(0, 365 * 4 + 300))
    if start.month in (10, 11, 12, 1, 2) and rng.random() < 0.3:
        start += timedelta(days=rng.randrange(0, 30))
    status = rng.choice(STATUS)
    if start > date(2026, 9, 1):
        status = "ongoing"
    reasons, weights = zip(*REASONS, strict=True)
    rows.append(
        [
            drug,
            rng.choice(strengths),
            rng.choice(forms),
            country,
            status,
            start.isoformat(),
            rng.choices(reasons, weights)[0],
            SOURCES[country],
        ]
    )
rows.sort(key=lambda r: r[5])
out = Path(__file__).with_name("shortages.csv")
with out.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(
        ["generic_name", "strength", "form", "country", "status", "start_date", "reason", "source"]
    )
    w.writerows(rows)
print(out, len(rows))
