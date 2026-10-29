"""Shared helpers: logging, resilient HTTP, email validation."""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import requests

log = logging.getLogger("outreach")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
VALID_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
NOT_FOUND = "Not Found"


class ApiError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


def setup_logging(log_dir: str = "logs", level: int = logging.INFO) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
    root = logging.getLogger("outreach")
    root.setLevel(level)
    if root.handlers:
        return
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    fh = logging.FileHandler(Path(log_dir) / "outreach.log", encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(sh)
    root.addHandler(fh)


def request_json(method: str, url: str, *, session: requests.Session | None = None,
                 retries: int = 4, backoff: float = 1.5, timeout: int = 30, **kwargs) -> dict:
    """HTTP call returning JSON, retrying on network errors, 429 and 5xx."""
    sess = session or requests
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = sess.request(method, url, timeout=timeout, **kwargs)
        except requests.RequestException as exc:  # network problem
            last = exc
            log.warning("Network error (%s), retry %d/%d", exc, attempt + 1, retries)
            time.sleep(backoff ** attempt)
            continue
        if resp.status_code in (429, 500, 502, 503, 504):
            last = ApiError(resp.status_code, resp.text)
            log.warning("HTTP %s from %s, retry %d/%d", resp.status_code, url, attempt + 1, retries)
            time.sleep(backoff ** attempt)
            continue
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text)
        return resp.json()
    raise last if last else RuntimeError("request failed")


def valid_email(value: str | None) -> bool:
    return bool(value) and value != NOT_FOUND and bool(VALID_EMAIL_RE.match(value))


def word_count(text: str) -> int:
    return len(text.split())
