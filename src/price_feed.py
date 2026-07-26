"""Scraper for the GENERIC_HTML_TABLE price feed from ariva.de.

Portfolio Performance configures securities with, among other things, a
historical price feed of type "GENERIC_HTML_TABLE" that points to an
ariva.de page with a price table. This module fetches that page and
extracts date + closing price per row, so `Portfolio.refresh_prices` can
add more recent prices without modifying the .portfolio file itself.
"""
import datetime
import html
import ipaddress
import re
import socket
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List
from urllib.parse import urlparse

import httpx

ALLOWED_HOSTS = {"www.ariva.de", "ariva.de"}

_ROW_RE = re.compile(r'<tr[^>]*class="arrow\d?"[^>]*>(.*?)</tr>', re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def is_safe_url(url: str) -> bool:
    """SSRF protection: https only, known ariva.de host, no private/internal IPs.

    Analogous to `is_safe_url` in DividendenTracker/app/sync.py, plus a host
    allowlist here since this URL isn't maintained by an admin but comes
    unmodified from the .portfolio file.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return False
        hostname = parsed.hostname
        if not hostname or hostname.lower() not in ALLOWED_HOSTS:
            return False
        addr_infos = socket.getaddrinfo(hostname, None)
        for info in addr_infos:
            ip_str = info[4][0]
            if "%" in ip_str:
                ip_str = ip_str.split("%")[0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def _strip_tags(cell_html: str) -> str:
    return html.unescape(_TAG_RE.sub("", cell_html)).strip()


def _parse_date(text: str) -> datetime.date:
    # ariva returns dates as "dd.mm.yy" (two-digit year, 20xx).
    day, month, year = text.split(".")
    return datetime.date(2000 + int(year), int(month), int(day))


def _parse_amount(text: str) -> Decimal:
    # e.g. "101,14 €" -> 101.14
    cleaned = text.replace("€", "").strip()
    cleaned = cleaned.replace(".", "").replace(",", ".")
    return Decimal(cleaned)


def fetch_ariva_prices(url: str) -> List[Dict[str, Any]]:
    """Fetches the historical price table of an ariva.de page.

    Returns a list of {"date": date, "close": Decimal}, most recent first
    (as shown on the page). Raises ValueError/httpx exceptions on network or
    parse errors.
    """
    if not is_safe_url(url):
        raise ValueError(f"URL not trusted or not allowed (SSRF protection): {url}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    with httpx.Client(follow_redirects=False, timeout=10.0) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        html_text = response.text

    marker = html_text.find('class="ql_date">Datum')
    if marker == -1:
        raise ValueError("Price table not found on the page (layout changed?).")
    table_start = html_text.rfind("<table", 0, marker)
    table_end = html_text.find("</table>", marker)
    if table_start == -1 or table_end == -1:
        raise ValueError("Price table not found on the page (layout changed?).")
    table_html = html_text[table_start:table_end + len("</table>")]

    results: List[Dict[str, Any]] = []
    for row_html in _ROW_RE.findall(table_html):
        cells = [_strip_tags(c) for c in _CELL_RE.findall(row_html)]
        # Columns: date, open, high, low, close, ...
        if len(cells) < 5:
            continue
        try:
            date = _parse_date(cells[0])
            close = _parse_amount(cells[4])
        except (ValueError, InvalidOperation, IndexError):
            continue
        results.append({"date": date, "close": close})
    return results
