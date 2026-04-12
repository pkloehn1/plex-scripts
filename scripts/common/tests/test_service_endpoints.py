from __future__ import annotations

from scripts.common.service_endpoints import SERVARR_FQDNS


class TestServarrFqdns:
    def test_is_dict(self) -> None:
        assert isinstance(SERVARR_FQDNS, dict)

    def test_contains_sonarr(self) -> None:
        assert "sonarr" in SERVARR_FQDNS

    def test_contains_radarr(self) -> None:
        assert "radarr" in SERVARR_FQDNS

    def test_all_values_are_strings(self) -> None:
        for key, value in SERVARR_FQDNS.items():
            assert isinstance(key, str)
            assert isinstance(value, str)

    def test_expected_keys_present(self) -> None:
        expected_keys = {"sonarr", "radarr", "radarr-se", "radarr-4k", "radarr-4k-se", "radarr-concerts"}
        assert set(SERVARR_FQDNS.keys()) == expected_keys
