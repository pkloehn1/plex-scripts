"""Test select tmdb poster."""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("plexapi")

from plexapi.exceptions import NotFound

from plex_scripts.tmdb import select_tmdb_poster as core


def _make_image(provider, selected=False):
    """Build a mock poster/art object with provider and selected state."""
    image = MagicMock()
    image.provider = provider
    image.selected = selected
    return image


class _CoreTestBase(unittest.TestCase):
    """Reset the core module's mutable globals around each test."""

    def setUp(self):
        """Clear shared global state before each test."""
        self._reset_globals()

    def tearDown(self):
        """Clear shared global state after each test."""
        self._reset_globals()

    @staticmethod
    def _reset_globals():
        core.stats.clear()
        core.errors.clear()
        core.library_progress.clear()
        core.progress_line_count = 0
        core.VERBOSE = False


class TestProgress(_CoreTestBase):
    """Progress bar rendering and tracking."""

    def test_vprint_emits_when_verbose(self):
        """Forward to print when VERBOSE is enabled."""
        core.VERBOSE = True
        with patch("builtins.print") as mock_print:
            core.vprint("hello")
        mock_print.assert_called_once_with("hello")

    def test_vprint_silent_when_not_verbose(self):
        """Stay silent when VERBOSE is disabled."""
        with patch("builtins.print") as mock_print:
            core.vprint("hello")
        mock_print.assert_not_called()

    def test_make_progress_bar(self):
        """Progress bar renders and clamps to bounds."""
        self.assertEqual(core._make_progress_bar(0.0), "[" + "." * 30 + "]")
        self.assertEqual(core._make_progress_bar(50.0), "[" + "#" * 15 + "." * 15 + "]")
        self.assertEqual(core._make_progress_bar(100.0), "[" + "#" * 30 + "]")
        self.assertEqual(core._make_progress_bar(-10.0), "[" + "." * 30 + "]")
        self.assertEqual(core._make_progress_bar(150.0), "[" + "#" * 30 + "]")

    def test_render_progress_empty_returns_early(self):
        """Rendering with no libraries writes nothing."""
        with patch("sys.stdout.write") as mock_write:
            core._render_progress_locked()
        mock_write.assert_not_called()

    def test_render_progress_writes_lines_and_redraws(self):
        """Rendering draws one overall line plus a line per library and redraws."""
        core.library_progress["Movies"] = {"total": 4, "processed": 2}
        core.library_progress["A very long library name to truncate"] = {"total": 5, "processed": 1}
        core.progress_line_count = 2  # force the redraw branch
        with patch("sys.stdout.write") as mock_write, patch("sys.stdout.flush"):
            core._render_progress_locked()
        self.assertTrue(mock_write.called)
        self.assertEqual(core.progress_line_count, 3)

    def test_render_progress_zero_totals(self):
        """Rendering tolerates zero totals without dividing by zero."""
        core.library_progress["Empty"] = {"total": 0, "processed": 0}
        core.progress_line_count = 0  # skip the redraw branch
        with patch("sys.stdout.write") as mock_write, patch("sys.stdout.flush"):
            core._render_progress_locked()
        self.assertTrue(mock_write.called)
        self.assertEqual(core.progress_line_count, 2)

    def test_init_progress_populates_and_renders(self):
        """init_progress seeds per-library counters."""
        with patch("sys.stdout.write"), patch("sys.stdout.flush"):
            core.init_progress({"Movies": 3})
        self.assertEqual(core.library_progress["Movies"], {"total": 3, "processed": 0})

    def test_update_progress_unknown_library_noop(self):
        """Updating an unknown library does nothing."""
        core.update_progress("Missing")
        self.assertEqual(core.library_progress, {})

    def test_update_progress_increments_and_clamps(self):
        """Updating a library increments and clamps at its total."""
        core.library_progress["Movies"] = {"total": 2, "processed": 1}
        with patch("sys.stdout.write"), patch("sys.stdout.flush"):
            core.update_progress("Movies")
            core.update_progress("Movies")
        self.assertEqual(core.library_progress["Movies"]["processed"], 2)

    def test_clear_progress_display_resets(self):
        """Clearing the display resets the line counter."""
        core.progress_line_count = 3
        with patch("sys.stdout.write"), patch("sys.stdout.flush"):
            core.clear_progress_display()
        self.assertEqual(core.progress_line_count, 0)

    def test_clear_progress_display_noop_when_empty(self):
        """Clearing with no prior output writes nothing."""
        with patch("sys.stdout.write") as mock_write:
            core.clear_progress_display()
        mock_write.assert_not_called()


