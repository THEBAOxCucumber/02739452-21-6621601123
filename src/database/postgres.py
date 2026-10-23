"""PostgreSQL access for the ETL: UPSERT, quarantine, cross-source de-duplication, quality checks."""
import json
import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import execute_values

# Lower number = higher priority when the same real-world event comes from several sources.
SOURCE_PRIORITY = {"usgs": 1, "gdacs": 2, "geonet": 3, "phivolcs_html": 4, "nasa_eonet": 5,
                   "reliefweb_api": 6}
MIN_CANONICAL_EVENTS = 100

# Earthquake match rules (GDACS/PHIVOLCS vs USGS). 120 s also covers PHIVOLCS times,
# which are published to the minute only.
EQ_MAX_SECONDS = 120
EQ_MAX_KM = 100
EQ_MAX_MAG_DIFF = 0.5


def connection_params():
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "disaster_db")),
        "user": os.getenv("DB_USER", os.getenv("POSTGRES_USER", "disaster_user")),
        "password": os.getenv("DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "")),
    }


@contextmanager
def get_connection():
    conn = psycopg2.connect(**connection_params())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


UPSERT_EVENTS_SQL = """
INSERT INTO disaster_events
  (source_name, source_event_id, event_type, event_name, event_time, latitude, longitude,
   magnitude, magnitude_unit, severity, country, source_url, raw_data, fetched_at)
VALUES %s
ON CONFLICT (source_name, source_event_id) DO UPDATE SET
  event_type = EXCLUDED.event_type, event_name = EXCLUDED.event_name,
  event_time = EXCLUDED.event_time, latitude = EXCLUDED.latitude,
  longitude = EXCLUDED.longitude, magnitude = EXCLUDED.magnitude,
  magnitude_unit = EXCLUDED.magnitude_unit, severity = EXCLUDED.severity,
  country = EXCLUDED.country, source_url = EXCLUDED.source_url,
  raw_data = EXCLUDED.raw_data, fetched_at = EXCLUDED.fetched_at, updated_at = NOW()
RETURNING (xmax = 0) AS inserted
"""


def upsert_events(rows, conn=None):
    """UPSERT validated rows. Returns {'inserted': n, 'updated': m}."""
    if not rows:
        return {"inserted": 0, "updated": 0}
    values = [(
        r["source_name"], r["source_event_id"], r["event_type"], r.get("event_name"),
        r["event_time"], r["latitude"], r["longitude"], r.get("magnitude"),
        r.get("magnitude_unit"), r.get("severity"), r.get("country"), r.get("source_url"),
        json.dumps(r.get("raw_data") or {}, default=str), r["fetched_at"],
    ) for r in rows]
    with _maybe_connection(conn) as c, c.cursor() as cur:
        flags = execute_values(cur, UPSERT_EVENTS_SQL, values, page_size=500, fetch=True)
    inserted = sum(1 for (flag,) in flags if flag)
    return {"inserted": inserted, "updated": len(rows) - inserted}


def upsert_quarantine(rows, dag_run_id=None, conn=None):
    if not rows:
        return 0
    # ON CONFLICT cannot touch the same row twice in one statement, so collapse repeats
    # of the same (source, id, reason) first (e.g. one event returned on two API pages).
    unique = {}
    for r in rows:
        key = (r.get("source_name") or "unknown", r.get("source_event_id") or "", r["reason"])
        unique[key] = json.dumps({k: v for k, v in r.items() if k != "reason"}, default=str)
    values = [(*key, raw, dag_run_id) for key, raw in unique.items()]
    with _maybe_connection(conn) as c, c.cursor() as cur:
        execute_values(cur, """
            INSERT INTO data_quarantine (source_name, source_event_id, reason, raw_data, dag_run_id)
            VALUES %s
            ON CONFLICT (source_name, source_event_id, reason) DO UPDATE SET
              raw_data = EXCLUDED.raw_data, dag_run_id = EXCLUDED.dag_run_id, last_seen_at = NOW()
        """, values)
    return len(values)


