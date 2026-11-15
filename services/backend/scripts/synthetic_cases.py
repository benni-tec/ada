"""Put synthetic cases on a "Suspected cancer pathway" case type through ADA's REST API,
so the open-case list and the county dashboards have something to show.

Every case is invented: keys are SYN-#####, and nothing describes a person. Per-step
days are drawn around Finland's typical days for lung cancer (Yle MOT 2025, the pathway
model's comparison) and around 1.3 x the Nordic targets for colorectal and pancreatic
cancer, where Finland publishes no per-step days. Each county gets a fixed synthetic
pace, and the pathways speed up gently over the months, so the trend has a shape. None
of this is data about Finland's counties.

    uv run python scripts/synthetic_cases.py --api http://localhost:8000/api \\
        --project <project id> --cases 300 --seed 1
"""

import argparse
import math
import random
from datetime import date, timedelta
from typing import Any

import httpx

COUNTIES = (
    "Helsinki",
    "Itä-Uusimaa",
    "Keski-Uusimaa",
    "Länsi-Uusimaa",
    "Vantaa ja Kerava",
    "Varsinais-Suomi",
    "Satakunta",
    "Kanta-Häme",
    "Pirkanmaa",
    "Päijät-Häme",
    "Kymenlaakso",
    "Etelä-Karjala",
    "Etelä-Savo",
    "Pohjois-Savo",
    "Pohjois-Karjala",
    "Keski-Suomi",
    "Etelä-Pohjanmaa",
    "Pohjanmaa",
    "Keski-Pohjanmaa",
    "Pohjois-Pohjanmaa",
    "Kainuu",
    "Lappi",
)
SITES = (("lung", 0.4), ("colorectal", 0.45), ("pancreas", 0.15))
STEPS = (
    "symptoms_to_contact",
    "contact_to_physician",
    "physician_to_imaging",
    "imaging_to_referral",
    "referral_to_specialist",
    "specialist_to_workup",
    "workup_to_treatment",
)
# The steps the targets table names, by step; symptoms to contact has no target.
TRIGGER = {
    "lung": ["lung_imaging"],
    "colorectal": ["crc_imaging_finding"],
    "pancreas": ["panc_imaging"],
}
SUSPICION = {
    "lung": ["lung_symptoms_smoker"],
    "colorectal": ["crc_blood"],
    "pancreas": ["panc_jaundice"],
}
AGES = (("00-49", 0.06), ("50-59", 0.12), ("60-69", 0.3), ("70-79", 0.36), ("80-89", 0.16))


def pick(rng: random.Random, weighted: tuple[tuple[str, float], ...]) -> str:
    return rng.choices([w[0] for w in weighted], [w[1] for w in weighted])[0]


def typical_days(version: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Per site and step, the centre of the draw: Finland's days where the model has
    them, 1.3 x the target elsewhere, 40 days of symptoms before the first contact."""
    targets = version["compiled"]["targets"]
    finland = version["spec"]["comparison"]["days"]
    centres: dict[str, dict[str, float]] = {}
    for site in version["spec"]["sites"]:
        known = finland.get(site, {})
        row: dict[str, float] = {}
        for step in STEPS:
            if step in known:
                row[step] = known[step]
            elif step == "symptoms_to_contact":
                row[step] = 40
            else:
                per = targets.get(site, {}).get(step, {})
                target = per.get("any") or per.get("surgery")
                row[step] = 1.3 * target if target else 7
        centres[site] = row
    return centres


def case(
    rng: random.Random, n: int, centres: dict[str, dict[str, float]], today: date, months: int
) -> tuple[str, dict[str, Any]]:
    site = pick(rng, SITES)
    county = rng.choice(COUNTIES)
    # A fixed synthetic pace per county, from 0.8 to 1.3.
    pace = 0.8 + 0.5 * (COUNTIES.index(county) * 7 % len(COUNTIES)) / (len(COUNTIES) - 1)
    started = today - timedelta(days=rng.randint(0, months * 30))
    # Pathways speed up over the months: 1.25 at the oldest, 0.95 now.
    age_of_case = (today - started).days / (months * 30)
    trend = 0.95 + 0.3 * age_of_case
    days: dict[str, int] = {}
    elapsed = 0
    budget = (today - started).days
    for step in STEPS:
        drawn = max(
            0, round(rng.lognormvariate(math.log(centres[site][step] * pace * trend), 0.45))
        )
        if step != "symptoms_to_contact" and elapsed + drawn > budget:
            days[step] = max(0, budget - elapsed)
            break
        days[step] = drawn
        if step != "symptoms_to_contact":
            elapsed += drawn
    finished = len(days) == len(STEPS) and elapsed <= budget
    values: dict[str, Any] = {
        "site": site,
        "sex": rng.choice(("female", "male")),
        "age_band": pick(rng, AGES),
        "route": pick(
            rng,
            (
                ("public_health_centre", 0.6),
                ("occupational", 0.15),
                ("private", 0.1),
                ("emergency", 0.15),
            ),
        ),
        "intent": "curative" if rng.random() < 0.7 else "palliative",
        "modality": "surgery" if site != "pancreas" or rng.random() < 0.4 else "drugs",
        "presentation": SUSPICION[site] + (TRIGGER[site] if "imaging_to_referral" in days else []),
        "days": days,
        "treatment_started": finished,
        "county": county,
        "first_contact": started.isoformat(),
    }
    return f"SYN-{n:05}", values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--project", required=True)
    parser.add_argument("--cases", type=int, default=300)
    parser.add_argument("--months", type=int, default=18)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    with httpx.Client(base_url=args.api, timeout=60) as api:
        models = api.get(f"/projects/{args.project}/models").raise_for_status().json()
        model = next(m for m in models if m["kind"] == "patient_pathway" and m["case_type_id"])
        version = api.get(f"/models/{model['id']}/versions/latest").raise_for_status().json()
        centres = typical_days(version)
        today = date.today()
        for n in range(1, args.cases + 1):
            key, values = case(rng, n, centres, today, args.months)
            api.put(
                f"/case-types/{model['case_type_id']}/cases/{key}", json={"values": values}
            ).raise_for_status()
        print(f"{args.cases} synthetic cases on case type {model['case_type_id']}")


if __name__ == "__main__":
    main()
