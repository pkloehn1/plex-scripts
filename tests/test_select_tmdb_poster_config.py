"""Test select tmdb poster config."""

import unittest


class LibrarySelectionState:
    """Simple state container used by tests; mirrored in select_tmdb_poster_config.

    This avoids importing the real implementation before it exists and keeps the
    tests focused on behaviour rather than concrete dataclass mechanics.
    """

    def __init__(self, all_libraries: bool, selected_libraries: list[str] | None = None) -> None:
        """Initialize LibrarySelectionState."""
        self.all_libraries = all_libraries
        self.selected_libraries = selected_libraries or []


class SelectTmdbPosterConfigTests(unittest.TestCase):
    """Select Tmdb Poster Config Tests."""

    def setUp(self) -> None:
        # Import lazily so the module can be created after this test file
        """Set Up."""
        from plex_scripts.tmdb import select_tmdb_poster_config as config

        self.config = config

    def test_selecting_specific_library_disables_all_libraries_flag(self) -> None:
        """Test selecting specific library disables all libraries flag."""
        state = self.config.LibrarySelectionState(all_libraries=True, selected_libraries=[])

        new_state = self.config.toggle_library_selection(state, "Movies", all_label="ALL")

        self.assertFalse(new_state.all_libraries)
        self.assertEqual(["Movies"], new_state.selected_libraries)

    def test_selecting_multiple_libraries_keeps_all_unset(self) -> None:
        """Test selecting multiple libraries keeps all unset."""
        state = self.config.LibrarySelectionState(all_libraries=True, selected_libraries=[])

        state = self.config.toggle_library_selection(state, "Movies", all_label="ALL")
        state = self.config.toggle_library_selection(state, "TV", all_label="ALL")

        self.assertFalse(state.all_libraries)
        self.assertCountEqual(["Movies", "TV"], state.selected_libraries)

    def test_unselecting_last_library_reverts_to_all_libraries(self) -> None:
        """Test unselecting last library reverts to all libraries."""
        state = self.config.LibrarySelectionState(all_libraries=False, selected_libraries=["Movies"])

        new_state = self.config.toggle_library_selection(state, "Movies", all_label="ALL")

        self.assertTrue(new_state.all_libraries)
        self.assertEqual([], new_state.selected_libraries)

    def test_selecting_all_option_clears_specific_libraries(self) -> None:
        """Test selecting all option clears specific libraries."""
        state = self.config.LibrarySelectionState(all_libraries=False, selected_libraries=["Movies", "TV"])

        new_state = self.config.toggle_library_selection(state, "ALL", all_label="ALL")

        self.assertTrue(new_state.all_libraries)
        self.assertEqual([], new_state.selected_libraries)

    def test_should_use_tui_with_no_arguments(self) -> None:
        """Test should use tui with no arguments."""
        self.assertTrue(self.config.should_use_tui(["select_tmdb_poster.py"]))

    def test_should_not_use_tui_when_flags_are_present(self) -> None:
        """Test should not use tui when flags are present."""
        self.assertFalse(self.config.should_use_tui(["select_tmdb_poster.py", "--poster"]))
        self.assertFalse(self.config.should_use_tui(["select_tmdb_poster.py", "--library", "Movies"]))


if __name__ == "__main__":  # pragma: no cover - manual invocation helper
    unittest.main()
