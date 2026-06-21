#!/usr/bin/env python3
"""
Build daily-readings.xml for the Catholic Prayer Library app.

The USCCB RSS feed only contains a *link* to each day's readings, never the
reading text. So we fetch the actual daily readings PAGE for the correct
US-Eastern date, extract the reading blocks, and embed them as escaped HTML
inside a single-item RSS feed that the app already knows how to parse and
sanitize.

Why US Eastern: the liturgical "today" rolls over at Eastern midnight. Using
the runner's UTC clock would fetch the wrong day's page during the late-evening
/ early-morning Eastern window.

Resilience: if the network/USCCB blocks us, we still write a valid feed with a
fallback message and <source-status>fallback</source-status>, so the committed
file is never invalid or empty -- and the job exits 0 so it can still commit.
"""

from __future__ import annotations
import html
import sys
import urllib.request
import urllib.error
from datetime import datetime
from email.utils import format_datetime

# Anchor everything to US Eastern so the date code matches USCCB's day.
try:
    from zoneinfo import ZoneInfo
    NOW = datetime.now(ZoneInfo("America/New_York"))
except Exception:  # pragma: no cover - zoneinfo ships with 3.9+
    from datetime import timezone, timedelta
    NOW = datetime.now(timezone(timedelta(hours=-4)))  # EDT approximation

DATE_CODE = NOW.strftime("%m%d%y")  # e.g. 062126 -> matches the app's massDateCode
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
    """Pull the reading blocks out of the USCCB daily page."""
    try:
        from bs4 import BeautifulSoup  # type: ignore
        soup = BeautifulSoup(page_html, "html.parser")
        blocks = soup.select("div.b-verse")
        if not blocks:
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

    import re
    matches = re.findall(
        r'<div[^>]*class="[^"]*b-verse[^"]*"[^>]*>(.*?)</div>\s*(?=<div|</div>|$)',
        page_html,
        re.S | re.I,
    )
    parts = [m.strip() for m in matches if m.strip()]
    return "\n".join(parts)


def build_feed(body_html: str, status: str) -> str:
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

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(build_feed(body, status))
    print(f"Wrote {OUT_PATH} (status={status}) for date {DATE_CODE}")
    return 0  # Always succeed: a fallback feed is still committable.


if __name__ == "__main__":
    sys.exit(main())