class TestSelectPoster(_CoreTestBase):
    """select_poster decision branches."""

    def test_skipped_locked(self):
        """Locked poster is skipped when locked items are excluded."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = True
        result = core.select_poster(item, include_locked=False)
        self.assertEqual(result, "skipped")
        item.isLocked.assert_called_with("thumb")

    def test_no_posters(self):
        """No available posters yields skipped."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = False
        item.posters.return_value = []
        self.assertEqual(core.select_poster(item), "skipped")

    def test_already_locked_provider_skipped(self):
        """A locked tmdb/tvdb/imdb poster is left in place."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = True
        item.posters.return_value = [_make_image("tmdb", selected=True)]
        result = core.select_poster(item, include_locked=True)
        self.assertEqual(result, "skipped")

    def test_update_replaces_provider(self):
        """A replaceable provider is swapped for the preferred one."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = False
        target = _make_image("tmdb")
        item.posters.return_value = [_make_image("plex", selected=True), target]
        self.assertEqual(core.select_poster(item, provider="tmdb"), "updated")
        target.select.assert_called_once()

    def test_no_selected_then_replace(self):
        """When nothing is selected, the preferred provider is chosen."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = False
        target = _make_image("tmdb")
        item.posters.return_value = [_make_image("plex"), target]
        self.assertEqual(core.select_poster(item, provider="tmdb"), "updated")
        target.select.assert_called_once()

    def test_list_provider_candidates(self):
        """A provider list is used verbatim as the candidate order."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = False
        target = _make_image("tvdb")
        item.posters.return_value = [_make_image("plex", selected=True), target]
        self.assertEqual(core.select_poster(item, provider=["tvdb"]), "updated")
        target.select.assert_called_once()

    def test_no_matching_provider_skipped(self):
        """A replaceable poster with no candidate available is skipped."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = False
        item.posters.return_value = [_make_image("plex", selected=True), _make_image("fanarttv")]
        self.assertEqual(core.select_poster(item, provider="tmdb"), "skipped")

    def test_locks_existing_non_replace_provider(self):
        """A good, unlocked provider poster is locked in place."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = False
        item.posters.return_value = [_make_image("fanarttv", selected=True)]
        self.assertEqual(core.select_poster(item), "locked")
        item.lockPoster.assert_called_once()


