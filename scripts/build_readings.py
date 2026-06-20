#!/usr/bin/env python3
"""
Build daily-readings.xml for the Catholic Prayer Library app.

The USCCB RSS feed only contains a *link* to each day's readings, never the
reading text itself. So we fetch the actual daily readings PAGE, extract the
reading blocks, and embed them as escaped HTML inside a single-item RSS feed
that the app already knows how to parse and sanitize.

This script is intentionally tolerant:
  * If the network/USCCB blocks us, we still write a valid feed with a
    fallback message and <source-status>fallback</source-status>, so the
    committed file is never an invalid or empty document.
  * The app reads ./daily-readings.xml first (same-origin on GitHub Pages),
    so a good run here is what users actually see.
"""

from __future__ import annotations
import html
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime

# US Eastern: USCCB's day boundary. ET is UTC-5 (standard) / UTC-4 (daylight).
# A fixed -4 is close enough to pick the right page around the 05:15 UTC run;
# if you want exact DST handling, swap in zoneinfo (Python 3.9+):
#   from zoneinfo import ZoneInfo; now = datetime.now(ZoneInfo("America/New_York"))
try:
    from zoneinfo import ZoneInfo
    NOW = datetime.now(ZoneInfo("America/New_York"))
except Exception:  # pragma: no cover - zoneinfo always present on 3.12
    NOW = datetime.now(timezone(timedelta(hours=-4)))

DATE_CODE = NOW.strftime("%m%d%y")              # e.g. 062026 -> matches the app
PAGE_URL = f"https://bible.usccb.org/bible/readings/{DATE_CODE}.cfm"
PUB_DATE = format_datetime(NOW)
OUT_PATH = "daily-readings.xml"

USER_AGENT = "Mozilla/5.0 (compatible; CatholicPrayerLibrary/1.0; daily readings cache)"


def fetch(url: str, timeout: int = 60) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="ignore")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"::warning::Fetch failed for {url}: {e}", file=sys.stderr)
        return None


def extract_readings(page_html: str) -> str:
    """
    Pull the reading blocks out of the USCCB daily page.

    USCCB wraps each reading in containers with classes like 'b-verse' /
    'innerblock'. Site markup changes occasionally, so we try a few strategies
    and fall back to BeautifulSoup if available. Returns inner HTML (a string)
    or '' if nothing usable was found.
    """
    # Prefer BeautifulSoup when present; it survives messy markup far better.
    try:
        from bs4 import BeautifulSoup  # type: ignore
        soup = BeautifulSoup(page_html, "html.parser")
        blocks = soup.select("div.b-verse")
        if not blocks:
            # Newer layouts sometimes use these wrappers:
            blocks = soup.select("div.innerblock, div.content-body, div.readings")
        parts = []
        for b in blocks:
            txt = b.decode_contents().strip()
            if txt:
                parts.append(txt)
        if parts:
            return "\n".join(parts)
    except ImportError:
        pass

    # Regex fallback (no external deps). Greedy-but-bounded grab of b-verse divs.
    import re
    matches = re.findall(
        r'<div[^>]*class="[^"]*b-verse[^"]*"[^>]*>(.*?)</div>\s*(?=<div|</div>|$)',
        page_html,
        re.S | re.I,
    )
    parts = [m.strip() for m in matches if m.strip()]
    return "\n".join(parts)


def build_feed(body_html: str, status: str) -> str:
    # Everything inside <description> must be escaped so the RSS itself stays
    # well-formed; the app un-escapes and sanitizes it on render.
    escaped_body = html.escape(body_html)
    return f"""<?xml version='1.0' encoding='utf-8'?>
<rss version="2.0">
  <channel>
    <title>Catholic Prayer Library Daily Mass Readings</title>
    <link>{PAGE_URL}</link>
    <description>Current Daily Mass readings for the Catholic Prayer Library</description>
    <item>
      <title>Daily Mass Readings</title>
      <link>{PAGE_URL}</link>
      <guid isPermaLink="true">{PAGE_URL}</guid>
      <pubDate>{PUB_DATE}</pubDate>
      <description>{escaped_body}</description>
      <source-status>{status}</source-status>
    </item>
  </channel>
</rss>
"""


def main() -> int:
    page = fetch(PAGE_URL)
    body = extract_readings(page) if page else ""

    if body:
        status = "ok"
        print(f"Extracted {len(body)} chars of reading HTML from {PAGE_URL}")
    else:
        status = "fallback"
        link = html.escape(PAGE_URL)
        body = (
            "<h2>Today\u2019s Readings</h2>"
            "<p>The official reading text could not be refreshed automatically "
            "on this run.</p>"
            f"<p><a href=\"{link}\">Open today\u2019s readings on the USCCB "
            "website</a>.</p>"
        )
        print("::warning::Falling back; no readings extracted.", file=sys.stderr)

    feed = build_feed(body, status)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(feed)
    print(f"Wrote {OUT_PATH} (status={status})")
    # Always exit 0: a fallback feed is still a valid, committable file.
    return 0


if __name__ == "__main__":
    sys.exit(main())
