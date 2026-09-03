# olx-watch

Polls OLX.pt every ~15 min (GitHub Actions cron), diffs against
`seen.json`, and Telegram-notifies any new listing that matches.

**Currently hunting:** Ray-Ban Hexagonal **RB3548N** sunglasses.

Alerts are tagged by confidence and price:

| Tag | Meaning |
|---|---|
| 🕶️🔥 **RB3548N — BOM PREÇO** | Model number in the title, at or under the good-price threshold |
| 🕶️ **RB3548N** | Model number in the title |
| 🕶️🔥 Ray-Ban Hexagonal — BOM PREÇO | Ray-Ban + hexagonal, no model number, good price |
| 🕶️ Ray-Ban Hexagonal | Ray-Ban + hexagonal, no model number |
| 🔧 Só peças/lentes | Matched, but it's replacement lenses/frames rather than whole glasses |

Look-alikes that share the search results are filtered out — notably the
**RB4548NM** Scuderia Ferrari hexagonal (different, pricier model) and
non-hexagonal Ray-Bans (Clubmaster RB3016, RB3386, …).

## Retargeting

Everything about the hunt lives in the `WATCH` dict at the top of
`watcher.py` — searches, brand/model/shape regexes, exclusions, price
threshold. To point it at something else: edit that dict, delete
`seen.json` (so the new target seeds cleanly instead of firing an alert
per existing listing), commit.

## Setup

Repo secrets: `TELEGRAM_BOT_TOKEN` (from @BotFather) and
`TELEGRAM_CHAT_ID`.

## Where this runs (and why not in the cloud)

OLX blocks datacenter IPs. Every GitHub Actions run 403s — on the JSON
API *and* the HTML scrape, for every query — so the scheduled workflow
is disabled and the watcher runs **locally on the Mac** instead, where a
residential IP plus a real browser gets through.

`watcher.py` tries three tiers per run and stops at the first that works:

1. **JSON API** over plain HTTP — cheapest, used when OLX isn't throttling
2. **HTML scrape** of `__PRERENDERED_STATE__` — different protection path
3. **Playwright browser** — warms up on the homepage for cookies, then
   calls the API from page context. The only tier that survives a
   throttled IP.

### Local scheduling

A launchd agent runs it every 15 minutes:

```
~/Library/LaunchAgents/pt.previews.olxwatch.plist
```

```bash
launchctl unload ~/Library/LaunchAgents/pt.previews.olxwatch.plist   # stop
launchctl load   ~/Library/LaunchAgents/pt.previews.olxwatch.plist   # start
tail -f ~/olx-watch/watcher.log                                      # watch
```

The repo lives at `~/olx-watch` rather than under `~/Desktop` because
macOS TCC blocks launchd agents from reading Desktop/Documents/Downloads
without Full Disk Access.

Telegram credentials live in `.telegram_token` and `.telegram_chat`
(gitignored, chmod 600) rather than in the repo.

**Caveat:** this only runs while the Mac is awake. Asleep or off means no
checks. For an always-on safety net, OLX's own **"Guardar Pesquisa"**
button on the search page sends native alerts and needs no
infrastructure.
