"""OLX.pt watcher — polls a set of searches and Telegrams every new listing.

What to hunt lives in hunt.py (the WATCH dict + a classify function). This
file is the engine and should not need editing to change target.

Fetching degrades through three tiers per run, stopping at the first that
answers:
  1. OLX's JSON API over plain HTTP     (cheap: ~25 MB, <1 s)
  2. the search page's embedded state   (different protection path)
  3. a local Playwright browser         (~670 MB, ~5 s — the only tier that
                                         survives a throttled IP)
OLX refuses datacenter IPs outright, so this runs locally via launchd, not
in the cloud. See README.

Every query is sorted newest-first. That matters: OLX returns at most ~40
results per query and ranks by relevance by default, so a fresh listing
can land at position 90 and never be seen. Sorted by date it's always on
top. (OLX's "newest" means most recently *refreshed*, so an old ad that
the seller bumps also rises — those get tagged "reativado".)

State (seen.json) holds ad ids already reported. On the very first run
the current listings are seeded silently instead of alerting on each.

Env vars (from .env via run_local.sh):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from hunt import WATCH

SEEN_PATH = Path(__file__).parent / "seen.json"
API_URL = "https://www.olx.pt/api/v1/offers/"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
# "Newest first". On OLX this orders by last refresh, not creation.
SORT = "created_at:desc"
# An ad created longer ago than this but showing up as new was bumped.
REACTIVATED_AFTER_DAYS = 14
# Matches the JSON string literal, escapes included. The older
# `"(.*?)";\s*\n` form depended on exact whitespace after the literal.
STATE_RE = re.compile(r'__PRERENDERED_STATE__\s*=\s*"((?:[^"\\]|\\.)*)"', re.S)


def _record(ad_id, title, price_label, price_value, url, city, region, created, refreshed):
    kind = WATCH["classify"](title)
    if kind is None:
        return None
    return {
        "id": ad_id,
        "title": title,
        "kind": kind,
        "price": price_label or "?",
        "price_value": price_value,
        "url": url or "",
        "city": city or "",
        "region": region or "",
        "created": created or "",
        "refreshed": refreshed or "",
    }


def _from_api(offer: dict) -> dict | None:
    price_label, price_value = None, None
    for prm in offer.get("params") or []:
        if prm.get("key") == "price":
            val = prm.get("value") or {}
            price_label, price_value = val.get("label"), val.get("value")
            break
    loc = offer.get("location") or {}
    return _record(
        offer["id"], (offer.get("title") or "").strip(), price_label, price_value,
        offer.get("url"), (loc.get("city") or {}).get("name"),
        (loc.get("region") or {}).get("name"),
        offer.get("created_time"), offer.get("last_refresh_time"),
    )


def _from_html(ad: dict) -> dict | None:
    price = ad.get("price") or {}
    loc = ad.get("location") or {}
    return _record(
        ad["id"], (ad.get("title") or "").strip(), price.get("displayValue"),
        (price.get("regularPrice") or {}).get("value"), ad.get("url"),
        loc.get("cityName"), loc.get("regionName"),
        ad.get("createdTime"), ad.get("lastRefreshTime"),
    )


def _api_url(query: str) -> str:
    qs = urllib.parse.urlencode({
        "offset": 0, "limit": 40, "query": query,
        "category_id": WATCH["category_id"], "sort_by": SORT,
    })
    return f"{API_URL}?{qs}"


def _get(url: str) -> str:
    """GET with browser-ish headers. OLX 403s bare requests."""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
        "Referer": "https://www.olx.pt/",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_via_api(query: str) -> list[dict]:
    payload = json.loads(_get(_api_url(query)))
    return [r for r in map(_from_api, payload.get("data") or []) if r]


def _find_ads(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "ads" and isinstance(v, list) and v and isinstance(v[0], dict) and "title" in v[0]:
                return v
            found = _find_ads(v)
            if found is not None:
                return found
    return None


def fetch_via_html(query: str) -> list[dict]:
    """Scrape the state blob embedded in the server-rendered search page.

    Note this must read the *server* response: a browser that has hydrated
    the page removes the script tag, so page.content() won't have it.
    """
    slug = "q-" + urllib.parse.quote(query.replace(" ", "-"))
    order = urllib.parse.urlencode({"search[order]": SORT})
    html = _get(f"https://www.olx.pt/{WATCH['category_path']}/{slug}/?{order}")
    m = STATE_RE.search(html)
    if not m:
        raise RuntimeError("__PRERENDERED_STATE__ not found")
    state = json.loads(json.loads('"' + m.group(1) + '"'))
    return [r for r in map(_from_html, _find_ads(state) or []) if r]


def fetch_via_browser(queries: list[str]) -> dict[int, dict]:
    """Drive a real browser on this machine; one session serves every query.

    Warms up on a category page first so the session picks up whatever
    cookies the bot check issues before the API calls.
    """
    from playwright.sync_api import sync_playwright  # lazy: optional dependency

    out: dict[int, dict] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        ctx = browser.new_context(locale="pt-PT", user_agent=UA)
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = ctx.new_page()
        page.goto(f"https://www.olx.pt/{WATCH['category_path']}/",
                  wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        for query in queries:
            payload = page.evaluate(
                """async (u) => {
                    const r = await fetch(u, {credentials:'include',
                                              headers:{'Accept':'application/json'}});
                    if (!r.ok) return {error: r.status};
                    return await r.json();
                }""",
                _api_url(query),
            )
            if not isinstance(payload, dict) or payload.get("error"):
                print(f"WARN: browser '{query}': HTTP {(payload or {}).get('error')}")
                continue
            hits = [r for r in map(_from_api, payload.get("data") or []) if r]
            for r in hits:
                out[r["id"]] = r
            print(f"browser '{query}': {len(hits)} relevant")
        browser.close()
    return out


def fetch_ads() -> list[dict]:
    """Plain HTTP per query (API, then HTML); if every query comes up
    empty, one shared browser session. Merged and deduped by ad id."""
    by_id: dict[int, dict] = {}
    errors: list[str] = []
    answered = False

    for query in WATCH["queries"]:
        got = None
        try:
            got = fetch_via_api(query)
            print(f"api     '{query}': {len(got)} relevant")
        except Exception as api_err:  # noqa: BLE001
            errors.append(f"api '{query}': {api_err}")
            try:
                got = fetch_via_html(query)
                print(f"html    '{query}': {len(got)} relevant (API failed over)")
            except Exception as html_err:  # noqa: BLE001
                errors.append(f"html '{query}': {html_err}")
        if got is not None:
            answered = True
            for ad in got:
                by_id[ad["id"]] = ad

    # Fall back on *no answer*, not on *no matches*: a query that answered
    # with zero relevant ads is a legitimate quiet day, not a block.
    if not answered:
        for e in errors:
            print(f"WARN: {e}")
        print("plain HTTP got no answer — trying local browser")
        try:
            by_id.update(fetch_via_browser(WATCH["queries"]))
        except ImportError:
            raise RuntimeError(
                "all plain-HTTP searches failed and Playwright isn't installed. "
                "OLX blocks datacenter IPs, so run this on a residential "
                "connection with: pip install -r requirements.txt && "
                "playwright install chromium"
            ) from None
        except Exception as browser_err:  # noqa: BLE001
            raise RuntimeError(
                f"all searches failed. plain HTTP: {' | '.join(errors)} ; "
                f"browser: {browser_err}"
            ) from None

    return sorted(by_id.values(), key=lambda a: a["refreshed"], reverse=True)


def send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("WARN: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — printing instead")
        print(text)
        return False
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "false",
    }).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:  # noqa: BLE001 — never let a send failure crash the run
        print(f"WARN: telegram send failed: {e}")
        return False


def _parse_ts(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _esc(s: str) -> str:
    """Titles go out as Telegram HTML; a stray '<' would reject the message."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_alert(a: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    head = WATCH["tags"].get(a["kind"], a["kind"])
    threshold = (WATCH.get("good_price") or {}).get(a["kind"])
    if threshold is not None and a["price_value"] is not None and a["price_value"] <= threshold:
        head += " · 🔥 BOM PREÇO"

    lines = [head, f"<b>{_esc(a['title'])}</b>"]
    brands = WATCH.get("brands", lambda t: [])(a["title"])
    if brands:
        lines.append("🏷️ " + " / ".join(brands))

    info = f"💶 {_esc(a['price'])}"
    where = " · ".join(x for x in (a["city"], a["region"]) if x)
    if where:
        info += f" · 📍 {_esc(where)}"
    lines.append(info)

    created = _parse_ts(a["created"])
    if created:
        when = f"🕒 publicado {created.strftime('%d/%m %H:%M')}"
        if (now - created).days >= REACTIVATED_AFTER_DAYS:
            when += " · 🔁 reativado"
        lines.append(when)

    lines.append(a["url"])
    return "\n".join(lines)


