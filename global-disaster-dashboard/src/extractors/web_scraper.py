"""Web scraping (requests + BeautifulSoup, no Selenium): PHIVOLCS latest earthquake list.

https://earthquake.phivolcs.dost.gov.ph/ (Philippine Institute of Volcanology and Seismology)
is one server-rendered HTML page holding every earthquake of the current month in a table:

  Date - Time (Philippine Time) | Latitude (ºN) | Longitude (ºE) | Depth (km) | Mag | Location

The site has no robots.txt (HTTP 404), which RFC 9309 treats as "no restrictions"; robots.txt
is still checked on every run. One request per DAG run (the whole month is on one page).
Only public seismic parameters are kept — no personal data.
"""
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.http_client import USER_AGENT, make_session
from src.transformations.normalize import make_row, to_float, utc_now_iso

SOURCE_NAME = "phivolcs_html"
LIST_URL = "https://earthquake.phivolcs.dost.gov.ph/"
PHILIPPINE_TIME = timezone(timedelta(hours=8))  # PHT, no daylight saving
PAGE_TIMEOUT = (10, 120)  # the page is ~2.5 MB
EXPECTED_HEADER = ["date - time", "latitude", "longitude", "depth", "mag", "location"]


# ---------- robots.txt ----------

def _rule_regex(path_pattern):
    """robots.txt path pattern -> regex ('*' = any chars, trailing '$' = end of URL)."""
    anchored = path_pattern.endswith("$")
    body = re.escape(path_pattern.rstrip("$")).replace(r"\*", ".*")
    return re.compile(body + ("$" if anchored else ""))


def robots_allows(robots_txt, url, user_agent=USER_AGENT):
    """RFC 9309 matching with wildcards (urllib.robotparser ignores '*' and '$').

    Uses the group for our user-agent if present, else '*'. The longest matching rule wins;
    on a tie Allow wins. Matching is done on path + query string.
    """
    groups, agents, rules, in_rules = [], [], [], False
    for raw in robots_txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if in_rules:
                groups.append((agents, rules))
                agents, rules, in_rules = [], [], False
            agents.append(value.lower())
        elif key in ("allow", "disallow"):
            in_rules = True
            if value:
                rules.append((key == "allow", value))
    groups.append((agents, rules))

    token = user_agent.split("/")[0].lower()
    chosen = next((r for a, r in groups if any(x != "*" and x in token for x in a)), None)
    if chosen is None:
        chosen = next((r for a, r in groups if "*" in a), [])

    parsed = urlparse(url)
    target = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    best = None  # (pattern length, allow)
    for allow, pattern in chosen:
        if _rule_regex(pattern).match(target):
            candidate = (len(pattern), allow)
            if best is None or candidate > best:
                best = candidate
    return True if best is None else best[1]


def check_robots(url, user_agent=USER_AGENT, session=None):
    """Raise PermissionError if robots.txt forbids the URL.

    RFC 9309: robots.txt answering 4xx (e.g. 404, none published) means no restrictions;
    5xx or no answer means "assume complete disallow".
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    session = session or make_session(total_retries=1)
    response = session.get(robots_url, timeout=(10, 30))
    if 400 <= response.status_code < 500:
        return
    if response.status_code >= 500:
        raise PermissionError(f"{robots_url} unavailable (HTTP {response.status_code}); not scraping")
    if not robots_allows(response.text, url, user_agent):
        raise PermissionError(f"robots.txt at {robots_url} disallows {url}")


# ---------- HTML parsing ----------

def parse_pht(text):
    """'23 October 2026 - 02:22 PM' (Philippine Time) -> aware UTC datetime, or None."""
    cleaned = re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()
    try:
        local = datetime.strptime(cleaned, "%d %B %Y - %I:%M %p")
    except ValueError:
        return None
    return local.replace(tzinfo=PHILIPPINE_TIME).astimezone(timezone.utc)


def _cells(tr):
    return [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip() for c in tr.find_all(["td", "th"])]


def find_event_table(soup):
    """The earthquake table is the one whose header matches EXPECTED_HEADER."""
    for table in soup.find_all("table"):
        for tr in table.find_all("tr")[:3]:
            header = [c.lower() for c in _cells(tr)]
            if len(header) >= 6 and all(h.startswith(e) for h, e in zip(header, EXPECTED_HEADER)):
                return table
    raise ValueError("PHIVOLCS earthquake table not found — page layout may have changed")


def parse_phivolcs_html(html, fetched_at, page_url=LIST_URL):
    soup = BeautifulSoup(html, "html.parser")
    rows, seen = [], {}
    for tr in find_event_table(soup).find_all("tr"):
        cells = _cells(tr)
        if len(cells) < 6 or cells[0].lower().startswith("date"):
            continue
        when = parse_pht(cells[0])
        lat, lon, depth, mag = (to_float(v) for v in cells[1:5])
        location = cells[5]
        link = tr.find("a", href=True)
        # Stable id = UTC minute of origin (bulletin file names change B1 -> B2F as the
        # solution is revised, so they are not used as ids). Same-minute quakes get a suffix.
        base_id = when.strftime("%Y%m%dT%H%MZ") if when else ""
        seen[base_id] = seen.get(base_id, 0) + 1
        event_id = base_id if seen[base_id] == 1 or not base_id else f"{base_id}-{seen[base_id]}"
        rows.append(make_row(
            source_name=SOURCE_NAME,
            source_event_id=event_id,
            event_type="earthquake",
            event_name=f"M {cells[4]} - {location}" if location else None,
            event_time=when.isoformat() if when else None,
            latitude=lat,
            longitude=lon,
            magnitude=mag,
            magnitude_unit="phivolcs",
            country="Philippines",
            source_url=urljoin(page_url, link["href"].replace("\\", "/")) if link else page_url,
            fetched_at=fetched_at,
            raw_data={
                "datetime_pht": cells[0], "latitude": cells[1], "longitude": cells[2],
                "depth_km": to_float(cells[3]), "magnitude": cells[4], "location": location,
                "scraped_from": page_url,
            },
        ))
    return rows


def fetch_phivolcs_html():
    session = make_session()
    check_robots(LIST_URL, session=session)
    response = session.get(LIST_URL, timeout=PAGE_TIMEOUT)
    response.raise_for_status()
    return parse_phivolcs_html(response.content, utc_now_iso(), response.url)
