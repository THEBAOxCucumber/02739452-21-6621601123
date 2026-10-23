"""NASA EONET v3 — natural events (wildfires, storms, floods, ...). Docs: https://eonet.gsfc.nasa.gov/docs/v3"""
import os

from src.http_client import get_json, make_session
from src.transformations.normalize import (
    EONET_CATEGORY_MAP, geometry_point, make_row, to_float, to_utc_iso, utc_now_iso,
)

SOURCE_NAME = "nasa_eonet"
URL = "https://eonet.gsfc.nasa.gov/api/v3/events"


def parse_eonet(payload, fetched_at):
    rows = []
    for event in payload.get("events", []):
        geometries = event.get("geometry") or []
        geom = geometries[-1] if geometries else {}  # latest observation -> location, size
        first = geometries[0] if geometries else {}  # first observation -> event start time
        lat, lon = geometry_point(geom)
        categories = event.get("categories") or [{}]
        category_id = categories[0].get("id", "")
        sources = event.get("sources") or [{}]
        rows.append(make_row(
            source_name=SOURCE_NAME,
            source_event_id=event.get("id"),
            event_type=EONET_CATEGORY_MAP.get(category_id, category_id or "unknown"),
            event_name=event.get("title"),
            event_time=to_utc_iso(first.get("date")),
            latitude=lat,
            longitude=lon,
            magnitude=to_float(geom.get("magnitudeValue")),
            magnitude_unit=geom.get("magnitudeUnit"),
            severity=None,  # EONET has no severity scale; open/closed is kept in raw_data
            source_url=sources[0].get("url") or event.get("link"),
            fetched_at=fetched_at,
            raw_data={
                "id": event.get("id"), "title": event.get("title"), "link": event.get("link"),
                "closed": event.get("closed"), "categories": categories, "sources": sources,
                "geometry_count": len(geometries), "first_date": first.get("date"),
                "latest_geometry": geom,
            },
        ))
    return rows


def fetch_eonet(start=None, limit=None):
    params = {
        "status": "all",
        "start": start or os.getenv("EONET_START_DATE", "2026-01-01"),
        "limit": limit or int(os.getenv("EONET_LIMIT", "500")),
    }
    payload = get_json(make_session(), URL, params=params)
    return parse_eonet(payload, utc_now_iso())
