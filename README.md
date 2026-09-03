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
