"""Test select tmdb poster."""

import pytest

pytest.importorskip("plexapi")

import unittest
from unittest.mock import MagicMock

from plex_scripts.tmdb import select_tmdb_poster


class TestSelectTmdbPoster(unittest.TestCase):
    """Test Select Tmdb Poster."""

    def test_make_progress_bar(self):
        """Test progress bar generation."""
        # 0%
        bar = select_tmdb_poster._make_progress_bar(0.0)
        self.assertEqual(bar, "[" + "." * 30 + "]")

        # 50%
        bar = select_tmdb_poster._make_progress_bar(50.0)
        self.assertEqual(bar, "[" + "#" * 15 + "." * 15 + "]")

        # 100%
        bar = select_tmdb_poster._make_progress_bar(100.0)
        self.assertEqual(bar, "[" + "#" * 30 + "]")

        # Bounds clamping
        bar = select_tmdb_poster._make_progress_bar(-10.0)
        self.assertEqual(bar, "[" + "." * 30 + "]")
        bar = select_tmdb_poster._make_progress_bar(150.0)
        self.assertEqual(bar, "[" + "#" * 30 + "]")

    def test_select_poster_skipped_locked(self):
        """Test select_poster skips locked items."""
        item = MagicMock()
        item.title = "Test Movie"
        item.isLocked.return_value = True

        result = select_tmdb_poster.select_poster(item, include_locked=False)
        self.assertEqual(result, "skipped")
        item.isLocked.assert_called_with("thumb")

    def test_select_poster_no_posters(self):
        """Test select_poster handles items with no posters."""
        item = MagicMock()
        item.title = "Test Movie"
        item.isLocked.return_value = False
        item.posters.return_value = []

        result = select_tmdb_poster.select_poster(item)
        self.assertEqual(result, "skipped")

    def test_select_poster_already_correct(self):
        """Test select_poster skips if correct provider is already locked."""
        item = MagicMock()
        item.title = "Test Movie"
        item.isLocked.return_value = True

        poster = MagicMock()
        poster.selected = True
        poster.provider = "tmdb"
        item.posters.return_value = [poster]

        result = select_tmdb_poster.select_poster(item, include_locked=False)
        self.assertEqual(result, "skipped")

    def test_select_poster_update(self):
        """Test select_poster updates to preferred provider."""
        item = MagicMock()
        item.title = "Test Movie"
        item.isLocked.return_value = False

        current_poster = MagicMock()
        current_poster.selected = True
        current_poster.provider = "plex"

        target_poster = MagicMock()
        target_poster.selected = False
        target_poster.provider = "tmdb"

        item.posters.return_value = [current_poster, target_poster]

        result = select_tmdb_poster.select_poster(item, provider="tmdb")
        self.assertEqual(result, "updated")
        target_poster.select.assert_called_once()

    def test_select_art_update(self):
        """Test select_art updates to preferred provider."""
        item = MagicMock()
        item.title = "Test Movie"
        item.isLocked.return_value = False

        current_art = MagicMock()
        current_art.selected = True
        current_art.provider = "plex"

        target_art = MagicMock()
        target_art.selected = False
        target_art.provider = "tmdb"

        item.arts.return_value = [current_art, target_art]

        result = select_tmdb_poster.select_art(item, provider="tmdb")
        self.assertEqual(result, "updated")
        target_art.select.assert_called_once()


if __name__ == "__main__":
    unittest.main()
