"""OLX.pt watcher — polls a set of searches and Telegrams every new listing.

Currently targeting: Ray-Ban Hexagonal RB3548N sunglasses.

Design note — why this file is config-driven:
    This started life watching Vagos Metal Fest tickets and got retargeted
    at sunglasses once the festival passed. Retargeting used to mean
    editing scattered constants and regexes, so the whole hunt is now one
    WATCH dict at the top. To point it at something else, edit that dict
    and wipe seen.json; nothing below it should need touching.

State (seen.json) is committed back to the repo by the GitHub Actions
workflow, which is what gives persistence between runs without any
external storage.

Env vars (set as GitHub Actions secrets):
    TELEGRAM_BOT_TOKEN  — from @BotFather
    TELEGRAM_CHAT_ID    — your personal chat with the bot

Exit code is 0 unless every search fails — a Telegram send failure logs
but doesn't crash, so one bad send never blocks the seen-state update
and floods you with duplicates on the next run.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------
# WHAT WE'RE HUNTING — edit this block to retarget the watcher
# ---------------------------------------------------------------------
WATCH = {
    "name": "Ray-Ban Hexagonal RB3548N",
    # Several queries, merged and deduped by ad id. OLX caps each search
    # around 40 results and pads the tail with loosely-related items, so
    # two narrow queries beat one broad one for coverage.
    "queries": ["ray ban hexagonal", "rb3548"],
    # Category path, used only by the HTML fallback below.
    "category_path": "moda/malas-e-acessorios/oculos-sol",
    # A title must look like Ray-Ban…
    "brand": re.compile(r"ray[\s\-]?ban", re.I),
    # …and name either the exact model or the shape.
    "model": re.compile(r"3548", re.I),
    "shape": re.compile(r"hexagon", re.I),
    # Other Ray-Ban model numbers that ride along in the results
    # (RB4548NM is the Ferrari hexagonal and RB3579N the Blaze hexagonal —
    # both hexagonal but NOT the RB3548N; RB3016 Clubmaster / RB3386 / etc.
    # aren't hexagonal at all).
    # Digit-boundary lookarounds, NOT \b: model codes are glued to letter
    # suffixes ("RB4548NM"), and \b never matches between a digit and a
    # letter — so a trailing \b silently let the Ferrari RB4548NM through.
    "other_models": re.compile(r"(?<!\d)(?:4548|3579|3016|3386|3025|2140|3447|4165)(?!\d)", re.I),
    # Replacement lenses, not the actual sunglasses. Still reported, but
    # tagged so a glance tells them apart.
    "parts_only": re.compile(r"\blentes?\b|\blenses\b|\bhaste|\barmaç", re.I),
    # Below this (EUR) it's worth jumping on; used only for the alert tag.
    "good_price": 60,
}

SEEN_PATH = Path(__file__).parent / "seen.json"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def classify(title: str) -> str | None:
    """Return 'exact' | 'likely' | 'parts' for a title we care about, else None.

    'exact'  — names model 3548, so it's the RB3548N family for sure.
    'likely' — Ray-Ban + hexagonal, no competing model number.
    'parts'  — matched above but it's lenses/frames/arms, not whole glasses.
    """
    if not WATCH["brand"].search(title):
        return None

    has_model = bool(WATCH["model"].search(title))
    has_shape = bool(WATCH["shape"].search(title))
    other = bool(WATCH["other_models"].search(title))

    if has_model:
        kind = "exact"
    elif has_shape and not other:
        kind = "likely"
    else:
        return None

    if WATCH["parts_only"].search(title):
        return "parts"
    return kind


API_URL = "https://www.olx.pt/api/v1/offers/"


def _normalise(offer: dict) -> dict | None:
    """Turn one OLX API offer into our internal shape, or None if irrelevant."""
    title = (offer.get("title") or "").strip()
    kind = classify(title)
    if kind is None:
        return None
    price_label, price_value = "?", None
    for prm in offer.get("params") or []:
        if prm.get("key") == "price":
            val = prm.get("value") or {}
            price_label = val.get("label") or prm.get("label") or "?"
            price_value = val.get("value")
            break
    loc = offer.get("location") or {}
    return {
        "id": offer["id"],
        "title": title,
        "kind": kind,
        "price": price_label,
        "price_value": price_value,
        "url": offer.get("url", ""),
        "city": (loc.get("city") or {}).get("name") or "",
        "region": (loc.get("region") or {}).get("name") or "",
    }


def _get(url: str) -> str:
    """GET with browser-ish headers. OLX 403s bare requests."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
            "Referer": "https://www.olx.pt/",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_via_api(query: str) -> list[dict]:
    """Primary path: OLX's own JSON API. Cleaner than scraping and gives
    a numeric price instead of a display string we'd have to parse."""
    qs = urllib.parse.urlencode({"offset": 0, "limit": 40, "query": query})
    payload = json.loads(_get(f"{API_URL}?{qs}"))
    out = []
    for offer in payload.get("data") or []:
        norm = _normalise(offer)
        if norm:
            out.append(norm)
    return out


