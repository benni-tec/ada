"""Write the demo's curated dashboards from a running ADA into the fixture `ada seed-demo`
replays (src/ada/entrypoints/cli/demo.json): each dashboard's layout, widgets and alert
rules, and every operator and data source behind them, keyed by their ids here. Nothing is
fetched: the sources are re-registered and fetched where the seed runs.

    uv run python scripts/export_demo.py --api http://localhost:8000/api \\
        --project <project id>
"""

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

DASHBOARDS = (
    "National Cancer Strategy 2026–2035",
    "Pathway times by county (synthetic)",
    "Data quality: county indicators",
)
OUT = Path(__file__).parent.parent / "src" / "ada" / "entrypoints" / "cli" / "demo.json"
REGISTRATION = (
    "name",
    "access_kind",
    "address",
    "format",
    "options",
    "freshness",
    "declared_schema",
    "provenance",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    api = httpx.Client(base_url=args.api, timeout=120)
    get = lambda path: api.get(path).raise_for_status().json()  # noqa: E731

    by_name = {d["name"]: d for d in get(f"/projects/{args.project}/dashboards")}
    rules = {
        group["dashboard"]["id"]: group["rules"]
        for group in get(f"/projects/{args.project}/alert-rules")
    }
    dashboards: list[dict[str, Any]] = []
    widgets: dict[str, dict[str, Any]] = {}
    roots: list[str] = []
    for name in DASHBOARDS:
        view = get(f"/dashboards/{by_name[name]['id']}")
        slots = []
        for slot in view["version"]["slots"]:
            widget = get(f"/widgets/{slot['widget_id']}")
            widgets[widget["id"]] = {
                key: widget[key]
                for key in ("operator_id", "inputs", "type", "title", "spec", "note")
            }
            roots += [widget["operator_id"], *widget["inputs"].values()]
            slots.append(
                {key: slot[key] for key in ("name", "description", "layout")}
                | {"widget": widget["id"]}
            )
        dashboard_rules = []
        for entry in rules.get(view["dashboard"]["id"], []):
            rule = entry.get("rule", entry)
            dashboard_rules.append(
                {
                    key: rule[key]
                    for key in (
                        "name",
                        "operator_id",
                        "formula",
                        "key_columns",
                        "severity",
                        "check_interval_seconds",
                        "max_data_age_seconds",
                    )
                }
            )
            roots.append(rule["operator_id"])
        dashboards.append(
            {
                "name": name,
                "default_time_range": view["dashboard"]["default_time_range"],
                "slots": slots,
                "rules": dashboard_rules,
            }
        )

    # Every operator behind them, inputs before the operators that read them.
    operators: dict[str, dict[str, Any]] = {}
    for root in dict.fromkeys(roots):
        for operator in get(f"/operators/{root}/lineage"):
            operators.setdefault(operator["id"], operator)
    ordered: list[dict[str, Any]] = []
    placed: set[str] = set()

    def place(id: str) -> None:
        if id in placed:
            return
        operator = operators[id]
        for input in operator["inputs"]:
            place(input)
        placed.add(id)
        if operator["kind"] == "source":
            ordered.append(
                {"key": id, "kind": "source", "source": operator["params"]["data_source_id"]}
            )
        else:
            ordered.append(
                {
                    "key": id,
                    "kind": operator["kind"],
                    "sql": operator["params"]["sql"],
                    "inputs": operator["inputs"],
                    "roles": operator["output"].get("roles"),
                    "materialize": operator.get("materializing", False),
                }
            )

    for id in operators:
        place(id)
    sources = {}
    case_types = {}
    for operator in ordered:
        if operator["kind"] == "source":
            source = get(f"/sources/{operator['source']}")
            sources[source["id"]] = {key: source[key] for key in REGISTRATION}
            if source["access_kind"] == "cases":
                case_types[source["address"]] = get(f"/case-types/{source['address']}")["name"]

    fixture = {
        "dashboards": dashboards,
        "widgets": widgets,
        "operators": ordered,
        "sources": sources,
        "case_types": case_types,
    }
    OUT.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n")
    counts = f"{len(dashboards)} dashboards, {len(widgets)} widgets, {len(ordered)} operators"
    print(f"{counts}, {len(sources)} sources -> {OUT}")


if __name__ == "__main__":
    main()
