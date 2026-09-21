# olx-watch

Polls OLX.pt every 15 minutes and sends a Telegram message for every new
listing that matches.

**Currently hunting:** guitar cabinets, **4x12** (in Lazer › Instrumentos
Musicais).

| Alert | Meaning |
|---|---|
| 🔊 **Coluna 4x12** | a standalone cab |
| 🎛️ **Cabeça + coluna 4x12** | head and cab sold together |
| 🔧 Acessório p/ 4x12 | cover, wheels, speakers *for* a 4x12 |
| · 🔥 BOM PREÇO | at or under the threshold (cab ≤ 200 €, stack ≤ 400 €) |
| · 🔁 reativado | an old ad the seller just bumped back to the top |

Each alert also shows brand(s), price, location, publish date and link.

The filter recognises every way sellers write it (`4x12`, `4 x 12`,
`4X12`, `4×12`), model codes that never say "4x12" (Orange PPC412, Marshall
AVT412 / 8412 / 1960, Blackstar HTV-412A), and bare "412" next to a cab
word. It drops 2x12/1x12 cabs, "Compro"/"Procuro" posts (buyers), rentals,
and guitars whose model number contains 412 (Harley Benton CLJ-412E).
`test_hunt.py` holds the cases — every past mistake is one of them.

```bash
python3 -m unittest            # run the classifier suite
```

## Layout

| File | Role |
|---|---|
| `hunt.py` | **what** to hunt: queries, category, classifier, alert tags, price thresholds |
| `watcher.py` | the engine: fetch, dedupe, alert. Target-agnostic |
| `test_hunt.py` | regression suite for the classifier and the alert format |
| `seen.json` | ids already reported. Local state, gitignored |

### Retargeting

Replace `hunt.py` (its docstring lists what it must export), update
`test_hunt.py`, **delete `seen.json`**, then run once by hand. Deleting
the state makes the first run seed the current listings silently.
Without that, every existing listing would alert as new.

## Why newest-first matters

OLX returns about 40 results per query and ranks by relevance unless told
otherwise. With 146+ matches, a fresh listing can land at position 90 and
never be seen. Every query is sent with `sort_by=created_at:desc`, which
on OLX means *most recently refreshed*. New listings are always on top.

## Where this runs (and why not in the cloud)

OLX blocks datacenter IPs: GitHub Actions gets 403 on the API *and* the
HTML. The scheduled workflow is disabled (manual dispatch kept for
retesting), and the watcher runs **locally on the Mac** via launchd.

`watcher.py` degrades through three fetch tiers, stopping at the first
that answers:

1. **JSON API** over plain HTTP: about 25 MB, under 1 s
2. **HTML scrape** of the server-rendered state
3. **Playwright browser**: about 670 MB, about 5 s. The only tier that
   survives a throttled IP. It launches only when OLX doesn't answer at
   all, never merely because nothing matched.

A `while True` loop was considered and rejected. launchd restarts after
crashes and reboots, and nothing stays resident between checks.

```bash
launchctl unload ~/Library/LaunchAgents/pt.previews.olxwatch.plist   # stop
launchctl load   ~/Library/LaunchAgents/pt.previews.olxwatch.plist   # start
tail -f ~/olx-watch/watcher.log                                      # watch
```

The repo lives at `~/olx-watch` rather than under `~/Desktop`, because
macOS TCC blocks launchd agents from reading Desktop, Documents and
Downloads.

## Setup

```bash
pip install -r requirements.txt && playwright install chromium
cp .env.example .env    # fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
```

**Caveat:** it only runs while the Mac is awake. For an always-on safety
net, OLX's own **"Guardar Pesquisa"** button on the search page sends
native alerts.
