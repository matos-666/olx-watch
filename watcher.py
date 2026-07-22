"""OLX watcher for Vagos Metal Fest tickets.

Scrapes the OLX.pt search results for Vagos Metal Fest ticket listings,
keeps a JSON file of already-seen ad IDs, and sends a Telegram message
for every new listing — with a loud tag when the title looks like a
full 5-day general pass (the thing we actually want to buy).

Designed to run inside a GitHub Actions cron every 15 minutes. State
(seen.json) is committed back to the repo by the workflow, which is
what gives us persistence between runs without any external storage.

Env vars (set as GitHub Actions secrets):
    TELEGRAM_BOT_TOKEN  — from @BotFather
    TELEGRAM_CHAT_ID    — your personal chat with the bot

Exit code is always 0 unless the page fetch itself fails — a Telegram
send failure logs but doesn't crash, so one bad send never blocks the
seen-state update and floods you with duplicates on the next run.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SEARCH_URL = "https://www.olx.pt/lazer/bilhetes-espectaculos/q-vagos-metal-fest-bilhete/"
SEEN_PATH = Path(__file__).parent / "seen.json"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# OLX pads search results with loosely-related listings once exact
# matches run out (the test run surfaced Franz Ferdinand and Blood
# Orange tickets). Only keep ads whose title actually references the
# festival.
RELEVANT_RE = re.compile(r"vagos|vmf\b|vagos\s*metal", re.IGNORECASE)

# Title patterns that mark a listing as the coveted full pass. OLX
# sellers write these a dozen ways — "passe geral", "passe 5 dias",
# "bilhete 5 dias", "full pass", "passe completo"...
FULL_PASS_RE = re.compile(
    r"passe\s*(geral|completo|5\s*dias?)|5\s*dias?|full\s*pass|bilhete\s+geral",
    re.IGNORECASE,
)


def fetch_ads() -> list[dict]:
    req = urllib.request.Request(SEARCH_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    m = re.search(r'window\.__PRERENDERED_STATE__\s*=\s*"(.*?)";\s*\n', html, re.S)
    if not m:
        raise RuntimeError("__PRERENDERED_STATE__ not found — OLX layout changed?")

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

    ads = find_ads(state)
    if ads is None:
        raise RuntimeError("ads array not found in prerendered state")

    out = []
    for a in ads:
        title = a.get("title", "")
        if not RELEVANT_RE.search(title):
            continue
        price = (a.get("price") or {}).get("displayValue") or "?"
        out.append(
            {
                "id": a["id"],
                "title": a.get("title", "").strip(),
                "price": price,
                "url": a.get("url", ""),
                "created": a.get("createdTime", ""),
                "city": ((a.get("location") or {}).get("cityName") or ""),
                "is_full_pass": bool(FULL_PASS_RE.search(a.get("title", ""))),
            }
        )
    return out


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
    except Exception as e:  # noqa: BLE001 — never let a send failure crash the run
        print(f"WARN: telegram send failed: {e}")
        return False


def main() -> int:
    seen: set[int] = set()
    if SEEN_PATH.exists():
        seen = set(json.loads(SEEN_PATH.read_text()))

    ads = fetch_ads()
    print(f"fetched {len(ads)} ads, {len(seen)} previously seen")

    new = [a for a in ads if a["id"] not in seen]

    # First run: seed the state silently instead of spamming 40 alerts.
    if not seen:
        print(f"first run — seeding {len(ads)} ads without notifying")
        SEEN_PATH.write_text(json.dumps(sorted(a["id"] for a in ads)))
        return 0

    for a in new:
        tag = "🎫🔥 <b>PASSE GERAL 5 DIAS</b>" if a["is_full_pass"] else "🎟️ Novo anúncio"
        msg = (
            f"{tag}\n"
            f"<b>{a['title']}</b>\n"
            f"💶 {a['price']} · 📍 {a['city']}\n"
            f"{a['url']}"
        )
        send_telegram(msg)
        print(f"notified: [{a['id']}] {a['title']} — {a['price']}")

    if new:
        all_ids = seen | {a["id"] for a in ads}
        SEEN_PATH.write_text(json.dumps(sorted(all_ids)))
        print(f"state updated: {len(all_ids)} ids")
    else:
        print("no new ads")

    return 0


if __name__ == "__main__":
    sys.exit(main())
