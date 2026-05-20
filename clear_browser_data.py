#!/usr/bin/env python3
"""
Browser Data Cleaner
Clears cookies, history, searches, cache, and form data for major browsers.
Supports macOS, Windows, and Linux.

Usage:
    python clear_browser_data.py                  # interactive confirmation
    python clear_browser_data.py --yes            # skip confirmation
    python clear_browser_data.py --dry-run        # preview only, no changes
    python clear_browser_data.py --no-cache       # skip cache deletion
    python clear_browser_data.py --passwords      # also delete saved passwords
"""

import os
import sys
import platform
import shutil
import sqlite3
import argparse
import configparser
from pathlib import Path


# ── CLI args ──────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Clear browser cookies, history, cache, and form data.")
    p.add_argument("--yes",       action="store_true", help="Skip confirmation prompt")
    p.add_argument("--dry-run",   action="store_true", help="Print what would be deleted without doing it")
    p.add_argument("--no-cache",  action="store_true", help="Skip cache directories")
    p.add_argument("--passwords", action="store_true", help="Also delete saved passwords (irreversible!)")
    return p.parse_args()


# ── Helpers ───────────────────────────────────────────────────────────────────

ARGS = None  # set in main()

def log(msg: str):
    print(msg)

def delete_file(path: Path):
    if not path.exists():
        return
    if ARGS.dry_run:
        log(f"    [dry-run] would delete: {path}")
        return
    try:
        path.unlink()
        log(f"    Deleted: {path}")
    except PermissionError:
        log(f"    Permission denied (is the browser open?): {path}")
    except Exception as e:
        log(f"    Error deleting {path}: {e}")

def delete_dir(path: Path):
    if not path.exists():
        return
    if ARGS.dry_run:
        log(f"    [dry-run] would remove dir: {path}")
        return
    try:
        shutil.rmtree(path)
        log(f"    Removed dir: {path}")
    except PermissionError:
        log(f"    Permission denied (is the browser open?): {path}")
    except Exception as e:
        log(f"    Error removing {path}: {e}")

def clear_sqlite_tables(db_path: Path, table_queries: list[str]):
    """Run DELETE statements against a SQLite database."""
    if not db_path.exists():
        return
    if ARGS.dry_run:
        log(f"    [dry-run] would clear tables in: {db_path}")
        return
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        for q in table_queries:
            try:
                conn.execute(q)
            except sqlite3.OperationalError as e:
                # Table may not exist in older browser versions — safe to skip
                pass
        conn.commit()
        conn.execute("VACUUM")
        conn.close()
        log(f"    Cleared: {db_path}")
    except PermissionError:
        log(f"    Permission denied (is the browser open?): {db_path}")
    except Exception as e:
        log(f"    Error clearing {db_path}: {e}")


# ── Chromium-based browsers ───────────────────────────────────────────────────

CHROMIUM_COOKIE_QUERIES = [
    "DELETE FROM cookies",
]

CHROMIUM_HISTORY_QUERIES = [
    "DELETE FROM urls",
    "DELETE FROM visits",
    "DELETE FROM visit_source",
    "DELETE FROM downloads",
    "DELETE FROM downloads_url_chains",
    "DELETE FROM keyword_search_terms",
    "DELETE FROM segments",
    "DELETE FROM segment_usage",
    "DELETE FROM typed_url_sync_metadata",
]

CHROMIUM_FORM_QUERIES = [
    "DELETE FROM autofill",
    "DELETE FROM autofill_dates",
    "DELETE FROM autofill_profile_emails",
    "DELETE FROM autofill_profile_names",
    "DELETE FROM autofill_profile_phones",
    "DELETE FROM autofill_profiles",
    "DELETE FROM keywords",          # search engines typed into address bar
]

CHROMIUM_PASSWORD_QUERIES = [
    "DELETE FROM logins",
    "DELETE FROM stats",
    "DELETE FROM insecure_credentials",
]


def chromium_profiles(base: Path) -> list[Path]:
    """Return all profile directories inside a Chromium user-data directory."""
    if not base.exists():
        return []
    dirs = []
    for candidate in [base / "Default"] + sorted(base.glob("Profile *")):
        if candidate.is_dir():
            dirs.append(candidate)
    return dirs


def clear_chromium_profile(base: Path, profile: Path):
    log(f"  Profile: {profile.name}")

    # Cookies
    clear_sqlite_tables(profile / "Cookies", CHROMIUM_COOKIE_QUERIES)

    # History & searches
    clear_sqlite_tables(profile / "History", CHROMIUM_HISTORY_QUERIES)

    # Form data / autofill
    clear_sqlite_tables(profile / "Web Data", CHROMIUM_FORM_QUERIES)

    # Saved passwords
    if ARGS.passwords:
        clear_sqlite_tables(profile / "Login Data", CHROMIUM_PASSWORD_QUERIES)
        clear_sqlite_tables(profile / "Login Data For Account", CHROMIUM_PASSWORD_QUERIES)

    # Cache
    if not ARGS.no_cache:
        for cache in ["Cache", "Code Cache", "GPUCache", "Service Worker"]:
            delete_dir(profile / cache)
        delete_dir(base / "ShaderCache")

    # Session / storage
    for d in ["Local Storage", "Session Storage", "IndexedDB"]:
        delete_dir(profile / d)


