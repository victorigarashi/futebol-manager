import csv
import json
import tempfile
import unittest
from pathlib import Path

from data.importers.brasileirao_rating_model import rate_player
from data.importers.catalog_builder import classify_candidate
from data.importers.cbf_importer import import_authorized_export as import_cbf_export
from data.importers.eafc26_importer import import_local_dataset, import_rows
from data.importers.fcmania_importer import import_authorized_export
from data.importers.game_pricing import game_starting_value_cents
from data.importers.identity_matcher import match_identity
from data.importers.playersdb_importer import import_export as import_playersdb_export
from data.importers.transfermarkt_importer import import_players
from data.importers.validation import (
    generate_reports,
    runtime_compatible,
    validate_records,
)


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class CatalogPipelineTests(unittest.TestCase):
    def test_game_price_is_integer_cents_and_deterministic(self) -> None:
        price = game_starting_value_cents(
            overall=80,
            potential=86,
            age=22,
            position="ST",
            external_market_value_eur=1_000_000,
        )
        self.assertIsInstance(price, int)
        self.assertGreater(price, 0)
        self.assertEqual(
            price,
            game_starting_value_cents(
                overall=80,
                potential=86,
                age=22,
                position="ST",
                external_market_value_eur=1_000_000,
            ),
        )

    def test_brasileirao_rating_model_requires_positional_evidence(self) -> None:
        self.assertIsNone(rate_player("ST", {"age": 22}))
        result = rate_player(
            "ST",
            {
                "age": 22,
                "minutes": 80,
                "appearances": 75,
                "regularity": 82,
                "shots": 76,
                "goals": 70,
                "assists": 55,
            },
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.confidence, "INTERNAL_ESTIMATE")
        self.assertTrue(1 <= result.overall <= 99)
        self.assertTrue(1 <= result.potential <= 99)

    def test_eafc26_schema_preserves_real_ratings_potential_and_attributes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "players.csv"
            write_csv(
                source,
                [
                    {
                        "player_id": "123",
                        "short_name": "A. Teste",
                        "long_name": "Atleta Teste",
                        "player_positions": "CAM, CM",
                        "overall": "79",
                        "potential": "86",
                        "dob": "2001-01-02",
                        "age": "24",
                        "nationality_name": "Brazil",
                        "club_team_id": "1",
                        "club_name": "Flamengo",
                        "league_name": "Série A",
                        "fifa_update_date": "2025-09-19",
                        "value_eur": "1000000",
                        "pace": "80",
                        "attacking_finishing": "70",
                        "goalkeeping_diving": "0",
                    }
                ],
            )
            [record] = import_rows(source)
            self.assertEqual(record["overall"], 79)
            self.assertEqual(record["potential"], 86)
            self.assertEqual(record["primary_position"], "MF")
            self.assertEqual(record["secondary_positions"], ["MF"])
            self.assertEqual(record["attributes"]["pace"], 80)
            self.assertEqual(record["rating_source"], "EAFC26_DATAHUB_KAGGLE_CC_BY_4_0")
            self.assertEqual(record["distribution_license"], "CC BY 4.0")

    def test_sentinel_birth_date_is_not_used_as_real_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "players.csv"
            write_csv(
                source,
                [
                    {
                        "player_id": "1",
                        "long_name": "Teste",
                        "short_name": "Teste",
                        "player_positions": "ST",
                        "overall": "70",
                        "potential": "75",
                        "dob": "1996-02-29",
                        "club_name": "Flamengo",
                        "nationality_name": "Brazil",
                    }
                ],
            )
            [record] = import_rows(source)
            self.assertIsNone(record["birth_date"])
            self.assertEqual(record["source_birth_date_raw"], "1996-02-29")
            self.assertTrue(record["source_quality"]["sentinel_birth_date"])

    def test_eafc_validation_does_not_require_historical_match(self) -> None:
        row = {
            "source_player_id": "10",
            "full_name": "Atleta Real",
            "current_club_name": "Flamengo",
            "primary_position": "ST",
            "overall": 80,
            "potential": 84,
            "distribution_allowed": True,
            "source_quality": {
                "sentinel_birth_date": False,
                "overall_valid": True,
                "potential_valid": True,
            },
        }
        self.assertEqual(
            classify_candidate(row, {"10": {"current_club_name": "Flamengo"}})[0],
            "VERIFIED",
        )
        self.assertEqual(classify_candidate(row, None)[0], "STALE_CLUB")
        invalid = {
            **row,
            "source_quality": {**row["source_quality"], "sentinel_birth_date": True},
        }
        self.assertEqual(classify_candidate(invalid, None)[0], "INVALID_IDENTITY")

    def test_transfermarkt_import_keeps_historical_value_and_never_fabricates_ratings(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tmp_path = Path(temporary)
            players = tmp_path / "players.csv"
            values = tmp_path / "values.csv"
            apps = tmp_path / "appearances.csv"
            write_csv(
                players,
                [
                    {
                        "player_id": "123",
                        "name": "João Teste",
                        "last_season": "2025",
                        "current_club_id": "1",
                        "country_of_citizenship": "Brazil",
                        "date_of_birth": "2000-06-10 00:00:00",
                        "sub_position": "Centre-Forward",
                        "position": "Attack",
                        "foot": "right",
                        "height_in_cm": "180",
                        "current_club_domestic_competition_id": "BRA1",
                        "current_club_name": "Club X",
                        "url": "https://example.test/player",
                    }
                ],
            )
            write_csv(
                values,
                [
                    {
                        "player_id": "123",
                        "date": "2026-06-01",
                        "market_value_in_eur": "1234567",
                        "current_club_name": "Club X",
                        "current_club_id": "1",
                        "player_club_domestic_competition_id": "BRA1",
                    },
                    {
                        "player_id": "123",
                        "date": "2026-06-20",
                        "market_value_in_eur": "9999999",
                        "current_club_name": "Club X",
                        "current_club_id": "1",
                        "player_club_domestic_competition_id": "BRA1",
                    },
                ],
            )
            write_csv(
                apps,
                [
                    {
                        "player_id": "123",
                        "date": "2025-03-01",
                        "competition_id": "BRA1",
                        "minutes_played": "90",
                        "goals": "1",
                        "assists": "0",
                    }
                ],
            )

            [record] = import_players(players, values, apps)

            self.assertEqual(record["market_value_reference_date"], "2026-06-01")
            self.assertEqual(record["external_market_value"], "1234567")
            self.assertEqual(record["age_at_reference_date"], 26)
            self.assertEqual(record["primary_position"], "Centre-Forward")
            self.assertEqual(record["normalized_game_position"], "ST")
            self.assertIsNone(record["overall"])
            self.assertIsNone(record["potential"])
            self.assertTrue(
                all(value is None for value in record["attributes"].values())
            )
            self.assertEqual(record["relevance_evidence"]["minutes"], 90)
            self.assertEqual(record["relevance_evidence"]["goals"], 1)
            self.assertFalse(record["player_photo_allowed_for_redistribution"])

    def test_no_brazil_appearances_is_missing_evidence_not_zero_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tmp_path = Path(temporary)
            players, values, apps = (
                tmp_path / name for name in ("players.csv", "values.csv", "apps.csv")
            )
            write_csv(
                players,
                [
                    {
                        "player_id": "1",
                        "name": "Nome",
                        "current_club_domestic_competition_id": "BRA1",
                        "current_club_name": "Club",
                        "position": "Defender",
                    }
                ],
            )
            write_csv(
                values,
                [
                    {
                        "player_id": "1",
                        "date": "",
                        "market_value_in_eur": "",
                        "current_club_name": "",
                        "current_club_id": "",
                        "player_club_domestic_competition_id": "",
                    }
                ],
            )
            write_csv(
                apps,
                [
                    {
                        "player_id": "1",
                        "date": "2025-01-01",
                        "competition_id": "GB1",
                        "minutes_played": "90",
                        "goals": "0",
                        "assists": "0",
                    }
                ],
            )
            [record] = import_players(players, values, apps)
            self.assertIsNone(record["relevance_evidence"])
            self.assertEqual(
                record["relevance_evidence_status"], "SOURCE_HAS_NO_BRA1_APPEARANCES"
            )

    def test_identity_match_is_conservative_and_detects_external_id_conflict(
        self,
    ) -> None:
        left = {
            "full_name": "Giorgian de Arrascaeta",
            "birth_date": "1994-06-01",
            "nationality": "Uruguay",
            "source_ids": {"transfermarkt": "1"},
        }
        self.assertEqual(
            match_identity(
                left, {**left, "source_ids": {"transfermarkt": "1"}}
            ).confidence,
            "EXACT_ID",
        )
        self.assertEqual(
            match_identity(left, {**left, "source_ids": {"playersdb": "2"}}).confidence,
            "HIGH_CONFIDENCE",
        )
        self.assertEqual(
            match_identity(
                left, {**left, "full_name": "Arrascaeta", "source_ids": {}}
            ).confidence,
            "UNMATCHED",
        )
        self.assertEqual(
            match_identity(
                left, {**left, "source_ids": {"transfermarkt": "other"}}
            ).confidence,
            "NEEDS_REVIEW",
        )

    def test_importers_require_permission_and_rating_source_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "players.csv"
            write_csv(source, [{"player_id": "1", "overall": "70"}])
            with self.assertRaises(PermissionError):
                import_authorized_export(source, permission_reference=None)
            with self.assertRaises(PermissionError):
                import_local_dataset(source, license_reference=None)
            self.assertEqual(
                import_local_dataset(source, license_reference="license-record")[0][
                    "rating_source"
                ],
                "EAFC26",
            )

    def test_playersdb_and_cbf_imports_keep_source_roles_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "players.csv"
            write_csv(
                source,
                [
                    {
                        "id": "pd:1",
                        "name": "Jogador",
                        "transfermarkt_id": "123",
                        "fifa_id": "456",
                    }
                ],
            )
            playerdb_row = import_playersdb_export(source)[0]
            self.assertIsNone(playerdb_row["rating_source"])
            self.assertEqual(playerdb_row["source_ids"]["transfermarkt"], "123")
            with self.assertRaises(PermissionError):
                import_cbf_export(source, permission_reference=None)
            self.assertEqual(
                import_cbf_export(source, permission_reference="authorization-id")[0][
                    "id"
                ],
                "pd:1",
            )

    def test_validation_and_reports_flag_duplicates_without_auto_merging(self) -> None:
        records = [
            {
                "player_id": "tm:1",
                "full_name": "João da Silva",
                "birth_date": "2000-01-01",
                "current_club_id": "1",
                "overall": None,
                "potential": None,
                "market_value_cents": None,
                "external_market_value": None,
                "attributes": {"pace": None},
                "primary_position": "Defender",
                "current_club_name": "Club",
                "relevance_evidence": None,
                "source_ids": {"transfermarkt": "1"},
            },
            {
                "player_id": "tm:2",
                "full_name": "Joao da Silva",
                "birth_date": "1999-01-01",
                "current_club_id": "2",
                "overall": None,
                "potential": None,
                "market_value_cents": None,
                "external_market_value": None,
                "attributes": {"pace": None},
                "primary_position": "Defender",
                "current_club_name": "Club",
                "relevance_evidence": None,
                "source_ids": {"transfermarkt": "2"},
            },
        ]
        with tempfile.TemporaryDirectory() as temporary:
            tmp_path = Path(temporary)
            self.assertTrue(validate_records(records)["valid"])
            report = generate_reports(records, tmp_path)
            self.assertEqual(report["record_count"], 2)
            self.assertEqual(report["overall_confirmed"], 0)
            self.assertEqual(report["runtime_compatible_count"], 0)
            self.assertFalse(runtime_compatible(records[0]))
            self.assertFalse(report["production_catalog_generated"])
            duplicates = (tmp_path / "DUPLICATES.csv").read_text(encoding="utf-8")
            self.assertIn("tm:1", duplicates)
            self.assertIn("tm:2", duplicates)  # review evidence; IDs are not merged
            self.assertEqual(
                json.loads((tmp_path / "coverage.json").read_text(encoding="utf-8"))[
                    "club_2026_validated"
                ],
                0,
            )
            self.assertTrue((tmp_path / "ASSET_MANIFEST.csv").exists())
