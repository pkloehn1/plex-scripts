"""Test select tmdb poster tui."""

import types
import unittest
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("urwid")

import urwid

from plex_scripts.tmdb.select_tmdb_poster_tui import ALL_LABEL, SelectTmdbPosterTUI, run_tui


def _make_plex(library_titles=("Movies",)):
    """Build a mock Plex server exposing the given movie libraries."""
    plex = MagicMock()
    sections = []
    for title in library_titles:
        section = MagicMock()
        section.title = title
        section.type = "movie"
        sections.append(section)
    plex.library.sections.return_value = sections
    return plex


class TestSelectTmdbPosterTUI(unittest.TestCase):
    """Test Select Tmdb Poster TUI."""

    def setUp(self):
        """Build a TUI backed by a mock Plex server."""
        self.mock_plex = _make_plex(["Movies"])
        self.tui = SelectTmdbPosterTUI(self.mock_plex)

    # ---- construction / main loop --------------------------------------
    def test_init(self):
        """TUI initialization wires up the frame and menu."""
        self.assertEqual(self.tui.plex, self.mock_plex)
        self.assertIsInstance(self.tui.main_menu, urwid.Padding)
        self.assertIsInstance(self.tui.frame, urwid.Frame)

    def test_build_main_menu(self):
        """The main menu lists the expected actions."""
        menu = self.tui._build_main_menu()
        self.assertIsInstance(menu, urwid.Padding)
        listbox = menu.original_widget
        self.assertIsInstance(listbox, urwid.ListBox)

        labels = []
        for widget in listbox.body:
            if isinstance(widget, urwid.AttrMap) and isinstance(widget.original_widget, urwid.Button):
                labels.append(widget.original_widget.label)

        self.assertIn("Library selection", labels)
        self.assertIn("Run", labels)

    @patch("plex_scripts.tmdb.select_tmdb_poster_tui.urwid.MainLoop")
    def test_run_without_scan(self, mock_loop_cls):
        """Start the loop and skip the scan when not requested."""
        mock_loop_instance = MagicMock()
        mock_loop_cls.return_value = mock_loop_instance

        with patch.object(self.tui, "_execute_scan") as mock_scan:
            self.tui.run()

        mock_loop_cls.assert_called_once()
        mock_loop_instance.run.assert_called_once()
        mock_scan.assert_not_called()

    @patch("plex_scripts.tmdb.select_tmdb_poster_tui.urwid.MainLoop")
    def test_run_executes_scan_when_selected(self, _mock_loop_cls):
        """Trigger the scan when Run was chosen."""
        self.tui._run_selected = True
        with patch.object(self.tui, "_execute_scan") as mock_scan:
            self.tui.run()
        mock_scan.assert_called_once()

    def test_unhandled_input_quit(self):
        """Quit keys raise ExitMainLoop."""
        for key in ("q", "Q", "esc"):
            with self.assertRaises(urwid.ExitMainLoop):
                self.tui.unhandled_input(key)

    def test_unhandled_input_other_key_ignored(self):
        """Non-quit keys are ignored."""
        self.assertIsNone(self.tui.unhandled_input("a"))

    def test_back_to_main(self):
        """_back_to_main restores the main menu body."""
        self.tui.open_poster_screen()
        self.tui._back_to_main()
        self.assertIs(self.tui.frame.body, self.tui.main_menu)

    # ---- library selection ---------------------------------------------
    def test_open_library_screen(self):
        """The library screen renders with the current selection."""
        self.tui.state.library_state.all_libraries = False
        self.tui.state.library_state.selected_libraries = ["Movies"]
        self.tui.open_library_screen()
        self.assertIsInstance(self.tui.frame.body, urwid.Padding)

    def test_library_checkbox_uncheck_all_ignored(self):
        """Unchecking the synthetic ALL row is a no-op."""
        before = self.tui.state.library_state
        self.tui._on_library_checkbox_change(MagicMock(), False, ALL_LABEL)
        self.assertIs(self.tui.state.library_state, before)

    def test_library_checkbox_toggle_specific(self):
        """Toggling a specific library updates the selection state."""
        self.tui._on_library_checkbox_change(MagicMock(), True, "Movies")
        self.assertFalse(self.tui.state.library_state.all_libraries)
        self.assertIn("Movies", self.tui.state.library_state.selected_libraries)

    # ---- poster / art options ------------------------------------------
    def test_open_poster_screen_and_flag(self):
        """Poster screen renders and the flag setter updates state."""
        self.tui.open_poster_screen()
        self.assertIsInstance(self.tui.frame.body, urwid.Padding)
        self.tui._set_poster_flag(MagicMock(), False)
        self.assertFalse(self.tui.state.poster)

    def test_open_art_screen_and_flag(self):
        """Art screen renders and the flag setter updates state."""
        self.tui.open_art_screen()
        self.assertIsInstance(self.tui.frame.body, urwid.Padding)
        self.tui._set_art_flag(MagicMock(), False)
        self.assertFalse(self.tui.state.art)

    # ---- sources ordering ----------------------------------------------
    def test_open_sources_screen(self):
        """The sources screen builds an edit per provider."""
        self.tui.open_sources_screen()
        self.assertIsInstance(self.tui.frame.body, urwid.Padding)
        self.assertEqual(set(self.tui.poster_order_edits), set(self.tui.providers))

    def test_get_provider_position(self):
        """Provider position is 1-based, or zero when absent."""
        self.assertEqual(self.tui._get_provider_position(None, "tmdb"), 0)
        self.assertEqual(self.tui._get_provider_position(["tmdb", "tvdb"], "tvdb"), 2)
        self.assertEqual(self.tui._get_provider_position(["tmdb"], "imdb"), 0)

    def test_apply_sources_and_back(self):
        """Applying sources stores the ordered providers and returns to menu."""
        self.tui.open_sources_screen()
        self.tui._apply_sources_and_back(MagicMock())
        self.assertIs(self.tui.frame.body, self.tui.main_menu)

    def test_ordered_from_edits(self):
        """Edits are ordered by priority, ignoring zero and invalid values."""
        edits = {
            "tmdb": types.SimpleNamespace(edit_text="2"),
            "tvdb": types.SimpleNamespace(edit_text="1"),
            "imdb": types.SimpleNamespace(edit_text="0"),
            "fanarttv": types.SimpleNamespace(edit_text="bad"),
        }
        self.assertEqual(self.tui._ordered_from_edits(edits), ["tvdb", "tmdb"])

    # ---- advanced ------------------------------------------------------
    def test_open_advanced_screen_and_setters(self):
        """Advanced screen renders and toggles update state."""
        self.tui.open_advanced_screen()
        self.assertIsInstance(self.tui.frame.body, urwid.Padding)
        self.tui._set_include_locked(MagicMock(), True)
        self.tui._set_verbose(MagicMock(), True)
        self.assertTrue(self.tui.state.include_locked)
        self.assertTrue(self.tui.state.verbose)

    def test_apply_advanced_workers_in_range(self):
        """A valid worker count is stored as-is."""
        self.tui.workers_edit = types.SimpleNamespace(edit_text="5")
        self.tui._apply_advanced_and_back(MagicMock())
        self.assertEqual(self.tui.state.workers, 5)

    def test_apply_advanced_workers_clamped_low(self):
        """A worker count below one is clamped up."""
        self.tui.workers_edit = types.SimpleNamespace(edit_text="0")
        self.tui._apply_advanced_and_back(MagicMock())
        self.assertEqual(self.tui.state.workers, 1)

    def test_apply_advanced_workers_clamped_high(self):
        """A worker count above eight is clamped down."""
        self.tui.workers_edit = types.SimpleNamespace(edit_text="20")
        self.tui._apply_advanced_and_back(MagicMock())
        self.assertEqual(self.tui.state.workers, 8)

    def test_apply_advanced_workers_invalid_kept(self):
        """An invalid worker count leaves the existing value untouched."""
        self.tui.state.workers = 4
        self.tui.workers_edit = types.SimpleNamespace(edit_text="bad")
        self.tui._apply_advanced_and_back(MagicMock())
        self.assertEqual(self.tui.state.workers, 4)

    # ---- run / execute -------------------------------------------------
    def test_run_and_exit(self):
        """Choosing Run flags the scan and exits the loop."""
        with self.assertRaises(urwid.ExitMainLoop):
            self.tui._run_and_exit()
        self.assertTrue(self.tui._run_selected)

    def test_execute_scan_all_libraries(self):
        """Executing with all-libraries dispatches every movie/show library."""
        with patch("plex_scripts.tmdb.select_tmdb_poster.process_libraries") as mock_process:
            self.tui._execute_scan()
        mock_process.assert_called_once()
        libraries = mock_process.call_args.args[0]
        self.assertEqual(len(libraries), 1)

    def test_execute_scan_selected_libraries(self):
        """Executing with explicit selections resolves each named library."""
        self.tui.state.library_state.all_libraries = False
        self.tui.state.library_state.selected_libraries = ["Movies"]
        section = MagicMock()
        self.mock_plex.library.section.return_value = section
        with patch("plex_scripts.tmdb.select_tmdb_poster.process_libraries") as mock_process:
            self.tui._execute_scan()
        mock_process.assert_called_once()
        self.mock_plex.library.section.assert_called_once_with("Movies")


class TestRunTui(unittest.TestCase):
    """The run_tui entry point."""

    @patch("plex_scripts.tmdb.select_tmdb_poster_tui.urwid.MainLoop")
    def test_run_tui_builds_and_runs(self, mock_loop_cls):
        """run_tui constructs the app and starts its loop."""
        mock_loop_instance = MagicMock()
        mock_loop_cls.return_value = mock_loop_instance
        run_tui(_make_plex(["Movies"]))
        mock_loop_instance.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
