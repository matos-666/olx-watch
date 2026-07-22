# vagos-watch

Watches OLX.pt for Vagos Metal Fest ticket listings. Every 15 minutes a
GitHub Actions cron scrapes the search page, diffs against `seen.json`,
and Telegram-notifies any new listing — with a loud tag when the title
looks like a 5-day full pass.

Setup: set repo secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
