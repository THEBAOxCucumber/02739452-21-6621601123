"""Row-level validation and in-batch de-duplication.

Every rejected row is returned with a reason so it can be written to the quarantine table.
"""
from datetime import datetime, timedelta, timezone

from src.transformations.normalize import NATURAL_EVENT_TYPES

EARLIEST_EVENT = datetime(1900, 1, 1, tzinfo=timezone.utc)
FUTURE_TOLERANCE = timedelta(days=1)


def validation_errors(row, now=None):
    now = now or datetime.now(timezone.utc)
    errors = []
    if not row.get("source_name"):
        errors.append("missing source_name")
    if not row.get("source_event_id"):
        errors.append("missing source_event_id")

    event_type = row.get("event_type")
    if not event_type or event_type == "unknown":
        errors.append("missing event_type")
    elif event_type not in NATURAL_EVENT_TYPES:
        errors.append(f"out-of-scope event_type '{event_type}' (not a natural hazard)")

    event_time = row.get("event_time")
    if not event_time:
        errors.append("missing or unparseable event_time")
    else:
        try:
            parsed = datetime.fromisoformat(event_time)
            if parsed.tzinfo is None:
                errors.append("event_time has no timezone")
            elif parsed < EARLIEST_EVENT or parsed > now + FUTURE_TOLERANCE:
                errors.append(f"event_time out of range: {event_time}")
        except (TypeError, ValueError):
            errors.append(f"invalid event_time: {event_time}")

    lat, lon = row.get("latitude"), row.get("longitude")
    if lat is None or lon is None:
        errors.append("missing coordinates")
    else:
        if not isinstance(lat, (int, float)) or not -90 <= lat <= 90:
            errors.append(f"latitude out of range: {lat}")
        if not isinstance(lon, (int, float)) or not -180 <= lon <= 180:
            errors.append(f"longitude out of range: {lon}")

    magnitude = row.get("magnitude")
    if magnitude is not None and not isinstance(magnitude, (int, float)):
        errors.append(f"non-numeric magnitude: {magnitude}")
    return errors


def validate_rows(rows, now=None):
    """Split rows into (valid, quarantined, stats).

    Duplicates of the same (source_name, source_event_id) inside one batch are dropped;
    the last occurrence wins, matching what the UPSERT would keep.
    """
    valid, quarantined = {}, []
    duplicates_in_batch = 0
    for row in rows:
        errors = validation_errors(row, now)
        if errors:
            quarantined.append({**row, "reason": "; ".join(errors)})
            continue
        key = (row["source_name"], row["source_event_id"])
        if key in valid:
            duplicates_in_batch += 1
        valid[key] = row
    stats = {
        "extracted": len(rows),
        "valid": len(valid),
        "quarantined": len(quarantined),
        "duplicates_in_batch": duplicates_in_batch,
    }
    return list(valid.values()), quarantined, stats