def main() -> int:
    seen: set[int] = set()
    first_run = not SEEN_PATH.exists()
    if not first_run:
        try:
            seen = set(json.loads(SEEN_PATH.read_text()))
        except Exception:  # noqa: BLE001 — corrupt state shouldn't be fatal
            print("WARN: seen.json unreadable, treating as first run")
            first_run = True

    ads = fetch_ads()
    print(f"[{WATCH['name']}] {len(ads)} relevant, {len(seen)} previously seen")

    # Seed silently on the first run instead of alerting on every listing.
    if first_run:
        SEEN_PATH.write_text(json.dumps(sorted(a["id"] for a in ads)))
        print(f"first run — seeded {len(ads)} ads without notifying")
        for a in ads:
            print(f"  [{a['kind']:5s}] {a['price']:>9s}  {a['created'][:10]}  {a['title'][:58]}")
        return 0

    new = [a for a in ads if a["id"] not in seen]
    for a in new:
        send_telegram(format_alert(a))
        print(f"notified: [{a['id']}] {a['kind']} {a['price']} — {a['title'][:60]}")

    if new:
        SEEN_PATH.write_text(json.dumps(sorted(seen | {a["id"] for a in ads})))
    else:
        print("no new ads")
    return 0


if __name__ == "__main__":
    sys.exit(main())