def resolve_quarantine(source_name, valid_ids, conn=None):
    """Delete quarantine entries for events of this source that now pass validation."""
    if not valid_ids:
        return 0
    with _maybe_connection(conn) as c, c.cursor() as cur:
        cur.execute("DELETE FROM data_quarantine WHERE source_name = %s AND source_event_id = ANY(%s)",
                    (source_name, list(valid_ids)))
        return cur.rowcount


HAVERSINE_KM = """
  2 * 6371 * ASIN(SQRT(
    POWER(SIN(RADIANS({b}.latitude - {a}.latitude) / 2), 2) +
    COS(RADIANS({a}.latitude)) * COS(RADIANS({b}.latitude)) *
    POWER(SIN(RADIANS({b}.longitude - {a}.longitude) / 2), 2)))
"""


def eq_matches_usgs_sql(source, rule, max_mag_diff):
    """Flag `source` earthquakes within EQ_MAX_SECONDS and EQ_MAX_KM (and optionally
    max_mag_diff) of a USGS earthquake as duplicates of it; the closest match in time wins."""
    mag_clause = ("" if max_mag_diff is None else
                  f"AND (s2.magnitude IS NULL OR u.magnitude IS NULL "
                  f"OR ABS(s2.magnitude - u.magnitude) <= {max_mag_diff})")
    return f"""
        UPDATE disaster_events s
        SET duplicate_of = m.usgs_id, duplicate_rule = '{rule}'
        FROM (
          SELECT s2.id AS source_id, best.id AS usgs_id
          FROM disaster_events s2
          CROSS JOIN LATERAL (
            SELECT u.id FROM disaster_events u
            WHERE u.source_name = 'usgs' AND u.event_type = 'earthquake'
              AND u.event_time BETWEEN s2.event_time - INTERVAL '{EQ_MAX_SECONDS} seconds'
                                   AND s2.event_time + INTERVAL '{EQ_MAX_SECONDS} seconds'
              {mag_clause}
              AND {HAVERSINE_KM.format(a='s2', b='u')} <= {EQ_MAX_KM}
            ORDER BY ABS(EXTRACT(EPOCH FROM (u.event_time - s2.event_time)))
            LIMIT 1
          ) best
          WHERE s2.source_name = '{source}' AND s2.event_type = 'earthquake'
        ) m
        WHERE s.id = m.source_id
    """


DEDUP_STEPS = [
    ("reset", """
        UPDATE disaster_events SET duplicate_of = NULL, duplicate_rule = NULL
        WHERE duplicate_of IS NOT NULL
    """),
    # Rule 1: EONET republishes GDACS alerts and links the GDACS report
    # (report.aspx?eventtype=WF&eventid=123) -> same event as gdacs 'WF-123'.
    ("eonet_cites_gdacs", """
        UPDATE disaster_events e
        SET duplicate_of = g.id, duplicate_rule = 'eonet_cites_gdacs'
        FROM disaster_events g
        WHERE e.source_name = 'nasa_eonet' AND g.source_name = 'gdacs'
          AND e.source_url ~* 'gdacs\\.org/report\\.aspx'
          AND g.source_event_id =
              UPPER(SUBSTRING(e.source_url FROM '(?i)eventtype=([A-Za-z]+)')) || '-' ||
              SUBSTRING(e.source_url FROM '(?i)eventid=([0-9]+)')
    """),
    # Rule 2: GDACS earthquake matching a USGS earthquake -> keep USGS.
    ("gdacs_eq_matches_usgs", eq_matches_usgs_sql("gdacs", "gdacs_eq_matches_usgs", EQ_MAX_MAG_DIFF)),
    # Rule 3: PHIVOLCS earthquake matching a USGS earthquake -> keep USGS. No magnitude
    # condition: PHIVOLCS and USGS use different magnitude scales for the same quake.
    ("phivolcs_eq_matches_usgs", eq_matches_usgs_sql("phivolcs_html", "phivolcs_eq_matches_usgs", None)),
    # Rule 4: same for GeoNet (New Zealand).
    ("geonet_eq_matches_usgs", eq_matches_usgs_sql("geonet", "geonet_eq_matches_usgs", None)),
    # Collapse chains (EONET -> GDACS -> USGS) so duplicate_of always points at a canonical row.
    ("collapse_chains", """
        UPDATE disaster_events d
        SET duplicate_of = p.duplicate_of
        FROM disaster_events p
        WHERE d.duplicate_of = p.id AND p.duplicate_of IS NOT NULL
    """),
]


