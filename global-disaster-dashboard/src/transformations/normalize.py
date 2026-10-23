"""Helpers that turn source-specific values into the common schema."""
from datetime import datetime, timezone
import re

# Common schema shared by every source (see sql/schema.sql).
COMMON_FIELDS = (
    "source_name", "source_event_id", "event_type", "event_name", "event_time",
    "latitude", "longitude", "magnitude", "magnitude_unit", "severity", "country",
    "source_url", "fetched_at", "raw_data",
)

# Natural-hazard types kept in the dashboard. Anything else is quarantined as out of scope.
NATURAL_EVENT_TYPES = {
    "earthquake", "storm", "wildfire", "flood", "volcano", "drought", "landslide",
    "tsunami", "cold_wave", "heat_wave", "sea_lake_ice", "snow", "dust_haze",
    "temperature_extreme", "fire", "other_natural",
}

# GDACS and ReliefWeb share GLIDE-style two-letter hazard codes.
HAZARD_CODE_MAP = {
    "EQ": "earthquake", "TC": "storm", "ST": "storm", "EC": "storm", "SS": "storm",
    "FL": "flood", "FF": "flood", "VO": "volcano", "DR": "drought", "WF": "wildfire",
    "FR": "fire", "LS": "landslide", "MS": "landslide", "AV": "landslide",
    "TS": "tsunami", "CW": "cold_wave", "HT": "heat_wave", "IN": "other_natural",
    # Not natural hazards -> out of scope.
    "EP": "epidemic", "AC": "technological", "OT": "other",
}

EONET_CATEGORY_MAP = {
    "wildfires": "wildfire", "severeStorms": "storm", "floods": "flood",
    "volcanoes": "volcano", "earthquakes": "earthquake", "drought": "drought",
    "landslides": "landslide", "seaLakeIce": "sea_lake_ice", "snow": "snow",
    "dustHaze": "dust_haze", "tempExtremes": "temperature_extreme",
    "waterColor": "water_color", "manmade": "manmade",
}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def to_utc_iso(value):
    """Parse epoch seconds/milliseconds or ISO-8601 text into an ISO UTC string.

    Naive timestamps are treated as UTC (GDACS and EONET publish UTC). Returns None
    when the value cannot be parsed so validation can quarantine the record.
    """
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if abs(value) > 1e11 else value
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except (ValueError, OverflowError, OSError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def to_float(value):
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def geometry_point(geometry):
    """Return (lat, lon) for a GeoJSON Point or the vertex-average centroid of a Polygon."""
    geometry = geometry or {}
    coords = geometry.get("coordinates")
    if not coords:
        return None, None
    if geometry.get("type") == "Point":
        return (to_float(coords[1]), to_float(coords[0])) if len(coords) > 1 else (None, None)
    if geometry.get("type") in ("Polygon", "MultiPolygon"):
        points = []

        def walk(node):
            if node and isinstance(node[0], (int, float)):
                points.append(node)
            else:
                for child in node:
                    walk(child)

        walk(coords)
        if not points:
            return None, None
        return (sum(p[1] for p in points) / len(points), sum(p[0] for p in points) / len(points))
    return None, None


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def month_year_to_iso(text):
    """'Panama: Earthquake - Oct 2026' -> '2026-10-01T00:00:00+00:00' (month precision)."""
    match = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{4})\s*$", text or "")
    if not match or match.group(1).lower() not in _MONTHS:
        return None
    month, year = _MONTHS[match.group(1).lower()], int(match.group(2))
    return datetime(year, month, 1, tzinfo=timezone.utc).isoformat()


def make_row(**fields):
    row = {field: None for field in COMMON_FIELDS}
    row.update(fields)
    row["source_event_id"] = str(row["source_event_id"] or "").strip()
    row["raw_data"] = row["raw_data"] or {}
    return row
