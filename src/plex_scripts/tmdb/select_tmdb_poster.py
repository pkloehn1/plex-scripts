#!/usr/bin/env python

"""Select TMDB posters and art for items in a Plex library.

Original author: /u/SwiftPanda16
Requires: plexapi

Examples (CLI mode):
    python select_tmdb_poster.py --library "Movies" --poster --art
    python select_tmdb_poster.py --rating_key 1234 --poster

For full options run: python select_tmdb_poster.py --help
"""

import argparse
import os
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import plexapi.base
from plexapi.server import PlexServer

plexapi.base.USER_DONT_RELOAD_FOR_KEYS.add("fields")


# Poster and art providers to replace
REPLACE_PROVIDERS = ["gracenote", "plex", None]

# Preferred poster and art provider to use (Note not all providers are availble for all items)
# Possible options: tmdb, tvdb, imdb, fanarttv, gracenote, plex
PREFERRED_POSTER_PROVIDER = "tmdb"
PREFERRED_ART_PROVIDER = "tmdb"


# ## OVERRIDES - ONLY EDIT IF RUNNING SCRIPT WITHOUT TAUTULLI ##

PLEX_URL = ""
PLEX_TOKEN = ""

# Environmental Variables
PLEX_URL = PLEX_URL or os.getenv("PLEX_URL", PLEX_URL)
PLEX_TOKEN = PLEX_TOKEN or os.getenv("PLEX_TOKEN", PLEX_TOKEN)

# Global statistics tracking
stats = {}
errors = []

VERBOSE = False
PROGRESS_BAR_WIDTH = 30

progress_lock = threading.Lock()
stats_lock = threading.Lock()
errors_lock = threading.Lock()
library_progress: dict[str, dict[str, int]] = {}
progress_line_count = 0


def vprint(*args: object, **kwargs: Any) -> None:
    """Vprint."""
    if VERBOSE:
        print(*args, **kwargs)


def _make_progress_bar(percentage: float) -> str:
    percentage = max(0.0, min(percentage, 100.0))
    filled_length = int(PROGRESS_BAR_WIDTH * (percentage / 100.0))
    bar = "#" * filled_length + "." * (PROGRESS_BAR_WIDTH - filled_length)
    return f"[{bar}]"


def _render_progress_locked() -> None:
    """Render the overall and per-library progress bars.

    This function assumes progress_lock is already held.
    """
    global progress_line_count

    if not library_progress:
        return

    overall_total = sum(data["total"] for data in library_progress.values())
    overall_processed = sum(data["processed"] for data in library_progress.values())
    overall_pct = (overall_processed / overall_total * 100.0) if overall_total else 0.0

    lines = []
    lines.append(
        f"Overall   {_make_progress_bar(overall_pct)} {overall_pct:5.1f}% ({overall_processed}/{overall_total})",
    )

    for name, data in library_progress.items():
        pct = (data["processed"] / data["total"] * 100.0) if data["total"] else 0.0
        truncated = name if len(name) <= 20 else name[:17] + "..."
        lines.append(f"{truncated:<20} {_make_progress_bar(pct)} {pct:5.1f}% ({data['processed']}/{data['total']})")

    # Move cursor up to the beginning of the previous progress block and clear it
    if progress_line_count:
        sys.stdout.write(f"\x1b[{progress_line_count}F")  # Move up N lines to column 0
        sys.stdout.write("\x1b[J")  # Clear from cursor to end of screen

    for line in lines:
        sys.stdout.write(line + "\n")
    sys.stdout.flush()

    progress_line_count = len(lines)


def init_progress(library_totals: dict[str, int]) -> None:
    """Initialize progress tracking for the given libraries.

    library_totals: mapping of library name -> total top-level items to process.
    """
    with progress_lock:
        library_progress.clear()
        for name, total in library_totals.items():
            library_progress[name] = {"total": int(total), "processed": 0}
        _render_progress_locked()


def update_progress(library_name: str, step: int = 1) -> None:
    """Increment progress for a specific library and redraw the bars."""
    with progress_lock:
        data = library_progress.get(library_name)
        if not data:
            return
        data["processed"] = min(data["processed"] + step, data["total"])
        _render_progress_locked()


