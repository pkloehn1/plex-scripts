"""Test select tmdb poster tui."""

import pytest

pytest.importorskip("urwid")

import unittest
from unittest.mock import MagicMock, patch

import urwid

from plex_scripts.tmdb.select_tmdb_poster_tui import SelectTmdbPosterTUI


class TestSelectTmdbPosterTUI(unittest.TestCase):
    """Test Select Tmdb Poster TUI."""

    def setUp(self):
        """Set Up."""
        self.mock_plex = MagicMock()
        # Mock library sections for init
        lib1 = MagicMock()
        lib1.title = "Movies"
        lib1.type = "movie"
        self.mock_plex.library.sections.return_value = [lib1]

        self.tui = SelectTmdbPosterTUI(self.mock_plex)

    def test_init(self):
        """Test TUI initialization."""
        self.assertEqual(self.tui.plex, self.mock_plex)
        self.assertIsInstance(self.tui.main_menu, urwid.Padding)
        self.assertIsInstance(self.tui.frame, urwid.Frame)

    def test_build_main_menu(self):
        """Test main menu creation."""
        menu = self.tui._build_main_menu()
        self.assertIsInstance(menu, urwid.Padding)
        listbox = menu.original_widget
        self.assertIsInstance(listbox, urwid.ListBox)

        # Verify menu items
        body = listbox.body
        # Check for button labels in the menu
        labels = []
        for w in body:
            if isinstance(w, urwid.AttrMap) and isinstance(w.original_widget, urwid.Button):
                labels.append(w.original_widget.label)

        self.assertIn("Library selection", labels)
        self.assertIn("Run", labels)

    @patch("select_tmdb_poster_tui.urwid.MainLoop")
    def test_run(self, mock_loop_cls):
        """Test run method starts the main loop."""
        mock_loop_instance = MagicMock()
        mock_loop_cls.return_value = mock_loop_instance

        self.tui.run()

        mock_loop_cls.assert_called_once()
        mock_loop_instance.run.assert_called_once()

    def test_open_library_screen(self):
        """Test opening library screen."""
        # Setup state
        self.tui.state.library_state.all_libraries = False
        self.tui.state.library_state.selected_libraries = ["Movies"]

        self.tui.open_library_screen()

        # Verify frame body updated
        self.assertNotEqual(self.tui.frame.body, self.tui.main_menu)
        # Should be a padding containing a listbox
        self.assertIsInstance(self.tui.frame.body, urwid.Padding)

    def test_unhandled_input_quit(self):
        """Test quit input handling."""
        with self.assertRaises(urwid.ExitMainLoop):
            self.tui.unhandled_input("q")

        with self.assertRaises(urwid.ExitMainLoop):
            self.tui.unhandled_input("Q")

        with self.assertRaises(urwid.ExitMainLoop):
            self.tui.unhandled_input("esc")


if __name__ == "__main__":
    unittest.main()
