"""Parser, normalization and validation tests. Fixtures mirror the structure of real
responses (trimmed); they are test inputs only and are never loaded into the database."""
from datetime import datetime, timezone

import pytest
import requests

from src.extractors.gdacs_api import GdacsOutsideVisitWindow, fetch_gdacs, in_visit_window, parse_gdacs
from src.extractors.geonet_api import parse_geonet
from src.extractors.nasa_eonet import parse_eonet
from src.extractors.reliefweb_api import (
    ReliefWebAppnameMissing, fetch_reliefweb_api, parse_reliefweb_api,
)
from src.extractors.usgs_earthquake import parse_usgs
from src.extractors.web_scraper import check_robots, parse_phivolcs_html, parse_pht, robots_allows
from src.transformations.normalize import geometry_point, month_year_to_iso, to_utc_iso
from src.transformations.validate import validate_rows

FETCHED = "2026-10-23T05:00:00+00:00"
NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)

USGS = {"features": [{
    "id": "us7000abcd", "geometry": {"type": "Point", "coordinates": [142.1, 38.2, 10.0]},
    "properties": {"mag": 6.1, "magType": "mww", "place": "near Japan", "title": "M 6.1 - near Japan",
                   "time": 1760000000000, "url": "https://earthquake.usgs.gov/x", "alert": "green"}}]}

EONET = {"events": [{
    "id": "EONET_1", "title": "Wildfire in Australia 1033018", "closed": None,
    "categories": [{"id": "wildfires", "title": "Wildfires"}],
    "sources": [{"id": "GDACS", "url": "https://www.gdacs.org/report.aspx?eventtype=WF&eventid=1033018"}],
    "geometry": [{"date": "2026-10-20T19:00:00Z", "type": "Polygon", "magnitudeValue": 26776.0,
                  "magnitudeUnit": "hectare",
                  "coordinates": [[[136.0, -20.0], [137.0, -20.0], [137.0, -21.0], [136.0, -21.0]]]}]}]}

GDACS = {"features": [{
    "geometry": {"type": "Point", "coordinates": [-101.9, 10.5]},
    "properties": {"eventtype": "TC", "eventid": 1001341, "name": "Tropical Cyclone VANCE-26",
                   "alertlevel": "Green", "country": "México", "fromdate": "2026-10-21T15:00:00",
                   "url": {"report": "https://www.gdacs.org/report.aspx?eventid=1001341&eventtype=TC"},
                   "severitydata": {"severity": 194.4, "severityunit": "km/h"}}}]}

PHIVOLCS_HTML = r"""
<table class="MsoNormalTable"><tr><td>layout</td></tr></table>
<table class="MsoNormalTable">
 <tr><th>Date - Time<br>(Philippine Time)</th><th>Latitude<br>(ºN)</th><th>Longitude<br>(ºE)</th>
     <th>Depth<br>(km)</th><th>Mag</th><th>Location</th></tr>
 <tr><td><a href="2026_Earthquake_Information\October\2026_1023_0622_B1.html">23 October 2026 - 02:22 PM</a></td>
     <td>18.36</td><td>121.60</td><td>068</td><td>1.6</td><td>004 km N 85° W of Aparri (Cagayan)</td></tr>
 <tr><td><a href="x.html">23 October 2026 - 02:22 PM</a></td>
     <td>05.61</td><td>125.25</td><td>034</td><td>2.1</td><td>024 km S 13° E of Glan (Sarangani)</td></tr>
 <tr><td>23 October 2026 - 25:99 PM</td><td>07.86</td><td>126.47</td><td>093</td><td>3.4</td><td>Cateel</td></tr>
</table>
"""


def test_usgs_parser_maps_common_schema():
    row = parse_usgs(USGS, FETCHED)[0]
    assert row["source_event_id"] == "us7000abcd"
    assert row["event_type"] == "earthquake"
    assert (row["latitude"], row["longitude"], row["magnitude"]) == (38.2, 142.1, 6.1)
    assert row["event_time"] == "2025-10-09T08:53:20+00:00"  # epoch ms -> UTC ISO