def clear_progress_display() -> None:
    """Clear the progress display block from the terminal."""
    global progress_line_count

    with progress_lock:
        if progress_line_count:
            sys.stdout.write(f"\x1b[{progress_line_count}F")
            sys.stdout.write("\x1b[J")
            sys.stdout.flush()
            progress_line_count = 0


def select_library(
    library: Any,
    items: list[Any],
    include_locked: bool = False,
    poster: bool = False,
    poster_provider: str | list[str] = PREFERRED_POSTER_PROVIDER,
    art: bool = False,
    art_provider: str | list[str] = PREFERRED_ART_PROVIDER,
) -> None:
    """Process all items in a Plex library, updating poster/art as requested.

    Progress for the library is tracked via update_progress and should be
    initialized by init_progress() before calling this function.
    """
    for item in items:
        # Only reload for fields
        item.reload(**{include_key: 0 for include_key, include_value in item._INCLUDES.items()})
        select_item(
            item,
            include_locked=include_locked,
            poster=poster,
            poster_provider=poster_provider,
            art=art,
            art_provider=art_provider,
        )

        # Process seasons for TV Shows
        if hasattr(item, "seasons"):
            for season in item.seasons():
                vprint(f"Processing season: {season.title}")
                # Seasons typically have posters, not background art
                select_item(
                    season,
                    include_locked=include_locked,
                    poster=poster,
                    poster_provider=poster_provider,
                    art=False,
                    art_provider=art_provider,
                )

        update_progress(library.title)


def select_item(
    item: Any,
    include_locked: bool = False,
    poster: bool = False,
    poster_provider: str | list[str] = PREFERRED_POSTER_PROVIDER,
    art: bool = False,
    art_provider: str | list[str] = PREFERRED_ART_PROVIDER,
) -> None:
    """Select item."""
    library_name = item.librarySectionTitle

    # Initialize stats for this library if not exists and bump total count
    with stats_lock:
        if library_name not in stats:
            stats[library_name] = {
                "total": 0,
                "poster_updated": 0,
                "poster_locked": 0,
                "poster_skipped": 0,
                "art_updated": 0,
                "art_locked": 0,
                "art_skipped": 0,
                "errors": 0,
            }
        stats[library_name]["total"] += 1

    item_title = f"{item.title} ({item.year if hasattr(item, 'year') else 'N/A'})"
    vprint(f"{item_title}")

    if poster:
        try:
            result = select_poster(item, include_locked, poster_provider)
            if result == "updated":
                with stats_lock:
                    stats[library_name]["poster_updated"] += 1
            elif result == "locked":
                with stats_lock:
                    stats[library_name]["poster_locked"] += 1
            elif result == "skipped":
                with stats_lock:
                    stats[library_name]["poster_skipped"] += 1
        except Exception as exception:
            with stats_lock:
                stats[library_name]["errors"] += 1
            with errors_lock:
                errors.append(
                    {
                        "library": library_name,
                        "item": item_title,
                        "type": "poster",
                        "error": str(exception),
                    }
                )
            vprint(f"  - ERROR selecting poster: {exception}")

    if art:
        try:
            result = select_art(item, include_locked, art_provider)
            if result == "updated":
                with stats_lock:
                    stats[library_name]["art_updated"] += 1
            elif result == "locked":
                with stats_lock:
                    stats[library_name]["art_locked"] += 1
            elif result == "skipped":
                with stats_lock:
                    stats[library_name]["art_skipped"] += 1
        except Exception as exception:
            with stats_lock:
                stats[library_name]["errors"] += 1
            with errors_lock:
                errors.append(
                    {
                        "library": library_name,
                        "item": item_title,
                        "type": "art",
                        "error": str(exception),
                    }
                )
            vprint(f"  - ERROR selecting art: {exception}")