def clear_chromium(name: str, base: Path):
    log(f"\n[{name}]")
    if not base.exists():
        log(f"  Not installed (path not found)")
        return
    profiles = chromium_profiles(base)
    if not profiles:
        log(f"  No profiles found in {base}")
        return
    for p in profiles:
        clear_chromium_profile(base, p)


# ── Firefox-based browsers ────────────────────────────────────────────────────

FIREFOX_COOKIE_QUERIES = [
    "DELETE FROM moz_cookies",
]

FIREFOX_HISTORY_QUERIES = [
    "DELETE FROM moz_historyvisits",
    "DELETE FROM moz_inputhistory",
    # Remove non-bookmarked places (visited pages)
    "DELETE FROM moz_places WHERE id NOT IN (SELECT fk FROM moz_bookmarks WHERE fk IS NOT NULL)",
]

FIREFOX_FORMHISTORY_QUERIES = [
    "DELETE FROM moz_formhistory",
]

FIREFOX_SEARCH_QUERIES = [
    # search history stored in places (search engine queries)
    "DELETE FROM moz_places WHERE url LIKE '%?q=%' OR url LIKE '%?s=%' OR url LIKE '%search?%' OR url LIKE '%/search/%'",
]


def firefox_find_profiles(root: Path) -> list[Path]:
    """Return profile directories from a Firefox root (reads profiles.ini)."""
    if not root.exists():
        return []

    profiles_ini = root / "profiles.ini"
    results = []

    if profiles_ini.exists():
        cfg = configparser.ConfigParser()
        cfg.read(profiles_ini, encoding="utf-8")
        for section in cfg.sections():
            if not section.startswith("Profile"):
                continue
            path_val = cfg[section].get("Path", "").strip()
            is_relative = cfg[section].get("IsRelative", "1").strip() == "1"
            if not path_val:
                continue
            profile_path = (root / path_val) if is_relative else Path(path_val)
            if profile_path.is_dir():
                results.append(profile_path)

    if not results:
        # Fallback: glob for *.default* directories
        for d in root.iterdir():
            if d.is_dir() and ("." in d.name):
                results.append(d)

    return results


def clear_firefox_profile(profile: Path):
    log(f"  Profile: {profile.name}")

    # Cookies
    clear_sqlite_tables(profile / "cookies.sqlite", FIREFOX_COOKIE_QUERIES)

    # History & search bar history
    clear_sqlite_tables(profile / "places.sqlite", FIREFOX_HISTORY_QUERIES)

    # Form & search input history
    clear_sqlite_tables(profile / "formhistory.sqlite", FIREFOX_FORMHISTORY_QUERIES)

    # Saved passwords
    if ARGS.passwords:
        delete_file(profile / "key4.db")
        delete_file(profile / "logins.json")
        delete_file(profile / "key3.db")

    # Cache
    if not ARGS.no_cache:
        for cache_dir in ["cache2", "startupCache", "OfflineCache", "thumbnails"]:
            delete_dir(profile / cache_dir)

    # Session / storage
    for d in ["storage", "IndexedDB", "serviceworker"]:
        delete_dir(profile / d)

    # Session restore (clears open-tab session state)
    delete_file(profile / "sessionstore.jsonlz4")


def clear_firefox(name: str, root: Path):
    log(f"\n[{name}]")
    if not root.exists():
        log(f"  Not installed (path not found)")
        return
    profiles = firefox_find_profiles(root)
    if not profiles:
        log(f"  No profiles found in {root}")
        return
    for p in profiles:
        clear_firefox_profile(p)


# ── Safari (macOS only) ───────────────────────────────────────────────────────

def clear_safari(home: Path):
    log("\n[Safari]")
    safari = home / "Library/Safari"
    if not safari.exists():
        log("  Not installed (path not found)")
        return

    # Cookies
    delete_file(home / "Library/Cookies/Cookies.binarycookies")

    # History database
    for f in [
        safari / "History.db",
        safari / "History.db-shm",
        safari / "History.db-wal",
        safari / "HistoryIndex.sk",
        safari / "RecentlyClosedTabs.plist",
        safari / "RecentlyClosedWindows.plist",
    ]:
        delete_file(f)

    # Form auto-fill
    delete_file(safari / "Form Values")

    # Saved passwords (Keychain; Python can't touch it — note only)
    if ARGS.passwords:
        log("  Note: Safari passwords live in macOS Keychain — delete them via Keychain Access or Safari > Settings > Passwords.")

    # Cache
    if not ARGS.no_cache:
        delete_dir(home / "Library/Caches/com.apple.Safari")

    # WebKit storage
    delete_dir(home / "Library/WebKit/com.apple.Safari")


# ── OS detection & path layout ────────────────────────────────────────────────

