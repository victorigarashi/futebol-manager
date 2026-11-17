from __future__ import annotations

import hashlib
import json
from pathlib import Path

from data.importers.commons_photo_manifest import load_reviews, merge_approved_photos


def review(player_id: str, checksum: str, **overrides: str) -> dict[str, str]:
    value = {
        "catalog_player_id": player_id,
        "wikidata_qid": "Q12345",
        "commons_file_title": "File:Player.jpg",
        "commons_file_url": "https://commons.wikimedia.org/wiki/File:Player.jpg",
        "original_url": "https://upload.wikimedia.org/example/Player.jpg",
        "author": "Example photographer",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0",
        "attribution": "Example photographer, CC BY 4.0",
        "identity_review_status": "APPROVED_MANUAL",
        "license_review_status": "APPROVED",
        "personality_rights_status": "NOT_ASSERTED_BY_SOURCE",
        "asset_path": "/player-photos/world/player.jpg",
        "asset_sha256": checksum,
    }
    value.update(overrides)
    return value


def catalog() -> dict:
    return {"players": [{"id": "WLD-1", "name": "Player One"}]}


def test_attach_only_a_manually_approved_local_cc_by_asset(tmp_path: Path) -> None:
    asset = tmp_path / "player-photos/world/player.jpg"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"licensed image bytes")
    checksum = hashlib.sha256(asset.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"photos": [review("WLD-1", checksum)]}), encoding="utf-8")

    reviews, issues = load_reviews(manifest)
    merged, report = merge_approved_photos(catalog(), reviews, tmp_path)

    assert issues == []
    assert merged["players"][0]["photo_url"] == "/player-photos/world/player.jpg"
    assert report["attached"][0]["author"] == "Example photographer"
    assert report["pending"] == []


def test_rejects_name_only_style_review_when_commons_flags_personality(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"photos": [review("WLD-1", "0" * 64, personality_rights_status="SOURCE_FLAGS_PERSONALITY")]}), encoding="utf-8")

    reviews, issues = load_reviews(manifest)
    merged, report = merge_approved_photos(catalog(), reviews, tmp_path)

    assert issues == []
    assert "photo_url" not in merged["players"][0]
    assert report["pending"] == [{"catalog_player_id": "WLD-1", "commons_file_title": "File:Player.jpg", "reason": "REVIEW_OR_LICENSE_NOT_APPROVED"}]


def test_manifest_reports_duplicate_player_and_unknown_license(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    first = review("WLD-1", "0" * 64, license="CC BY-SA 4.0")
    second = review("WLD-1", "1" * 64, commons_file_title="File:Other.jpg", asset_path="/player-photos/world/other.jpg")
    manifest.write_text(json.dumps({"photos": [first, second]}), encoding="utf-8")

    reviews, issues = load_reviews(manifest)

    assert len(reviews) == 1
    assert any("jogador repetido" in issue for issue in issues)


def test_catalog_schema_accepts_only_local_photo_assets_or_https() -> None:
    from app.domain.catalog import CatalogPlayer

    base = {
        "id": "WLD-1", "name": "Player One", "club_code": "WLD", "position": "ST",
        "overall": 80, "potential": 82, "market_value_cents": 1,
        "source": "test", "source_version": "v1",
    }
    assert CatalogPlayer(**base, photo_url="/player-photos/world/player.jpg").photo_url
    assert CatalogPlayer(**base, photo_url="https://example.test/player.jpg").photo_url
