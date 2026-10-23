"""ReliefWeb API v2 — disasters. Docs: https://apidoc.reliefweb.int/read/resources/disasters/

Requires a pre-approved appname (request: https://apidoc.reliefweb.int/), set as
RELIEFWEB_APPNAME in .env. Limits: <= 1000 items per call, 10,000 calls per day.

The disasters resource has no coordinates, so each disaster is placed at its primary
country's centre (src/reference/country_centroids.csv) and marked
location_precision = "country_centroid". If the API ever returns primary_country.location,
that is used instead.
"""
import csv
import os
import time
from functools import lru_cache
from pathlib import Path

from src.http_client import DEFAULT_TIMEOUT, make_session
from src.transformations.normalize import HAZARD_CODE_MAP, make_row, to_float, to_utc_iso, utc_now_iso

SOURCE_NAME = "reliefweb_api"
URL = "https://api.reliefweb.int/v2/disasters"
PAGE_LIMIT = 1000  # API maximum
MAX_PAGES = 5
CENTROIDS_CSV = Path(__file__).resolve().parent.parent / "reference" / "country_centroids.csv"
FIELDS = ["id", "name", "glide", "status", "date", "primary_country", "primary_type", "url"]


class ReliefWebAppnameMissing(RuntimeError):
    """RELIEFWEB_APPNAME is not set; the source is skipped rather than failed."""


@lru_cache(maxsize=1)
def country_centroids():
    with open(CENTROIDS_CSV, encoding="utf-8") as f:
        return {r["iso3"]: (float(r["lat"]), float(r["lon"])) for r in csv.DictReader(f)}


def _location(country):
    loc = country.get("location") or {}
    lat, lon = to_float(loc.get("lat")), to_float(loc.get("lon"))
    if lat is not None and lon is not None:
        return lat, lon, "reliefweb_country_location"
    centroid = country_centroids().get((country.get("iso3") or "").upper())
    if centroid:
        return centroid[0], centroid[1], "country_centroid"
    return None, None, None


def parse_reliefweb_api(payload, fetched_at):
    rows = []
    for item in payload.get("data", []):
        f = item.get("fields") or {}
        country = f.get("primary_country") or {}
        primary_type = f.get("primary_type") or {}
        code = (primary_type.get("code") or "").upper()
        lat, lon, precision = _location(country)
        rows.append(make_row(
            source_name=SOURCE_NAME,
            source_event_id=item.get("id") or f.get("id"),
            event_type=HAZARD_CODE_MAP.get(code, code.lower() or "unknown"),
            event_name=f.get("name"),
            event_time=to_utc_iso((f.get("date") or {}).get("event")),
            latitude=lat,
            longitude=lon,
            severity=None,  # ReliefWeb has no severity scale; status is kept in raw_data
            country=country.get("name"),
            source_url=f.get("url"),
            fetched_at=fetched_at,
            raw_data={
                "id": item.get("id"), "name": f.get("name"), "glide": f.get("glide"),
                "status": f.get("status"), "hazard_code": code, "hazard_name": primary_type.get("name"),
                "country_iso3": country.get("iso3"), "date": f.get("date"),
                "location_precision": precision,
            },
        ))
    return rows


def fetch_reliefweb_api(appname=None, start_date=None, sleep=time.sleep):
    appname = appname or os.getenv("RELIEFWEB_APPNAME", "").strip()
    if not appname:
        raise ReliefWebAppnameMissing(
            "RELIEFWEB_APPNAME is not set. Request an approved appname at "
            "https://apidoc.reliefweb.int/ and add it to .env")
    start = start_date or os.getenv("RELIEFWEB_START_DATE", "2025-01-01")
    body = {
        "limit": PAGE_LIMIT,
        "fields": {"include": FIELDS},
        "filter": {"field": "date.event", "value": {"from": f"{start}T00:00:00+00:00"}},
        "sort": ["date.event:desc"],
    }
    session = make_session()
    fetched_at = utc_now_iso()
    rows, offset = [], 0
    for page in range(MAX_PAGES):
        if page:
            sleep(1)
        response = session.post(URL, params={"appname": appname}, json={**body, "offset": offset},
                                timeout=DEFAULT_TIMEOUT)
        if response.status_code == 403:
            raise PermissionError(f"ReliefWeb rejected appname '{appname}' (HTTP 403): {response.text[:200]}")
        response.raise_for_status()
        payload = response.json()
        rows.extend(parse_reliefweb_api(payload, fetched_at))
        offset += payload.get("count", 0)
        if not payload.get("count") or offset >= payload.get("totalCount", 0):
            break
    return rows
