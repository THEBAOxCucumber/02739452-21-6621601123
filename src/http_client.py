"""Shared HTTP session: timeouts, retries on 429/5xx (honours Retry-After), polite User-Agent."""
import os

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = os.getenv(
    "SCRAPER_USER_AGENT",
    "GlobalDisasterDashboard/1.0 (student educational project; non-commercial)",
)
DEFAULT_TIMEOUT = (10, 60)  # (connect, read) seconds


def make_session(total_retries=3, backoff=2.0):
    retry = Retry(
        total=total_retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),  # POST only for read-only search APIs (ReliefWeb)
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_json(session, url, params=None, timeout=DEFAULT_TIMEOUT):
    response = session.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()
