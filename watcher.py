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
    # Several searches, merged and deduped by ad id. OLX caps each search
    # at ~40 results and pads the tail with loosely-related items, so two
    # narrow searches beat one broad one for coverage.
    "searches": [
        "https://www.olx.pt/moda/malas-e-acessorios/oculos-sol/q-ray-ban-hexagonal/",
        "https://www.olx.pt/moda/malas-e-acessorios/oculos-sol/q-rb3548/",
    ],
    # A title must look like Ray-Ban…
    "brand": re.compile(r"ray[\s\-]?ban", re.I),
    # …and name either the exact model or the shape.
    "model": re.compile(r"3548", re.I),
    "shape": re.compile(r"hexagon", re.I),
    # Other Ray-Ban model numbers that ride along in the results
    # (RB4548NM is the Ferrari hexagonal — a different, pricier model;
    # RB3016 Clubmaster / RB3386 / etc. aren't hexagonal at all).
    # Digit-boundary lookarounds, NOT \b: model codes are glued to letter
    # suffixes ("RB4548NM"), and \b never matches between a digit and a
    # letter — so a trailing \b silently let the Ferrari RB4548NM through.
    "other_models": re.compile(r"(?<!\d)(?:4548|3016|3386|3025|2140|3447|4165)(?!\d)", re.I),
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


def fetch_ads() -> list[dict]:
    """Fetch every configured search, merge, dedupe by id, keep relevant."""
    by_id: dict[int, dict] = {}
    errors = []

    for url in WATCH["searches"]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url}: {e}")
            continue

        m = re.search(r'window\.__PRERENDERED_STATE__\s*=\s*"(.*?)";\s*\n', html, re.S)
        if not m:
            errors.append(f"{url}: __PRERENDERED_STATE__ not found")
            continue

        try:
            state = json.loads(json.loads('"' + m.group(1) + '"'))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url}: state parse failed: {e}")
            continue

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

        for a in find_ads(state) or []:
            title = (a.get("title") or "").strip()
            kind = classify(title)
            if kind is None:
                continue
            price_obj = (a.get("price") or {}).get("regularPrice") or {}
            by_id[a["id"]] = {
                "id": a["id"],
                "title": title,
                "kind": kind,
                "price": (a.get("price") or {}).get("displayValue") or "?",
                "price_value": price_obj.get("value"),
                "url": a.get("url", ""),
                "city": (a.get("location") or {}).get("cityName") or "",
                "region": (a.get("location") or {}).get("regionName") or "",
            }

    # Only a total wipeout is fatal — one dead search shouldn't kill the run.
    if errors and not by_id:
        raise RuntimeError("all searches failed: " + " | ".join(errors))
    for e in errors:
        print(f"WARN: {e}")

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
