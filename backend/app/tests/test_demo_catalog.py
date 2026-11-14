import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.domain.demo_catalog import create_demo_catalog
from app.domain.market import InitialMarket


def test_demo_requires_development_and_separate_snapshots() -> None:
    assert not Settings(_env_file=None).enable_demo_catalog
    with pytest.raises(ValidationError):
        Settings(_env_file=None, enable_demo_catalog=True, app_environment="production")
    settings = Settings(_env_file=None, enable_demo_catalog=True, app_environment="test")
    assert settings.snapshot_path == settings.demo_snapshot_path


@pytest.mark.parametrize("mode", ["FIVE_A_SIDE", "ELEVEN_A_SIDE"])
def test_demo_catalog_can_fill_twenty_teams(mode: str) -> None:
    catalog = create_demo_catalog()
    assert catalog.source == "synthetic-demo"
    assert all(player.name.startswith("DEMO ") for player in catalog.players)
    clubs = {player.club_code: 5_000_000_000 for player in catalog.players}
    assert len(clubs) == 20
    assert InitialMarket(catalog, mode, clubs).viable().viable
