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
import random
from datetime import date

import httpx

from ada.entrypoints.cli.synthetic import case, typical_days


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
