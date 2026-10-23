"""USGS FDSN Event API — earthquakes. Docs: https://earthquake.usgs.gov/fdsnws/event/1/"""
import os

from src.http_client import get_json, make_session
from src.transformations.normalize import make_row, to_float, to_utc_iso, utc_now_iso

SOURCE_NAME = "usgs"
URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"


def parse_usgs(payload, fetched_at):
    rows = []
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        rows.append(make_row(
            source_name=SOURCE_NAME,
            source_event_id=feature.get("id"),
            event_type="earthquake",
            event_name=props.get("title") or props.get("place") or "Earthquake",
            event_time=to_utc_iso(props.get("time")),
            latitude=to_float(coords[1]) if len(coords) > 1 else None,
            longitude=to_float(coords[0]) if coords else None,
            magnitude=to_float(props.get("mag")),
            magnitude_unit=props.get("magType"),
            severity=props.get("alert"),  # PAGER alert: green/yellow/orange/red or None
            source_url=props.get("url"),
            fetched_at=fetched_at,
            raw_data={
                "id": feature.get("id"), "place": props.get("place"), "mag": props.get("mag"),
                "magType": props.get("magType"), "time": props.get("time"),
                "depth_km": coords[2] if len(coords) > 2 else None, "tsunami": props.get("tsunami"),
                "status": props.get("status"), "net": props.get("net"), "sig": props.get("sig"),
            },
        ))
    return rows


def fetch_usgs(starttime=None, minmagnitude=None, limit=None):
    params = {
        "format": "geojson",
        "starttime": starttime or os.getenv("USGS_START_DATE", "2026-01-01"),
        "minmagnitude": minmagnitude or float(os.getenv("USGS_MIN_MAGNITUDE", "4.5")),
        "limit": limit or int(os.getenv("USGS_LIMIT", "1000")),
        "orderby": "time",
    }
    payload = get_json(make_session(), URL, params=params)
    return parse_usgs(payload, utc_now_iso())