def test_eonet_polygon_uses_centroid_and_category_mapping():
    event = {**EONET["events"][0]}
    event["geometry"] = [{"date": "2026-10-01T00:00:00Z", "type": "Point", "coordinates": [0, 0]},
                         *event["geometry"]]
    row = parse_eonet({"events": [event]}, FETCHED)[0]
    assert row["event_time"] == "2026-10-01T00:00:00+00:00"  # start = first observation
    assert row["event_type"] == "wildfire"
    assert row["latitude"] == pytest.approx(-20.5) and row["longitude"] == pytest.approx(136.5)
    assert row["magnitude_unit"] == "hectare"


def test_gdacs_naive_time_is_utc_and_id_includes_type():
    row = parse_gdacs(GDACS, FETCHED)[0]
    assert row["source_event_id"] == "TC-1001341"
    assert row["event_type"] == "storm"
    assert row["severity"] == "green"
    assert row["event_time"] == "2026-10-21T15:00:00+00:00"


def test_gdacs_one_request_per_type_60s_apart(monkeypatch):
    calls = []

    def fake_get_json(session, url, params=None, **kwargs):
        calls.append(params["eventlist"])
        return GDACS

    monkeypatch.setattr("src.extractors.gdacs_api.get_json", fake_get_json)
    sleeps = []
    in_window = datetime(2026, 10, 23, 4, 30, tzinfo=timezone.utc)
    rows = fetch_gdacs(event_types=["EQ", "TC", "FL"], sleep=sleeps.append, now=in_window)
    assert calls == ["EQ", "TC", "FL"]
    assert sleeps == [60, 60]  # never two requests within 60 s
    assert len(rows) == 3


@pytest.mark.parametrize("hhmm,inside", [((3, 59), False), ((4, 0), True), ((6, 37), True),
                                         ((6, 38), False), ((14, 0), False)])
def test_gdacs_visit_window(hhmm, inside):
    assert in_visit_window(datetime(2026, 10, 23, *hhmm, tzinfo=timezone.utc)) is inside


def test_gdacs_outside_window_is_skipped_without_requests(monkeypatch):
    monkeypatch.setattr("src.extractors.gdacs_api.get_json", lambda *a, **k: pytest.fail("no request"))
    with pytest.raises(GdacsOutsideVisitWindow):
        fetch_gdacs(now=datetime(2026, 10, 23, 7, 30, tzinfo=timezone.utc))


def test_geonet_parser_skips_deleted_and_maps_fields():
    payload = {"features": [
        {"geometry": {"type": "Point", "coordinates": [178.6, -38.4]},
         "properties": {"publicID": "2026p798113", "time": "2026-10-23T07:14:45.876Z", "depth": 26.1,
                        "magnitude": 2.3057, "mmi": -1, "locality": "45 km east of Tolaga Bay",
                        "quality": "automatic"}},
        {"geometry": {"type": "Point", "coordinates": [175.0, -40.0]},
         "properties": {"publicID": "gone", "time": "2026-10-23T07:00:00Z", "quality": "deleted"}},
    ]}
    rows = parse_geonet(payload, FETCHED)
    assert len(rows) == 1
    row = rows[0]
    assert (row["source_event_id"], row["latitude"], row["longitude"]) == ("2026p798113", -38.4, 178.6)
    assert row["event_time"] == "2026-10-23T07:14:45.876000+00:00"
    assert row["magnitude"] == 2.31 and row["event_name"] == "M 2.3 - 45 km east of Tolaga Bay"
    assert row["source_url"] == "https://www.geonet.org.nz/earthquake/2026p798113"


