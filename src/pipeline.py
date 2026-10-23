"""ETL steps used by the Airflow DAG. Each step passes data through JSON files in DATA_DIR
(raw landing zone) so that XCom only carries small paths and counters.

Run locally without Airflow:  python -m src.pipeline
"""
import json
import os
from pathlib import Path

from src.database import postgres
from src.extractors.gdacs_api import fetch_gdacs
from src.extractors.geonet_api import fetch_geonet
from src.extractors.nasa_eonet import fetch_eonet
from src.extractors.usgs_earthquake import fetch_usgs
from src.extractors.reliefweb_api import fetch_reliefweb_api
from src.extractors.web_scraper import fetch_phivolcs_html
from src.transformations.validate import validate_rows

EXTRACTORS = {
    "nasa_eonet": fetch_eonet,
    "gdacs": fetch_gdacs,
    "usgs": fetch_usgs,
    "geonet": fetch_geonet,
    "reliefweb_api": fetch_reliefweb_api,
    "phivolcs_html": fetch_phivolcs_html,  # web scraping (requests + BeautifulSoup)
}


class SimulatedSourceFailure(RuntimeError):
    """Raised on purpose to demonstrate that one failing source does not stop the others."""


def run_dir(run_id):
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in run_id)
    path = Path(os.getenv("DATA_DIR", "data")) / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write(path, rows):
    path.write_text(json.dumps(rows, default=str, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def extract(source, run_id, simulate_failure=()):
    if source in simulate_failure:
        raise SimulatedSourceFailure(f"Simulated outage for source '{source}'")
    rows = EXTRACTORS[source]()
    return {"source": source, "raw_path": _write(run_dir(run_id) / f"{source}_raw.json", rows),
            "extracted": len(rows)}


def transform_validate(extract_result, run_id):
    source = extract_result["source"]
    valid, quarantined, stats = validate_rows(_read(extract_result["raw_path"]))
    folder = run_dir(run_id)
    return {"source": source, **stats,
            "valid_path": _write(folder / f"{source}_valid.json", valid),
            "quarantine_path": _write(folder / f"{source}_quarantine.json", quarantined)}


def load(transform_result, run_id):
    valid = _read(transform_result["valid_path"])
    quarantined = _read(transform_result["quarantine_path"])
    with postgres.get_connection() as conn:
        counts = postgres.upsert_events(valid, conn)
        postgres.resolve_quarantine(transform_result["source"],
                                    [r["source_event_id"] for r in valid], conn)
        postgres.upsert_quarantine(quarantined, run_id, conn)
    return {**{k: v for k, v in transform_result.items() if not k.endswith("_path")},
            "inserted": counts["inserted"], "updated": counts["updated"],
            "loaded": counts["inserted"] + counts["updated"]}


def run_all(run_id="manual", sources=None):
    """Sequential local run (no Airflow). A failing source is logged and skipped."""
    results = {}
    for source in sources or EXTRACTORS:
        try:
            results[source] = load(transform_validate(extract(source, run_id), run_id), run_id)
        except Exception as exc:  # keep going with the other sources
            results[source] = {"error": repr(exc)}
    results["dedup"] = postgres.mark_cross_source_duplicates()
    results["quality"] = postgres.run_quality_checks(run_id)
    return results


if __name__ == "__main__":
    from datetime import datetime, timezone
    print(json.dumps(run_all("manual__" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")),
                     indent=2, default=str))