def get_browser_map():
    system = platform.system()
    home = Path.home()

    if system == "Darwin":
        app = home / "Library/Application Support"
        return {
            "chromium": {
                "Google Chrome":   app / "Google/Chrome",
                "Brave":           app / "BraveSoftware/Brave-Browser",
                "Chromium":        app / "Chromium",
                "Microsoft Edge":  app / "Microsoft Edge",
                "Opera":           app / "com.operasoftware.Opera",
                "Vivaldi":         app / "Vivaldi",
                "Arc":             app / "Arc/User Data",
            },
            "firefox": {
                "Firefox":         app / "Firefox",
                "LibreWolf":       app / "librewolf",
                "Waterfox":        app / "Waterfox",
                "Floorp":          app / "Floorp",
                "Zen Browser":     app / "Zen Browser",
                "Pale Moon":       app / "Moonchild Productions/Pale Moon",
                "Basilisk":        app / "Moonchild Productions/Basilisk",
            },
            "safari": home,
            "system": "macos",
        }

    elif system == "Windows":
        local  = Path(os.environ.get("LOCALAPPDATA",  home / "AppData/Local"))
        roaming = Path(os.environ.get("APPDATA",      home / "AppData/Roaming"))
        return {
            "chromium": {
                "Google Chrome":   local  / "Google/Chrome/User Data",
                "Brave":           local  / "BraveSoftware/Brave-Browser/User Data",
                "Chromium":        local  / "Chromium/User Data",
                "Microsoft Edge":  local  / "Microsoft/Edge/User Data",
                "Opera":           roaming / "Opera Software/Opera Stable",
                "Vivaldi":         local  / "Vivaldi/User Data",
                "Arc":             local  / "Arc/User Data",
            },
            "firefox": {
                "Firefox":         roaming / "Mozilla/Firefox",
                "LibreWolf":       roaming / "librewolf",
                "Waterfox":        roaming / "Waterfox",
                "Floorp":          roaming / "Floorp",
                "Zen Browser":     roaming / "Zen Browser",
                "Pale Moon":       roaming / "Moonchild Productions/Pale Moon",
                "Basilisk":        roaming / "Moonchild Productions/Basilisk",
            },
            "safari": None,
            "system": "windows",
        }

    elif system == "Linux":
        cfg = home / ".config"
        return {
            "chromium": {
                "Google Chrome":   cfg / "google-chrome",
                "Brave":           cfg / "BraveSoftware/Brave-Browser",
                "Chromium":        cfg / "chromium",
                "Microsoft Edge":  cfg / "microsoft-edge",
                "Opera":           cfg / "opera",
                "Vivaldi":         cfg / "vivaldi",
            },
            "firefox": {
                "Firefox":                  home / ".mozilla/firefox",
                "LibreWolf":                home / ".librewolf",
                "Waterfox":                 home / ".waterfox",
                "Floorp":                   home / ".floorp",
                "Zen Browser":              home / ".zen",
                "Pale Moon":                home / ".moonchild productions/pale moon",
                "Basilisk":                 home / ".moonchild productions/basilisk",
                "Firefox (Snap)":           home / "snap/firefox/common/.mozilla/firefox",
                "Firefox (Flatpak)":        home / ".var/app/org.mozilla.firefox/.mozilla/firefox",
                "Brave (Flatpak)":          None,   # handled in chromium via cfg above
                "LibreWolf (Flatpak)":      home / ".var/app/io.gitlab.librewolf-community/.librewolf",
            },
            "safari": None,
            "system": "linux",
        }

    else:
        return None


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    global ARGS
    ARGS = parse_args()

    browser_map = get_browser_map()
    if browser_map is None:
        print(f"Unsupported OS: {platform.system()}")
        sys.exit(1)

    print("=" * 60)
    print("Browser Data Cleaner")
    print(f"OS      : {platform.system()} {platform.release()}")
    print(f"Home    : {Path.home()}")
    print(f"Mode    : {'DRY RUN — no files will be changed' if ARGS.dry_run else 'LIVE'}")
    print(f"Cache   : {'skip' if ARGS.no_cache else 'delete'}")
    print(f"Passwords: {'DELETE' if ARGS.passwords else 'keep'}")
    print("=" * 60)
    print("\nThis will clear: cookies, history, search history, cache,")
    print("form auto-fill data, and session storage.")
    if ARGS.passwords:
        print("WARNING: Saved passwords will also be deleted!")
    print("\nClose all browsers before continuing for best results.")

    if not ARGS.yes and not ARGS.dry_run:
        answer = input("\nProceed? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            sys.exit(0)

    # Chromium-based
    for name, path in browser_map["chromium"].items():
        if path is not None:
            clear_chromium(name, path)

    # Firefox-based
    for name, path in browser_map["firefox"].items():
        if path is not None:
            clear_firefox(name, path)

    # Safari
    if browser_map.get("safari"):
        clear_safari(browser_map["safari"])

    print("\n" + "=" * 60)
    if ARGS.dry_run:
        print("Dry run complete — no files were changed.")
    else:
        print("Done! Restart your browsers to apply changes.")
    print("=" * 60)


if __name__ == "__main__":
    main()