def test_phivolcs_parser_converts_pht_to_utc_and_builds_stable_ids():
    rows = parse_phivolcs_html(PHIVOLCS_HTML, FETCHED)
    assert len(rows) == 3
    first, second, bad = rows
    assert first["event_time"] == "2026-10-23T06:22:00+00:00"  # 14:22 PHT = 06:22 UTC
    assert first["source_event_id"] == "20261023T0622Z"
    assert second["source_event_id"] == "20261023T0622Z-2"  # same minute -> suffix
    assert (first["latitude"], first["longitude"], first["magnitude"]) == (18.36, 121.6, 1.6)
    assert first["raw_data"]["depth_km"] == 68.0
    assert first["source_url"].endswith("2026_Earthquake_Information/October/2026_1023_0622_B1.html")
    assert bad["event_time"] is None and bad["source_event_id"] == ""
    valid, quarantined, _ = validate_rows(rows, now=NOW)
    assert len(valid) == 2 and len(quarantined) == 1


def test_phivolcs_layout_change_is_detected():
    with pytest.raises(ValueError, match="table not found"):
        parse_phivolcs_html("<table><tr><td>nothing</td></tr></table>", FETCHED)


def test_parse_pht():
    assert parse_pht("01 October 2026 - 01:07 AM").isoformat() == "2026-09-30T17:07:00+00:00"
    assert parse_pht("garbage") is None



RELIEFWEB_ROBOTS = """
User-agent: *
Allow: /core/*.css$
Disallow: /core/
Disallow: /search?
Disallow: /*&page=*
Disallow: /*/rss.xml
"""


@pytest.mark.parametrize("url,allowed", [
    ("https://reliefweb.int/disasters", True),
    ("https://reliefweb.int/disasters?type=EQ&page=2", False),   # wildcard rule
    ("https://reliefweb.int/updates/rss.xml", False),
    ("https://reliefweb.int/search?q=x", False),
    ("https://reliefweb.int/core/theme.css", True),               # longer Allow beats Disallow
    ("https://reliefweb.int/core/theme.js", False),
])
def test_robots_wildcards(url, allowed):
    assert robots_allows(RELIEFWEB_ROBOTS, url) is allowed


def test_robots_specific_agent_group_overrides_star():
    txt = "User-agent: *\nDisallow:\n\nUser-agent: GlobalDisasterDashboard\nDisallow: /\n"
    assert robots_allows(txt, "https://x.org/a", "GlobalDisasterDashboard/1.0") is False
    assert robots_allows(txt, "https://x.org/a", "OtherBot/1.0") is True


def _robots_session(status, text=""):
    class FakeResponse:
        pass

    FakeResponse.status_code, FakeResponse.text = status, text

    class FakeSession:
        def get(self, *a, **k):
            return FakeResponse()

    return FakeSession()


def test_robots_disallow_blocks_scraping():
    with pytest.raises(PermissionError):
        check_robots("https://example.org/disasters",
                     session=_robots_session(200, "User-agent: *\nDisallow: /disasters"))


def test_robots_missing_means_allowed_but_server_error_means_stop():
    check_robots("https://example.org/", session=_robots_session(404))  # no exception
    with pytest.raises(PermissionError):
        check_robots("https://example.org/", session=_robots_session(503))



def test_validation_quarantines_with_reasons():
    good = parse_usgs(USGS, FETCHED)[0]
    rows = [
        good,
        {**good},  # same source id -> in-batch duplicate
        {**good, "source_event_id": "bad-lat", "latitude": 95.0},
        {**good, "source_event_id": "no-time", "event_time": None},
        {**good, "source_event_id": "no-coords", "longitude": None},
        {**good, "source_event_id": "future", "event_time": "2030-01-01T00:00:00+00:00"},
        {**good, "source_event_id": ""},
        {**good, "source_event_id": "epi", "event_type": "epidemic"},
    ]
    valid, quarantined, stats = validate_rows(rows, now=NOW)
    assert len(valid) == 1 and stats["duplicates_in_batch"] == 1
    reasons = {q["source_event_id"]: q["reason"] for q in quarantined}
    assert "latitude out of range" in reasons["bad-lat"]
    assert "missing or unparseable event_time" in reasons["no-time"]
    assert "missing coordinates" in reasons["no-coords"]
    assert "out of range" in reasons["future"]
    assert "missing source_event_id" in reasons[""]
    assert "out-of-scope" in reasons["epi"]