def select_poster(
    item: Any,
    include_locked: bool = False,
    provider: str | list[str] = PREFERRED_POSTER_PROVIDER,
) -> str:
    """Select poster."""
    vprint("  Checking poster...")

    if item.isLocked("thumb") and not include_locked:  # PlexAPI 4.5.10
        vprint(f"  - Locked poster for {item.title}. Skipping.")
        return "skipped"

    posters = item.posters()
    if not posters:
        vprint(f"  - WARNING: No available posters for {item.title}.")
        return "skipped"

    selected_poster = next((poster for poster in posters if poster.selected), None)

    if selected_poster is None:
        vprint(f"  - WARNING: No poster selected for {item.title}.")
    else:
        vprint(f"  - Poster provider is '{selected_poster.provider}' for {item.title}.")

        if selected_poster.provider in ["tmdb", "tvdb", "imdb"] and item.isLocked("thumb"):
            vprint(f"  - Already has locked {selected_poster.provider} poster. Skipping.")
            return "skipped"

    if selected_poster is None or selected_poster.provider in REPLACE_PROVIDERS:
        if isinstance(provider, list):
            candidates = provider
        else:
            candidates = [provider, "tvdb", "imdb"]

        seen = set()
        ordered_providers = []
        for name in candidates:
            if name and name not in seen:
                ordered_providers.append(name)
                seen.add(name)

        provider_poster = None
        for name in ordered_providers:
            provider_poster = next((poster for poster in posters if poster.provider == name), None)
            if provider_poster is not None:
                break

        if provider_poster is None:
            joined = ", ".join(ordered_providers)
            vprint(f"  - WARNING: No {joined} poster available for {item.title}. Skipping.")
            return "skipped"

        # Selecting the poster automatically locks it
        provider_poster.select()
        vprint(f"  - Selected and locked {provider_poster.provider} poster for {item.title}.")
        return "updated"

    item.lockPoster()
    vprint(f"  - Locked {selected_poster.provider} poster for {item.title}.")
    return "locked"


def select_art(
    item: Any,
    include_locked: bool = False,
    provider: str | list[str] = PREFERRED_ART_PROVIDER,
) -> str:
    """Select art."""
    vprint("  Checking art...")

    if item.isLocked("art") and not include_locked:  # PlexAPI 4.5.10
        vprint(f"  - Locked art for {item.title}. Skipping.")
        return "skipped"

    arts = item.arts()
    if not arts:
        vprint(f"  - WARNING: No available art for {item.title}.")
        return "skipped"

    selected_art = next((art for art in arts if art.selected), None)

    if selected_art is None:
        vprint(f"  - WARNING: No art selected for {item.title}.")
    else:
        vprint(f"  - Art provider is '{selected_art.provider}' for {item.title}.")

        if selected_art.provider in ["tmdb", "tvdb", "imdb"] and item.isLocked("art"):
            vprint(f"  - Already has locked {selected_art.provider} art. Skipping.")
            return "skipped"

    if selected_art is None or selected_art.provider in REPLACE_PROVIDERS:
        if isinstance(provider, list):
            candidates = provider
        else:
            candidates = [provider, "tvdb", "imdb"]

        seen = set()
        ordered_providers = []
        for name in candidates:
            if name and name not in seen:
                ordered_providers.append(name)
                seen.add(name)

        provider_art = None
        for name in ordered_providers:
            provider_art = next((art for art in arts if art.provider == name), None)
            if provider_art is not None:
                break

        if provider_art is None:
            joined = ", ".join(ordered_providers)
            vprint(f"  - WARNING: No {joined} art available for {item.title}. Skipping.")
            return "skipped"

        # Selecting the art automatically locks it
        provider_art.select()
        vprint(f"  - Selected and locked {provider_art.provider} art for {item.title}.")
        return "updated"

    item.lockArt()
    vprint(f"  - Locked {selected_art.provider} art for {item.title}.")
    return "locked"


def print_summary() -> None:
    """Print a simple end-of-run status and any errors."""
    if not errors:
        print("\nProcessing completed with no errors.")
        return

    print("\nErrors encountered during processing:")
    print("-" * 80)
    for error in errors:
        print(f"{error['library']}: {error['item']} [{error['type']}] {error['error']}")


