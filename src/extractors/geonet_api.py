"""GeoNet Quake API (GNS Science, New Zealand). Docs: https://api.geonet.org.nz/
Data licence: CC BY 4.0 (attribute GeoNet). No key needed; robots.txt allows /quake.
"""
from src.http_client import get_json, make_session
from src.transformations.normalize import make_row, to_float, to_utc_iso, utc_now_iso

SOURCE_NAME = "geonet"
URL = "https://api.geonet.org.nz/quake"
HEADERS = {"Accept": "application/vnd.geo+json;version=2"}


def parse_geonet(payload, fetched_at):
    rows = []
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        if props.get("quality") == "deleted":  # retracted by GeoNet
            continue
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        public_id = props.get("publicID")
        mag = to_float(props.get("magnitude"))
        rows.append(make_row(
            source_name=SOURCE_NAME,
            source_event_id=public_id,
            event_type="earthquake",
            event_name=f"M {mag:.1f} - {props.get('locality')}" if mag is not None else props.get("locality"),
            event_time=to_utc_iso(props.get("time")),
            latitude=to_float(coords[1]) if len(coords) > 1 else None,
            longitude=to_float(coords[0]) if coords else None,
            magnitude=round(mag, 2) if mag is not None else None,
            magnitude_unit="M",
            country="New Zealand",
            source_url=f"https://www.geonet.org.nz/earthquake/{public_id}" if public_id else None,
            fetched_at=fetched_at,
            raw_data={k: props.get(k) for k in ("publicID", "time", "depth", "magnitude", "mmi",
                                                 "locality", "quality")},
        ))
    return rows


def fetch_geonet():
    session = make_session()
    session.headers.update(HEADERS)
    payload = get_json(session, URL, params={"MMI": -1})  # -1 = all intensities
    return parse_geonet(payload, utc_now_iso())
