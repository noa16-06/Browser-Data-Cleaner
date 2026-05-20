# Browser-Data-Cleaner

Clears cookies, history, searches, cache, and form data for major browsers. Supports macOS, Windows, and Linux.

## Browsers covered

| Engine   | Browsers                                                    |
|----------|-------------------------------------------------------------|
| Chromium | Chrome, Brave, Chromium, Edge, Opera, Vivaldi, Arc          |
| Firefox  | Firefox, LibreWolf, Waterfox, Floorp, Zen, Pale Moon, Basilisk |
| WebKit   | Safari (macOS only)                                         |

## What it clears

- **Cookies** — all session and persistent cookies
- **History** — visited URLs and page visits
- **Searches** — address bar input history, search engine queries, `keyword_search_terms`
- **Cache** — disk cache, GPU cache, shader cache, service workers
- **Form data** — autofill entries, stored form values
- **Session storage** — IndexedDB, local/session storage

## Flags

```
--dry-run       Preview what would be deleted (no changes made)
--yes           Skip the confirmation prompt
--no-cache      Skip cache directories (faster, keeps cache)
--passwords     Also delete saved passwords (disabled by default)
```

## Usage

```bash
python3 clear_browser_data.py             # interactive
python3 clear_browser_data.py --dry-run   # preview first
python3 clear_browser_data.py --yes       # no prompt
```

> **Tip:** Close all browsers before running — SQLite files locked by a running browser will show a "Permission denied" error and be skipped safely.