def process_libraries(
    libraries: list[Any],
    include_locked: bool,
    poster: bool,
    poster_provider: str | list[str],
    art: bool,
    art_provider: str | list[str],
    max_workers: int = 4,
) -> None:
    """Process a collection of libraries with progress bars and threading."""
    if not libraries:
        print("No movie or show libraries found. Exiting.")
        return

    library_totals = {}
    library_items = {}
    for library in libraries:
        items = library.all(includeGuids=False)
        library_totals[library.title] = len(items)
        library_items[library.title] = items

    init_progress(library_totals)

    with ThreadPoolExecutor(max_workers=min(len(libraries), max_workers)) as executor:
        futures = [
            executor.submit(
                select_library,
                library,
                library_items[library.title],
                include_locked,
                poster,
                poster_provider,
                art,
                art_provider,
            )
            for library in libraries
        ]
        for future in futures:
            future.result()

    print_summary()


def _resolve_should_use_tui() -> Callable[[list[str]], bool]:
    """Import should_use_tui, supporting both module and direct-file launches.

    Under ``python -m plex_scripts.tmdb.select_tmdb_poster`` (or with the
    package installed) the package-qualified import resolves. When run as a
    loose file (shebang or an IDE "run" button) only the script's own
    directory is on sys.path, so fall back to the flat sibling import.
    """
    try:
        from plex_scripts.tmdb.select_tmdb_poster_config import should_use_tui
    except ImportError:
        from select_tmdb_poster_config import should_use_tui
    return should_use_tui


def _resolve_run_tui() -> Callable[[Any], None] | None:
    """Import run_tui across launch modes, or return None when unavailable.

    Returns None when neither the package nor the flat import succeeds, e.g.
    the optional ``urwid`` dependency is missing.
    """
    try:
        from plex_scripts.tmdb.select_tmdb_poster_tui import run_tui
    except ImportError:
        try:
            from select_tmdb_poster_tui import run_tui
        except ImportError:
            return None
    return run_tui


if __name__ == "__main__":
    if not PLEX_URL or not PLEX_TOKEN:
        print(
            (
                "Error: PLEX_URL and PLEX_TOKEN must be defined.\n"
                + "Set them as environment variables or edit the script overrides."
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    should_use_tui = _resolve_should_use_tui()

    if should_use_tui(sys.argv):
        run_tui = _resolve_run_tui()
        if run_tui is None:
            print(
                "Interactive TUI is not available. Install the 'urwid' package to use the menu interface.",
                file=sys.stderr,
            )
            sys.exit(1)

        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        run_tui(plex)
        sys.exit(0)

    parser = argparse.ArgumentParser()
    parser.add_argument("--rating_key", type=int)
    parser.add_argument("--library")
    parser.add_argument(
        "--all_libraries",
        action="store_true",
        help="Process all movie and show libraries",
    )
    parser.add_argument("--include_locked", action="store_true")
    parser.add_argument("--poster", action="store_true")
    parser.add_argument("--poster_provider", default=PREFERRED_POSTER_PROVIDER)
    parser.add_argument("--art", action="store_true")
    parser.add_argument("--art_provider", default=PREFERRED_ART_PROVIDER)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging of individual items and provider decisions.",
    )
    opts = parser.parse_args()

    VERBOSE = opts.verbose

    plex = PlexServer(PLEX_URL, PLEX_TOKEN)

    if opts.rating_key:
        item = plex.fetchItem(opts.rating_key)
        select_item(
            item,
            opts.include_locked,
            opts.poster,
            opts.poster_provider,
            opts.art,
            opts.art_provider,
        )
        print_summary()
    elif opts.library:
        library = plex.library.section(opts.library)
        items = library.all(includeGuids=False)
        init_progress({library.title: len(items)})
        select_library(
            library,
            items,
            include_locked=opts.include_locked,
            poster=opts.poster,
            poster_provider=opts.poster_provider,
            art=opts.art,
            art_provider=opts.art_provider,
        )
        print_summary()
    elif opts.all_libraries:
        libraries = [lib for lib in plex.library.sections() if lib.type in ["movie", "show"]]
        process_libraries(
            libraries,
            include_locked=opts.include_locked,
            poster=opts.poster,
            poster_provider=opts.poster_provider,
            art=opts.art,
            art_provider=opts.art_provider,
        )
    else:
        print("No --rating_key, --library, or --all_libraries specified. Exiting.")
