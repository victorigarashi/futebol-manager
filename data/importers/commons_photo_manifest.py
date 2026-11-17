"""Validate manually reviewed Wikimedia Commons photos for the world Draft.

This module deliberately does *not* search Commons by a player name. A name-only
match can select a namesake or a photo of the wrong person.  A curator supplies
the Wikidata QID and completes the two review statuses in a local manifest after
checking the Commons file page.

Only CC0 and CC-BY assets are accepted by default.  Share-alike, non-commercial,
unknown and source-flagged personality-rights assets remain in the review report.
The result is a new catalog file; the existing catalog is never modified in place.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ALLOWED_LICENSES = frozenset({"CC0-1.0", "CC BY 3.0", "CC BY 4.0"})
MANUAL_IDENTITY_APPROVED = "APPROVED_MANUAL"
LICENSE_APPROVED = "APPROVED"
PERSONALITY_SOURCE_CLEAR = "NOT_ASSERTED_BY_SOURCE"
QID = re.compile(r"^Q[1-9][0-9]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
LOCAL_ASSET = re.compile(r"^/player-photos/world/[a-z0-9][a-z0-9-]*\.(?:avif|jpe?g|png|webp)$")


@dataclass(frozen=True)
class PhotoReview:
    catalog_player_id: str
    wikidata_qid: str
    commons_file_title: str
    commons_file_url: str
    original_url: str
    author: str
    license: str
    license_url: str
    attribution: str
    identity_review_status: str
    license_review_status: str
    personality_rights_status: str
    asset_path: str
    asset_sha256: str

    @property
    def approved(self) -> bool:
        return (
            self.license in ALLOWED_LICENSES
            and self.identity_review_status == MANUAL_IDENTITY_APPROVED
            and self.license_review_status == LICENSE_APPROVED
            and self.personality_rights_status == PERSONALITY_SOURCE_CLEAR
        )


def _require_text(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} é obrigatório.")
    return " ".join(value.split())


def _https_url(value: str, field: str) -> str:
    if urlparse(value).scheme != "https":
        raise ValueError(f"{field} precisa usar HTTPS.")
    return value


def parse_review(raw: dict[str, Any]) -> PhotoReview:
    review = PhotoReview(
        catalog_player_id=_require_text(raw, "catalog_player_id"),
        wikidata_qid=_require_text(raw, "wikidata_qid"),
        commons_file_title=_require_text(raw, "commons_file_title"),
        commons_file_url=_https_url(_require_text(raw, "commons_file_url"), "commons_file_url"),
        original_url=_https_url(_require_text(raw, "original_url"), "original_url"),
        author=_require_text(raw, "author"),
        license=_require_text(raw, "license"),
        license_url=_https_url(_require_text(raw, "license_url"), "license_url"),
        attribution=_require_text(raw, "attribution"),
        identity_review_status=_require_text(raw, "identity_review_status"),
        license_review_status=_require_text(raw, "license_review_status"),
        personality_rights_status=_require_text(raw, "personality_rights_status"),
        asset_path=_require_text(raw, "asset_path"),
        asset_sha256=_require_text(raw, "asset_sha256"),
    )
    if not QID.fullmatch(review.wikidata_qid):
        raise ValueError("wikidata_qid inválido.")
    if not review.commons_file_title.startswith("File:"):
        raise ValueError("commons_file_title deve começar com 'File:'.")
    if urlparse(review.commons_file_url).netloc != "commons.wikimedia.org":
        raise ValueError("commons_file_url deve apontar para commons.wikimedia.org.")
    if not LOCAL_ASSET.fullmatch(review.asset_path):
        raise ValueError("asset_path deve ser um arquivo local em /player-photos/world/.")
    if not SHA256.fullmatch(review.asset_sha256):
        raise ValueError("asset_sha256 inválido.")
    return review


def load_reviews(path: Path) -> tuple[list[PhotoReview], list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("photos"), list):
        raise TypeError("Manifesto deve conter uma lista 'photos'.")
    reviews: list[PhotoReview] = []
    issues: list[str] = []
    seen_player_ids: set[str] = set()
    seen_files: set[str] = set()
    for index, raw in enumerate(payload["photos"]):
        if not isinstance(raw, dict):
            issues.append(f"photos[{index}]: registro inválido.")
            continue
        try:
            review = parse_review(raw)
        except ValueError as error:
            issues.append(f"photos[{index}]: {error}")
            continue
        if review.catalog_player_id in seen_player_ids:
            issues.append(f"photos[{index}]: jogador repetido ({review.catalog_player_id}).")
            continue
        if review.commons_file_title in seen_files:
            issues.append(f"photos[{index}]: arquivo Commons repetido ({review.commons_file_title}).")
            continue
        seen_player_ids.add(review.catalog_player_id)
        seen_files.add(review.commons_file_title)
        reviews.append(review)
    return reviews, issues


def file_matches_checksum(asset_root: Path, review: PhotoReview) -> bool:
    target = asset_root / review.asset_path.removeprefix("/")
    if not target.is_file():
        return False
    return hashlib.sha256(target.read_bytes()).hexdigest() == review.asset_sha256


def merge_approved_photos(catalog: dict[str, Any], reviews: list[PhotoReview], asset_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a copy with only verified, local licensed photos attached."""
    updated = copy.deepcopy(catalog)
    players = {str(player.get("id")): player for player in updated.get("players", []) if isinstance(player, dict)}
    attached: list[dict[str, str]] = []
    pending: list[dict[str, str]] = []
    for review in reviews:
        reason = ""
        if review.catalog_player_id not in players:
            reason = "CATALOG_PLAYER_NOT_FOUND"
        elif not review.approved:
            reason = "REVIEW_OR_LICENSE_NOT_APPROVED"
        elif not file_matches_checksum(asset_root, review):
            reason = "LOCAL_ASSET_MISSING_OR_CHECKSUM_MISMATCH"
        if reason:
            pending.append({"catalog_player_id": review.catalog_player_id, "commons_file_title": review.commons_file_title, "reason": reason})
            continue
        players[review.catalog_player_id]["photo_url"] = review.asset_path
        attached.append({
            "catalog_player_id": review.catalog_player_id,
            "commons_file_title": review.commons_file_title,
            "commons_file_url": review.commons_file_url,
            "author": review.author,
            "license": review.license,
            "license_url": review.license_url,
            "attribution": review.attribution,
        })
    updated["photo_provenance"] = {
        "source": "Wikimedia Commons individual-file manifest",
        "automatic_name_matching": False,
        "distribution": "Only locally bundled assets with approved per-file review are attached.",
        "credits": attached,
    }
    return updated, {"attached": attached, "pending": pending}


def main(argv: list[str]) -> None:
    if len(argv) != 5:
        raise SystemExit("uso: commons_photo_manifest.py <catalog.json> <manifest.json> <asset-root> <output.json>")
    catalog_path, manifest_path, asset_root, output_path = map(Path, argv[1:])
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    reviews, issues = load_reviews(manifest_path)
    merged, report = merge_approved_photos(catalog, reviews, asset_root)
    report["issues"] = issues
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"attached": len(report["attached"]), "pending": len(report["pending"]), "issues": issues}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv)
