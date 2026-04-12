"""Select tmdb poster config."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LibrarySelectionState:
    """Represents the library selection state for the TUI.

    all_libraries:
        When True, the scan should operate on all movie/show libraries and the
        selected_libraries list is ignored.
    selected_libraries:
        Explicitly selected library titles. When this list is empty the
        all_libraries flag is treated as the source of truth.
    """

    all_libraries: bool
    selected_libraries: list[str]


def toggle_library_selection(
    state: LibrarySelectionState, library_name: str, all_label: str = "ALL"
) -> LibrarySelectionState:
    """Toggle selection state for a library or the synthetic "all libraries" row.

    Behaviour rules (validated by tests):
    * Selecting any specific library disables all_libraries.
    * Selecting multiple libraries accumulates them in selected_libraries.
    * Unselecting the last specific library reverts back to all_libraries=True.
    * Selecting the synthetic all_label row forces all_libraries=True and clears
        any specific selections.
    """
    # Selecting the synthetic "all" row always wins and clears specifics.
    if library_name == all_label:
        return LibrarySelectionState(all_libraries=True, selected_libraries=[])

    selected = list(state.selected_libraries)

    if library_name in selected:
        selected.remove(library_name)
    else:
        selected.append(library_name)

    if not selected:
        # No specific libraries selected; fall back to "all libraries".
        return LibrarySelectionState(all_libraries=True, selected_libraries=[])

    return LibrarySelectionState(all_libraries=False, selected_libraries=selected)


def should_use_tui(argv: list[str]) -> bool:
    """Return True when the TUI should be launched.

    Current rule: if the script is invoked without any additional arguments,
    we prefer the interactive TUI. Any flags/arguments imply non-interactive
    CLI mode (for Tautulli/automation), and the caller is responsible for
    providing a complete configuration via flags.
    """
    # argv[0] is the script; any additional elements indicate CLI flags.
    return len(argv) <= 1