@pytest.mark.parametrize("value,expected", [
    ("2026-10-20T19:00:00Z", "2026-10-20T19:00:00+00:00"),
    ("2026-10-20T19:00:00+07:00", "2026-10-20T12:00:00+00:00"),
    (1760000000, "2025-10-09T08:53:20+00:00"),
    ("not a date", None),
    (None, None),
])
def test_to_utc_iso(value, expected):
    assert to_utc_iso(value) == expected


def test_month_year_and_point_helpers():
    assert month_year_to_iso("Niger: Floods - Sep 2026") == "2026-09-01T00:00:00+00:00"
    assert month_year_to_iso("No date here") is None
    assert geometry_point({"type": "Point", "coordinates": [10, 20]}) == (20.0, 10.0)
    assert geometry_point(None) == (None, None)


def _rw_item(id_, code="EQ", iso3="PAN", location=None, event="2026-10-09T00:00:00+00:00"):
    country = {"name": "Panama", "iso3": iso3}
    if location:
        country["location"] = location
    return {"id": id_, "fields": {
        "id": int(id_), "name": "Panama: Earthquake - Oct 2026", "status": "ongoing",
        "glide": "EQ-2026-000188-PAN", "date": {"event": event},
        "primary_country": country, "primary_type": {"code": code, "name": "Earthquake"},
        "url": f"https://reliefweb.int/node/{id_}"}}


def test_reliefweb_api_uses_country_centroid_when_no_location():
    row = parse_reliefweb_api({"data": [_rw_item("52720")]}, FETCHED)[0]
    assert row["source_name"] == "reliefweb_api" and row["source_event_id"] == "52720"
    assert row["event_type"] == "earthquake"
    assert row["event_time"] == "2026-10-09T00:00:00+00:00"
    assert (row["latitude"], row["longitude"]) == (9.0, -80.0)
    assert row["raw_data"]["location_precision"] == "country_centroid"


def test_reliefweb_api_prefers_api_location_and_flags_unknown_country():
    rows = parse_reliefweb_api({"data": [
        _rw_item("1", location={"lat": 8.7, "lon": -80.27}),
        _rw_item("2", iso3="XXX"),
        _rw_item("3", code="EP"),
    ]}, FETCHED)
    assert (rows[0]["latitude"], rows[0]["longitude"]) == (8.7, -80.27)
    valid, quarantined, _ = validate_rows(rows, now=NOW)
    assert [r["source_event_id"] for r in valid] == ["1"]
    reasons = {q["source_event_id"]: q["reason"] for q in quarantined}
    assert "missing coordinates" in reasons["2"] and "out-of-scope" in reasons["3"]


def test_reliefweb_api_requires_appname(monkeypatch):
    monkeypatch.delenv("RELIEFWEB_APPNAME", raising=False)
    with pytest.raises(ReliefWebAppnameMissing):
        fetch_reliefweb_api()


def test_reliefweb_api_paginates_with_appname_in_query(monkeypatch):
    pages = [{"count": 2, "totalCount": 3, "data": [_rw_item("1"), _rw_item("2")]},
             {"count": 1, "totalCount": 3, "data": [_rw_item("3")]}]
    calls = []

    class FakeResponse:
        status_code = 200
        def __init__(self, payload):
            self.payload = payload
        def raise_for_status(self):
            pass
        def json(self):
            return self.payload

    class FakeSession:
        def post(self, url, params=None, json=None, timeout=None):
            calls.append((params, json["offset"], json["limit"]))
            return FakeResponse(pages[len(calls) - 1])

    monkeypatch.setattr("src.extractors.reliefweb_api.make_session", FakeSession)
    rows = fetch_reliefweb_api(appname="my-app", sleep=lambda s: None)
    assert len(rows) == 3
    assert calls == [({"appname": "my-app"}, 0, 1000), ({"appname": "my-app"}, 2, 1000)]


def test_http_timeout_propagates(monkeypatch):
    from src.extractors import usgs_earthquake

    def boom(*a, **k):
        raise requests.Timeout("read timed out")

    monkeypatch.setattr(usgs_earthquake, "get_json", boom)
    with pytest.raises(requests.Timeout):
        usgs_earthquake.fetch_usgs()
