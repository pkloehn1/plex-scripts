"""Select tmdb poster tui."""

from __future__ import annotations

from dataclasses import dataclass

import urwid
from plexapi.server import PlexServer

from plex_scripts.tmdb import select_tmdb_poster as core
from plex_scripts.tmdb.select_tmdb_poster_config import LibrarySelectionState, toggle_library_selection

ALL_LABEL = "All movie/show libraries"


@dataclass
class TuiState:
    """State container for the TUI application."""

    library_state: LibrarySelectionState
    include_locked: bool = False
    poster: bool = True
    art: bool = True
    poster_providers: list[str] | None = None
    art_providers: list[str] | None = None
    verbose: bool = False
    workers: int = 4


class SelectTmdbPosterTUI:
    """Terminal User Interface for selecting TMDB posters."""

    def __init__(self, plex: PlexServer) -> None:
        """Initialize the TUI with a Plex server connection."""
        self.plex = plex
        library_titles = [lib.title for lib in plex.library.sections() if lib.type in ["movie", "show"]]
        self.providers: list[str] = [
            "tmdb",
            "tvdb",
            "imdb",
            "fanarttv",
            "gracenote",
            "plex",
        ]
        default_order = ["tmdb", "tvdb", "imdb"]
        self.state = TuiState(
            library_state=LibrarySelectionState(all_libraries=True, selected_libraries=[]),
            poster_providers=list(default_order),
            art_providers=list(default_order),
        )
        self.library_titles: list[str] = library_titles
        self._run_selected = False

        self.header = urwid.Text("TMDB Poster Selector - TUI", align="center")
        self.footer = urwid.Text("Use arrow keys, Enter to select, Q to quit.")
        self.main_menu = self._build_main_menu()
        self.frame = urwid.Frame(self.main_menu, header=self.header, footer=self.footer)

    # ---- main loop -----------------------------------------------------
    def run(self) -> None:
        """Start the main event loop."""
        loop = urwid.MainLoop(self.frame, unhandled_input=self.unhandled_input)
        loop.run()
        if self._run_selected:
            self._execute_scan()

    def unhandled_input(self, key: str) -> None:
        """Handle global input keys like Quit."""
        if key in ("q", "Q", "esc"):
            raise urwid.ExitMainLoop()

    # ---- main menu -----------------------------------------------------
    def _build_main_menu(self) -> urwid.Widget:
        items = []
        for label, handler in (
            ("Library selection", self.open_library_screen),
            ("Poster options", self.open_poster_screen),
            ("Art options", self.open_art_screen),
            ("Sources ordering", self.open_sources_screen),
            ("Advanced", self.open_advanced_screen),
            ("Run", self._run_and_exit),
        ):
            button = urwid.Button(label)
            urwid.connect_signal(button, "click", lambda _, h=handler: h())
            items.append(urwid.AttrMap(button, None, focus_map="reversed"))
        listbox = urwid.ListBox(urwid.SimpleFocusListWalker(items))
        return urwid.Padding(listbox, left=2, right=2)

    def _back_to_main(self, _button: urwid.Button | None = None) -> None:
        self.frame.body = self.main_menu

    # ---- library selection ---------------------------------------------
    def open_library_screen(self) -> None:
        """Display the library selection screen."""
        widgets = []

        all_checkbox = urwid.CheckBox(ALL_LABEL, state=self.state.library_state.all_libraries)
        urwid.connect_signal(all_checkbox, "change", self._on_library_checkbox_change, ALL_LABEL)
        widgets.append(all_checkbox)

        for title in self.library_titles:
            checked = (
                not self.state.library_state.all_libraries and title in self.state.library_state.selected_libraries
            )
            cb = urwid.CheckBox(title, state=checked)
            urwid.connect_signal(cb, "change", self._on_library_checkbox_change, title)
            widgets.append(cb)

        widgets.append(urwid.Divider())
        back_btn = urwid.Button("Back")
        urwid.connect_signal(back_btn, "click", self._back_to_main)
        widgets.append(back_btn)

        listbox = urwid.ListBox(urwid.SimpleFocusListWalker(widgets))
        self.frame.body = urwid.Padding(listbox, left=2, right=2)

    def _on_library_checkbox_change(self, checkbox: urwid.CheckBox, new_state: bool, label: str) -> None:
        if not new_state and label == ALL_LABEL:
            # Ignore unchecking of ALL; logic handled via specific boxes
            return
        self.state.library_state = toggle_library_selection(self.state.library_state, label, ALL_LABEL)
        # Ensure visual state is consistent: rebuild screen
        self.open_library_screen()

    # ---- poster options ------------------------------------------------
    def open_poster_screen(self) -> None:
        """Display the poster options screen."""
        widgets = []
        cb = urwid.CheckBox("Update posters", state=self.state.poster)
        urwid.connect_signal(cb, "change", self._set_poster_flag)
        widgets.append(cb)

        widgets.append(urwid.Divider())
        back_btn = urwid.Button("Back")
        urwid.connect_signal(back_btn, "click", self._back_to_main)
        widgets.append(back_btn)

        self.frame.body = urwid.Padding(urwid.ListBox(urwid.SimpleFocusListWalker(widgets)), left=2, right=2)

    def _set_poster_flag(self, _checkbox: urwid.CheckBox, state: bool) -> None:
        self.state.poster = state

    # ---- art options ---------------------------------------------------
    def open_art_screen(self) -> None:
        """Display the art options screen."""
        widgets = []
        cb = urwid.CheckBox("Update art", state=self.state.art)
        urwid.connect_signal(cb, "change", self._set_art_flag)
        widgets.append(cb)

        widgets.append(urwid.Divider())
        back_btn = urwid.Button("Back")
        urwid.connect_signal(back_btn, "click", self._back_to_main)
        widgets.append(back_btn)

        self.frame.body = urwid.Padding(urwid.ListBox(urwid.SimpleFocusListWalker(widgets)), left=2, right=2)

    def _set_art_flag(self, _checkbox: urwid.CheckBox, state: bool) -> None:
        self.state.art = state

    # ---- sources ordering ----------------------------------------------
    def open_sources_screen(self) -> None:
        """Display the source provider ordering screen."""
        widgets = [
            urwid.Text(
                "Set provider priority (1 = first choice). Leave 0 to skip a provider.",
            ),
            urwid.Divider(),
            urwid.Text("Poster providers:"),
        ]

        self.poster_order_edits: dict[str, urwid.IntEdit] = {}
        for name in self.providers:
            current_pos = self._get_provider_position(self.state.poster_providers, name)
            edit = urwid.IntEdit(f"{name:>10}: ", current_pos or 0)
            self.poster_order_edits[name] = edit
            widgets.append(edit)

        widgets.append(urwid.Divider())
        widgets.append(urwid.Text("Art providers:"))

        self.art_order_edits: dict[str, urwid.IntEdit] = {}
        for name in self.providers:
            current_pos = self._get_provider_position(self.state.art_providers, name)
            edit = urwid.IntEdit(f"{name:>10}: ", current_pos or 0)
            self.art_order_edits[name] = edit
            widgets.append(edit)

        widgets.append(urwid.Divider())
        back_btn = urwid.Button("Back")
        urwid.connect_signal(back_btn, "click", self._apply_sources_and_back)
        widgets.append(back_btn)

        self.frame.body = urwid.Padding(urwid.ListBox(urwid.SimpleFocusListWalker(widgets)), left=2, right=2)

    def _get_provider_position(self, ordered: list[str] | None, name: str) -> int:
        if not ordered or name not in ordered:
            return 0
        return ordered.index(name) + 1

    def _apply_sources_and_back(self, _button: urwid.Button) -> None:
        self.state.poster_providers = self._ordered_from_edits(self.poster_order_edits)
        self.state.art_providers = self._ordered_from_edits(self.art_order_edits)
        self._back_to_main()

    def _ordered_from_edits(self, edits: dict[str, urwid.IntEdit]) -> list[str]:
        positions: list[tuple[int, str]] = []
        for name, edit in edits.items():
            try:
                value = int(edit.edit_text)
            except ValueError:
                continue
            if value > 0:
                positions.append((value, name))

        # Sort by chosen priority, then stable provider order for ties
        positions.sort(key=lambda item: (item[0], self.providers.index(item[1])))
        ordered = [name for value, name in positions]

        # At most six choices are meaningful
        return ordered[:6]

    # ---- advanced ------------------------------------------------------
    def open_advanced_screen(self) -> None:
        """Display the advanced options screen."""
        widgets = []

        include_cb = urwid.CheckBox("Include locked items", state=self.state.include_locked)
        urwid.connect_signal(include_cb, "change", self._set_include_locked)
        widgets.append(include_cb)

        verbose_cb = urwid.CheckBox("Verbose output", state=self.state.verbose)
        urwid.connect_signal(verbose_cb, "change", self._set_verbose)
        widgets.append(verbose_cb)

        widgets.append(urwid.Divider())
        widgets.append(urwid.Text("Worker threads (1-8):"))
        self.workers_edit = urwid.IntEdit("Count: ", self.state.workers)
        widgets.append(self.workers_edit)

        widgets.append(urwid.Divider())
        back_btn = urwid.Button("Back")
        urwid.connect_signal(back_btn, "click", self._apply_advanced_and_back)
        widgets.append(back_btn)

        self.frame.body = urwid.Padding(urwid.ListBox(urwid.SimpleFocusListWalker(widgets)), left=2, right=2)

    def _set_include_locked(self, _checkbox: urwid.CheckBox, state: bool) -> None:
        self.state.include_locked = state

    def _set_verbose(self, _checkbox: urwid.CheckBox, state: bool) -> None:
        self.state.verbose = state

    def _apply_advanced_and_back(self, _button: urwid.Button) -> None:
        try:
            value = int(self.workers_edit.edit_text)
            if value < 1:
                value = 1
            elif value > 8:
                value = 8
            self.state.workers = value
        except ValueError:
            # Keep existing value if input is invalid
            pass
        self._back_to_main()

    # ---- run -----------------------------------------------------------
    def _run_and_exit(self) -> None:
        self._run_selected = True
        raise urwid.ExitMainLoop()

    def _execute_scan(self) -> None:
        # Map library selection state to actual Plex libraries
        if self.state.library_state.all_libraries:
            libraries = [lib for lib in self.plex.library.sections() if lib.type in ["movie", "show"]]
        else:
            libraries = [self.plex.library.section(name) for name in self.state.library_state.selected_libraries]

        core.VERBOSE = self.state.verbose
        core.process_libraries(
            libraries,
            include_locked=self.state.include_locked,
            poster=self.state.poster,
            poster_provider=self.state.poster_providers or [core.PREFERRED_POSTER_PROVIDER],
            art=self.state.art,
            art_provider=self.state.art_providers or [core.PREFERRED_ART_PROVIDER],
            max_workers=self.state.workers,
        )


def run_tui(plex: PlexServer) -> None:
    """Run tui."""
    app = SelectTmdbPosterTUI(plex)
    app.run()