class TestSelectArt(_CoreTestBase):
    """select_art decision branches."""

    def test_skipped_locked(self):
        """Locked art is skipped when locked items are excluded."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = True
        result = core.select_art(item, include_locked=False)
        self.assertEqual(result, "skipped")
        item.isLocked.assert_called_with("art")

    def test_no_arts(self):
        """No available art yields skipped."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = False
        item.arts.return_value = []
        self.assertEqual(core.select_art(item), "skipped")

    def test_already_locked_provider_skipped(self):
        """Locked tmdb/tvdb/imdb art is left in place."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = True
        item.arts.return_value = [_make_image("tmdb", selected=True)]
        self.assertEqual(core.select_art(item, include_locked=True), "skipped")

    def test_update_replaces_provider(self):
        """A replaceable art provider is swapped for the preferred one."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = False
        target = _make_image("tmdb")
        item.arts.return_value = [_make_image("plex", selected=True), target]
        self.assertEqual(core.select_art(item, provider="tmdb"), "updated")
        target.select.assert_called_once()

    def test_no_selected_then_replace(self):
        """When no art is selected, the preferred provider is chosen."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = False
        target = _make_image("tmdb")
        item.arts.return_value = [_make_image("plex"), target]
        self.assertEqual(core.select_art(item, provider="tmdb"), "updated")
        target.select.assert_called_once()

    def test_list_provider_candidates(self):
        """A provider list is used verbatim for art."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = False
        target = _make_image("imdb")
        item.arts.return_value = [_make_image("plex", selected=True), target]
        self.assertEqual(core.select_art(item, provider=["imdb"]), "updated")
        target.select.assert_called_once()

    def test_no_matching_provider_skipped(self):
        """A replaceable art with no candidate available is skipped."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = False
        item.arts.return_value = [_make_image("plex", selected=True), _make_image("fanarttv")]
        self.assertEqual(core.select_art(item, provider="tmdb"), "skipped")

    def test_locks_existing_non_replace_provider(self):
        """A good, unlocked provider art is locked in place."""
        item = MagicMock()
        item.title = "Movie"
        item.isLocked.return_value = False
        item.arts.return_value = [_make_image("fanarttv", selected=True)]
        self.assertEqual(core.select_art(item), "locked")
        item.lockArt.assert_called_once()


class TestResolveSections(_CoreTestBase):
    """resolve_sections separates found sections from missing names."""

    def test_separates_found_and_missing(self):
        """Named libraries resolve to found sections; unknown names are reported missing."""
        plex = MagicMock()
        found_section = MagicMock()

        def fake_section(name):
            if name == "Gone":
                raise NotFound("missing")
            return found_section

        plex.library.section.side_effect = fake_section
        resolution = core.resolve_sections(plex, ["Movies", "Gone"])
        self.assertEqual(resolution.found, [found_section])
        self.assertEqual(resolution.missing, ["Gone"])


class TestSelectItem(_CoreTestBase):
    """select_item statistics and error handling."""

    @staticmethod
    def _make_item():
        item = MagicMock()
        item.title = "Movie"
        item.year = 2020
        item.librarySectionTitle = "Movies"
        return item

    def test_records_each_result_kind(self):
        """Updated/locked/skipped results increment the matching counters."""
        for result_kind in ("updated", "locked", "skipped"):
            self._reset_globals()
            item = self._make_item()
            with (
                patch.object(core, "select_poster", return_value=result_kind),
                patch.object(core, "select_art", return_value=result_kind),
            ):
                core.select_item(item, poster=True, art=True)
            self.assertEqual(core.stats["Movies"][f"poster_{result_kind}"], 1)
            self.assertEqual(core.stats["Movies"][f"art_{result_kind}"], 1)
            self.assertEqual(core.stats["Movies"]["total"], 1)

    def test_poster_exception_recorded(self):
        """A poster error is captured in stats and the error list."""
        item = self._make_item()
        with patch.object(core, "select_poster", side_effect=RuntimeError("boom")):
            core.select_item(item, poster=True, art=False)
        self.assertEqual(core.stats["Movies"]["errors"], 1)
        self.assertEqual(core.errors[0]["type"], "poster")

    def test_art_exception_recorded(self):
        """An art error is captured in stats and the error list."""
        item = self._make_item()
        with patch.object(core, "select_art", side_effect=RuntimeError("boom")):
            core.select_item(item, poster=False, art=True)
        self.assertEqual(core.stats["Movies"]["errors"], 1)
        self.assertEqual(core.errors[0]["type"], "art")

    def test_item_without_year(self):
        """Items lacking a year attribute fall back to N/A."""
        item = MagicMock()
        item.title = "Movie"
        item.librarySectionTitle = "Movies"
        del item.year
        core.select_item(item, poster=False, art=False)
        self.assertEqual(core.stats["Movies"]["total"], 1)


class TestSelectLibrary(_CoreTestBase):
    """select_library item and season traversal."""

    def test_processes_items_and_seasons(self):
        """Each item and its seasons are processed and progress advances."""
        library = MagicMock()
        library.title = "Shows"
        core.library_progress["Shows"] = {"total": 1, "processed": 0}

        season = MagicMock()
        season.title = "Season 1"
        item = MagicMock()
        item.title = "Show"
        item._INCLUDES = {"includeKey": 1}
        item.seasons.return_value = [season]

        with patch.object(core, "select_item") as mock_select, patch("sys.stdout.write"), patch("sys.stdout.flush"):
            core.select_library(library, [item], poster=True, art=True)

        item.reload.assert_called_once()
        self.assertEqual(mock_select.call_count, 2)
        self.assertEqual(core.library_progress["Shows"]["processed"], 1)


class TestPrintSummary(_CoreTestBase):
    """print_summary output."""

    def test_no_errors(self):
        """A clean run reports no errors."""
        with patch("builtins.print") as mock_print:
            core.print_summary()
        mock_print.assert_called_once()

    def test_with_errors(self):
        """Recorded errors are printed individually."""
        core.errors.append({"library": "Movies", "item": "Movie (2020)", "type": "poster", "error": "boom"})
        with patch("builtins.print") as mock_print:
            core.print_summary()
        self.assertGreaterEqual(mock_print.call_count, 3)


class TestProcessLibraries(_CoreTestBase):
    """process_libraries orchestration."""

    def test_no_libraries(self):
        """An empty library list exits early."""
        with patch("builtins.print") as mock_print:
            core.process_libraries(
                [], include_locked=False, poster=True, poster_provider="tmdb", art=False, art_provider="tmdb"
            )
        mock_print.assert_called_once()

    def test_runs_each_library(self):
        """Each library is dispatched to a worker and a summary printed."""
        library = MagicMock()
        library.title = "Movies"
        library.all.return_value = [MagicMock()]

        with (
            patch.object(core, "select_library") as mock_select_library,
            patch.object(core, "print_summary") as mock_summary,
            patch("sys.stdout.write"),
            patch("sys.stdout.flush"),
        ):
            core.process_libraries(
                [library],
                include_locked=False,
                poster=True,
                poster_provider="tmdb",
                art=True,
                art_provider="tmdb",
            )

        mock_select_library.assert_called_once()
        mock_summary.assert_called_once()
        library.all.assert_called_once_with(includeGuids=False)

    def test_isolates_one_library_failure(self):
        """A failing library is recorded and does not abort the other libraries."""
        good_library = MagicMock()
        good_library.title = "Good"
        good_library.all.return_value = [MagicMock()]
        bad_library = MagicMock()
        bad_library.title = "Bad"
        bad_library.all.return_value = [MagicMock()]

        def fake_select_library(library, *_args, **_kwargs):
            if library.title == "Bad":
                raise RuntimeError("boom")

        with (
            patch.object(core, "select_library", side_effect=fake_select_library),
            patch.object(core, "print_summary"),
            patch("sys.stdout.write"),
            patch("sys.stdout.flush"),
        ):
            core.process_libraries(
                [good_library, bad_library],
                include_locked=False,
                poster=True,
                poster_provider="tmdb",
                art=False,
                art_provider="tmdb",
            )

        recorded = [error for error in core.errors if error["library"] == "Bad"]
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["type"], "library")

    def test_isolates_library_enumeration_failure(self):
        """A library whose item enumeration fails is recorded and skipped."""
        good_library = MagicMock()
        good_library.title = "Good"
        good_library.all.return_value = [MagicMock()]
        bad_library = MagicMock()
        bad_library.title = "Bad"
        bad_library.all.side_effect = RuntimeError("enumerate boom")

        with (
            patch.object(core, "select_library") as mock_select_library,
            patch.object(core, "print_summary"),
            patch("sys.stdout.write"),
            patch("sys.stdout.flush"),
        ):
            error_count = core.process_libraries(
                [good_library, bad_library],
                include_locked=False,
                poster=True,
                poster_provider="tmdb",
                art=False,
                art_provider="tmdb",
            )

        self.assertTrue(any(error["library"] == "Bad" for error in core.errors))
        self.assertEqual(error_count, len(core.errors))
        mock_select_library.assert_called_once()

    def test_all_enumeration_failures_skip_executor(self):
        """When every library fails enumeration, the executor is skipped."""
        bad_library = MagicMock()
        bad_library.title = "Bad"
        bad_library.all.side_effect = RuntimeError("boom")

        with (
            patch.object(core, "select_library") as mock_select_library,
            patch.object(core, "print_summary") as mock_summary,
        ):
            error_count = core.process_libraries(
                [bad_library],
                include_locked=False,
                poster=True,
                poster_provider="tmdb",
                art=False,
                art_provider="tmdb",
            )

        mock_select_library.assert_not_called()
        mock_summary.assert_called_once()
        self.assertEqual(error_count, 1)

    def test_reset_clears_prior_run_errors(self):
        """Each run starts from a clean error list."""
        core.errors.append({"library": "Stale", "item": "(library)", "type": "library", "error": "old"})
        with patch("builtins.print"):
            core.process_libraries(
                [], include_locked=False, poster=True, poster_provider="tmdb", art=False, art_provider="tmdb"
            )
        self.assertEqual(core.errors, [])


class TestEntryPointResolvers(_CoreTestBase):
    """Import resolvers supporting both module and direct-file launches."""

    def test_resolve_should_use_tui_package(self):
        """The package import resolves to the real should_use_tui."""
        resolved = core._resolve_should_use_tui()
        self.assertTrue(resolved([]))
        self.assertFalse(resolved(["script", "--poster"]))

    def test_resolve_should_use_tui_falls_back_to_flat(self):
        """A failed package import falls back to the flat sibling import."""
        flat_module = types.ModuleType("select_tmdb_poster_config")
        flat_module.should_use_tui = lambda argv: argv == ["sentinel"]
        overrides = {
            "plex_scripts.tmdb.select_tmdb_poster_config": None,
            "select_tmdb_poster_config": flat_module,
        }
        with patch.dict(sys.modules, overrides):
            resolved = core._resolve_should_use_tui()
        self.assertTrue(resolved(["sentinel"]))

    def test_resolve_run_tui_package(self):
        """The package import resolves run_tui when available."""
        self.assertIsNotNone(core._resolve_run_tui())

    def test_resolve_run_tui_falls_back_to_flat(self):
        """A failed package import falls back to the flat sibling import."""
        flat_module = types.ModuleType("select_tmdb_poster_tui")
        sentinel = object()
        flat_module.run_tui = sentinel
        overrides = {
            "plex_scripts.tmdb.select_tmdb_poster_tui": None,
            "select_tmdb_poster_tui": flat_module,
        }
        with patch.dict(sys.modules, overrides):
            self.assertIs(core._resolve_run_tui(), sentinel)

    def test_resolve_run_tui_unavailable_returns_none(self):
        """When neither import resolves, the resolver returns None."""
        overrides = {
            "plex_scripts.tmdb.select_tmdb_poster_tui": None,
            "select_tmdb_poster_tui": None,
        }
        with patch.dict(sys.modules, overrides):
            self.assertIsNone(core._resolve_run_tui())


if __name__ == "__main__":
    unittest.main()
