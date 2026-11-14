from dataclasses import dataclass


@dataclass(frozen=True)
class ClubSeed:
    code: str
    name: str
    sort_order: int


CLUBS: tuple[ClubSeed, ...] = (
    ClubSeed("FLA", "Flamengo", 1),
    ClubSeed("PAL", "Palmeiras", 2),
    ClubSeed("COR", "Corinthians", 3),
    ClubSeed("SAO", "São Paulo", 4),
    ClubSeed("SAN", "Santos", 5),
    ClubSeed("FLU", "Fluminense", 6),
    ClubSeed("BOT", "Botafogo", 7),
    ClubSeed("VAS", "Vasco", 8),
    ClubSeed("CRU", "Cruzeiro", 9),
    ClubSeed("CAM", "Atlético-MG", 10),
    ClubSeed("GRE", "Grêmio", 11),
    ClubSeed("INT", "Internacional", 12),
    ClubSeed("BAH", "Bahia", 13),
    ClubSeed("VIT", "Vitória", 14),
    ClubSeed("CAP", "Athletico-PR", 15),
    ClubSeed("CFC", "Coritiba", 16),
    ClubSeed("RBB", "Red Bull Bragantino", 17),
    ClubSeed("MIR", "Mirassol", 18),
    ClubSeed("CHA", "Chapecoense", 19),
    ClubSeed("REM", "Remo", 20),
)