def mark_cross_source_duplicates(conn=None):
    """Re-compute duplicate_of for all rows. Idempotent. Returns rows flagged per rule."""
    flagged = {}
    with _maybe_connection(conn) as c, c.cursor() as cur:
        for name, sql in DEDUP_STEPS:
            cur.execute(sql)
            if name != "reset":
                flagged[name] = cur.rowcount
    return flagged


QUALITY_CHECKS = [
    # (name, SQL returning one value, predicate, expectation text)
    ("canonical_events_at_least_100",
     "SELECT COUNT(*) FROM disaster_events WHERE duplicate_of IS NULL",
     lambda v: v >= MIN_CANONICAL_EVENTS, f">= {MIN_CANONICAL_EVENTS} unique validated events"),
    ("no_duplicate_source_ids",
     "SELECT COUNT(*) FROM (SELECT 1 FROM disaster_events GROUP BY source_name, source_event_id HAVING COUNT(*) > 1) d",
     lambda v: v == 0, "0 duplicated (source_name, source_event_id)"),
    ("coordinates_in_range",
     "SELECT COUNT(*) FROM disaster_events WHERE latitude NOT BETWEEN -90 AND 90 OR longitude NOT BETWEEN -180 AND 180",
     lambda v: v == 0, "0 rows with out-of-range coordinates"),
    ("no_future_events",
     "SELECT COUNT(*) FROM disaster_events WHERE event_time > NOW() + INTERVAL '1 day'",
     lambda v: v == 0, "0 events dated in the future"),
    ("sources_with_data",
     "SELECT COUNT(DISTINCT source_name) FROM disaster_events",
     lambda v: v >= 3, ">= 3 sources present"),
    ("duplicate_pointers_canonical",
     "SELECT COUNT(*) FROM disaster_events d JOIN disaster_events p ON d.duplicate_of = p.id WHERE p.duplicate_of IS NOT NULL",
     lambda v: v == 0, "duplicate_of never points at another duplicate"),
]


def run_quality_checks(dag_run_id, conn=None):
    results = []
    with _maybe_connection(conn) as c, c.cursor() as cur:
        for name, sql, predicate, expectation in QUALITY_CHECKS:
            cur.execute(sql)
            value = cur.fetchone()[0]
            passed = bool(predicate(value))
            results.append({"check_name": name, "passed": passed,
                            "observed_value": str(value), "expectation": expectation})
            cur.execute("""
                INSERT INTO data_quality_results (dag_run_id, check_name, passed, observed_value, expectation)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (dag_run_id, check_name) DO UPDATE SET
                  passed = EXCLUDED.passed, observed_value = EXCLUDED.observed_value, checked_at = NOW()
            """, (dag_run_id, name, passed, str(value), expectation))
    return results


def record_pipeline_runs(entries, conn=None):
    with _maybe_connection(conn) as c, c.cursor() as cur:
        for e in entries:
            cur.execute("""
                INSERT INTO pipeline_runs (dag_id, dag_run_id, source_name, status, records_extracted,
                  records_loaded, records_quarantined, message, started_at, finished_at)
                VALUES (%(dag_id)s, %(dag_run_id)s, %(source_name)s, %(status)s, %(records_extracted)s,
                  %(records_loaded)s, %(records_quarantined)s, %(message)s, %(started_at)s, NOW())
                ON CONFLICT (dag_run_id, source_name) DO UPDATE SET
                  status = EXCLUDED.status, records_extracted = EXCLUDED.records_extracted,
                  records_loaded = EXCLUDED.records_loaded,
                  records_quarantined = EXCLUDED.records_quarantined,
                  message = EXCLUDED.message, finished_at = NOW()
            """, e)


@contextmanager
def _maybe_connection(conn):
    if conn is not None:
        yield conn
    else:
        with get_connection() as new_conn:
            yield new_conn