def fetch_via_html(query: str) -> list[dict]:
    """Fallback: scrape __PRERENDERED_STATE__ out of the search page.

    Kept because the API and the HTML sit behind different protection —
    when one starts 403ing the other has historically still worked.
    """
    slug = "q-" + query.replace(" ", "-")
    url = f"https://www.olx.pt/{WATCH['category_path']}/{slug}/"
    html = _get(url)
    m = re.search(r'window\.__PRERENDERED_STATE__\s*=\s*"(.*?)";\s*\n', html, re.S)
    if not m:
        raise RuntimeError("__PRERENDERED_STATE__ not found")
    state = json.loads(json.loads('"' + m.group(1) + '"'))

    def find_ads(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if (
                    k == "ads"
                    and isinstance(v, list)
                    and v
                    and isinstance(v[0], dict)
                    and "title" in v[0]
                ):
                    return v
                found = find_ads(v)
                if found is not None:
                    return found
        return None

    out = []
    for a in find_ads(state) or []:
        title = (a.get("title") or "").strip()
        kind = classify(title)
        if kind is None:
            continue
        price = a.get("price") or {}
        out.append({
            "id": a["id"],
            "title": title,
            "kind": kind,
            "price": price.get("displayValue") or "?",
            "price_value": (price.get("regularPrice") or {}).get("value"),
            "url": a.get("url", ""),
            "city": (a.get("location") or {}).get("cityName") or "",
            "region": (a.get("location") or {}).get("regionName") or "",
        })
    return out


def fetch_via_browser(queries: list[str]) -> dict[int, dict]:
    """Last resort: drive a real browser on this machine.

    OLX blocks datacenter IPs outright (GitHub Actions gets 403 on both
    the API and the HTML) and also 403s plain HTTP from residential IPs.
    A real browser on a residential connection still passes, so this tier
    exists for running the watcher locally.

    One browser handles every query: launching Chromium costs ~2s, and we
    warm up on the homepage once so the session picks up whatever cookies
    the bot check hands out before touching the API.
    """
    from playwright.sync_api import sync_playwright  # imported lazily

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
        page.goto("https://www.olx.pt/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)

        for query in queries:
            qs = urllib.parse.urlencode({"offset": 0, "limit": 40, "query": query})
            payload = page.evaluate(
                """async (u) => {
                    const r = await fetch(u, {credentials:'include',
                                              headers:{'Accept':'application/json'}});
                    if (!r.ok) return {error: r.status};
                    return await r.json();
                }""",
                f"{API_URL}?{qs}",
            )
            if not isinstance(payload, dict) or payload.get("error"):
                print(f"WARN: browser '{query}': HTTP {(payload or {}).get('error')}")
                continue
            hits = 0
            for offer in payload.get("data") or []:
                norm = _normalise(offer)
                if norm:
                    out[norm["id"]] = norm
                    hits += 1
            print(f"browser '{query}': {hits} relevant")

        browser.close()
    return out


def fetch_ads() -> list[dict]:
    """Try plain HTTP first (API, then HTML) per query; if every query
    comes up empty, fall back to one shared browser session.

    Results are merged and deduped by ad id across all tiers.
    """
    by_id: dict[int, dict] = {}
    errors = []

    for query in WATCH["queries"]:
        got = None
        try:
            got = fetch_via_api(query)
            print(f"api   '{query}': {len(got)} relevant")
        except Exception as api_err:  # noqa: BLE001
            errors.append(f"api '{query}': {api_err}")
            try:
                got = fetch_via_html(query)
                print(f"html  '{query}': {len(got)} relevant (API failed over)")
            except Exception as html_err:  # noqa: BLE001
                errors.append(f"html '{query}': {html_err}")
        for ad in got or []:
            by_id[ad["id"]] = ad

    if not by_id:
        # Every plain-HTTP path failed. This is the normal state from a
        # datacenter IP, so it's expected rather than exceptional.
        for e in errors:
            print(f"WARN: {e}")
        print("plain HTTP got nothing — trying local browser")
        try:
            by_id.update(fetch_via_browser(WATCH["queries"]))
        except ImportError:
            raise RuntimeError(
                "all plain-HTTP searches failed and Playwright isn't installed. "
                "OLX blocks datacenter IPs, so this watcher needs to run on a "
                "residential connection with `pip install playwright && "
                "playwright install chromium`."
            ) from None
        except Exception as browser_err:  # noqa: BLE001
            raise RuntimeError(
                f"all searches failed. plain HTTP: {' | '.join(errors)} ; "
                f"browser: {browser_err}"
            ) from None

    if not by_id:
        raise RuntimeError("all searches failed: " + " | ".join(errors))

    return sorted(by_id.values(), key=lambda a: (a["price_value"] or 9e9))


def send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("WARN: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — printing instead")
        print(text)
        return False
    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:  # noqa: BLE001
        print(f"WARN: telegram send failed: {e}")
        return False


def format_alert(a: dict) -> str:
    cheap = (
        a["price_value"] is not None
        and a["price_value"] <= WATCH["good_price"]
        and a["kind"] != "parts"
    )
    if a["kind"] == "parts":
        tag = "🔧 Só peças/lentes"
    elif a["kind"] == "exact" and cheap:
        tag = "🕶️🔥 <b>RB3548N — BOM PREÇO</b>"
    elif a["kind"] == "exact":
        tag = "🕶️ <b>RB3548N</b>"
    elif cheap:
        tag = "🕶️🔥 <b>Ray-Ban Hexagonal — BOM PREÇO</b>"
    else:
        tag = "🕶️ Ray-Ban Hexagonal"

    where = " · ".join(x for x in (a["city"], a["region"]) if x)
    return (
        f"{tag}\n"
        f"<b>{a['title']}</b>\n"
        f"💶 {a['price']}"
        + (f" · 📍 {where}" if where else "")
        + f"\n{a['url']}"
    )


def main() -> int:
    seen: set[int] = set()
    if SEEN_PATH.exists():
        try:
            seen = set(json.loads(SEEN_PATH.read_text()))
        except Exception:  # noqa: BLE001 — corrupt state shouldn't be fatal
            print("WARN: seen.json unreadable, treating as first run")

    ads = fetch_ads()
    print(f"matched {len(ads)} relevant ads, {len(seen)} previously seen")

    new = [a for a in ads if a["id"] not in seen]

    # First run: seed silently rather than firing an alert per existing ad.
    if not seen:
        print(f"first run — seeding {len(ads)} ads without notifying")
        SEEN_PATH.write_text(json.dumps(sorted(a["id"] for a in ads)))
        for a in ads:
            print(f"  [{a['kind']:6s}] {a['price']:>8s}  {a['title'][:60]}")
        return 0

    for a in new:
        send_telegram(format_alert(a))
        print(f"notified: [{a['id']}] {a['kind']} {a['price']} — {a['title'][:60]}")

    if new:
        SEEN_PATH.write_text(json.dumps(sorted(seen | {a["id"] for a in ads})))
        print(f"state updated: {len(seen | {a['id'] for a in ads})} ids")
    else:
        print("no new ads")

    return 0


if __name__ == "__main__":
    sys.exit(main())
