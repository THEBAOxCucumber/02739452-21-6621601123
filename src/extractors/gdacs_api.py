"""GDACS event-list API — alerts with alert level. Swagger: https://www.gdacs.org/gdacsapi/swagger/index.html

gdacs.org/robots.txt asks for at most one request per 60 seconds and visits between
04:00-06:45 UTC, so requests are sequential with a 60 s pause and the DAG is scheduled
inside that window.

One request per hazard type rather than paging one mixed list: page order of the mixed
list is unstable (page 2 repeated half of page 1) and wildfires crowd out other types.
"""
from datetime import datetime, timezone
import os
import time

from src.http_client import get_json, make_session
from src.transformations.normalize import (
    HAZARD_CODE_MAP, make_row, to_float, to_utc_iso, utc_now_iso,
)

SOURCE_NAME = "gdacs"
URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
REQUEST_INTERVAL_SECONDS = 60  # robots.txt Request-rate: 1/60
VISIT_WINDOW_START_MIN = 4 * 60          # robots.txt Visit-time: 0400-0645 UTC
VISIT_WINDOW_LAST_START_MIN = 6 * 60 + 38  # leave ~7 min for 6 requests to finish by 06:45


def gdacs_event_key(event_type, event_id):
    return f"{event_type}-{event_id}"


def parse_gdacs(payload, fetched_at):
    rows = []
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        severity = props.get("severitydata") or {}
        code = props.get("eventtype", "")
        rows.append(make_row(
            source_name=SOURCE_NAME,
            source_event_id=gdacs_event_key(code, props.get("eventid")) if props.get("eventid") else "",
            event_type=HAZARD_CODE_MAP.get(code, code.lower() or "unknown"),
            event_name=props.get("name") or props.get("eventname"),
            event_time=to_utc_iso(props.get("fromdate")),
            latitude=to_float(coords[1]) if len(coords) > 1 else None,
            longitude=to_float(coords[0]) if coords else None,
            magnitude=to_float(severity.get("severity")),
            magnitude_unit=severity.get("severityunit"),
            severity=(props.get("alertlevel") or "").lower() or None,
            country=props.get("country") or None,
            source_url=(props.get("url") or {}).get("report"),
            fetched_at=fetched_at,
            raw_data={
                "eventtype": code, "eventid": props.get("eventid"), "episodeid": props.get("episodeid"),
                "alertlevel": props.get("alertlevel"), "alertscore": props.get("alertscore"),
                "fromdate": props.get("fromdate"), "todate": props.get("todate"),
                "iso3": props.get("iso3"), "source": props.get("source"),
                "severitytext": severity.get("severitytext"), "iscurrent": props.get("iscurrent"),
            },
        ))
    return rows


class GdacsOutsideVisitWindow(RuntimeError):
    """Now is outside the robots.txt Visit-time window; the source is skipped, not failed."""


def in_visit_window(now=None):
    """True if a full run (6 requests, ~5 min) can start now and finish by 06:45 UTC."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    minutes = now.hour * 60 + now.minute
    return VISIT_WINDOW_START_MIN <= minutes < VISIT_WINDOW_LAST_START_MIN


def fetch_gdacs(from_date=None, to_date=None, event_types=None, sleep=time.sleep, now=None):
    if os.getenv("GDACS_RESPECT_VISIT_TIME", "true").lower() != "false" and not in_visit_window(now):
        raise GdacsOutsideVisitWindow(
            "gdacs.org robots.txt Visit-time is 04:00-06:45 UTC (11:00-13:45 Thai time); "
            "skipping GDACS for this run")
    params = {
        "alertlevel": "green;orange;red",
        "fromDate": from_date or os.getenv("GDACS_START_DATE", "2026-01-01"),
        "toDate": to_date or datetime.now(timezone.utc).date().isoformat(),
    }
    event_types = event_types or os.getenv("GDACS_EVENT_TYPES", "EQ;TC;FL;VO;DR;WF").split(";")
    session = make_session()
    fetched_at = utc_now_iso()
    rows = []
    for i, code in enumerate(event_types):
        if i:
            sleep(REQUEST_INTERVAL_SECONDS)
        payload = get_json(session, URL, params={**params, "eventlist": code})
        rows.extend(parse_gdacs(payload, fetched_at))
    return rows
