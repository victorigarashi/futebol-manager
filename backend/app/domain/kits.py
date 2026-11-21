"""Match kits: one OFFICIAL selection per match, chosen by the server and drawn identically
by the 2D and the 3D renderers.

Colours are compared perceptually (CIELAB, CIEDE2000), never by raw hex values, on the
shirt (the dominant area at match size), the shorts and the socks; lightness is checked
separately so two kits never depend only on hue (red/green colour-blindness).

Data honesty: the club palette below is the same primary/secondary pair the app already
used. Nothing here claims to be a club's official away or third kit: the alternatives are
generic combinations, labelled as such (``"generic": True``).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

CLUB_COLORS: dict[str, tuple[str, str]] = {
    "FLA": ("#C8102E", "#111111"), "PAL": ("#0B6B3A", "#FFFFFF"), "COR": ("#F4F4F4", "#111111"), "SAO": ("#E8E8E8", "#D7262B"),
    "SAN": ("#F7F7F7", "#111111"), "FLU": ("#7A1F3D", "#0F7A4D"), "BOT": ("#1A1A1A", "#FFFFFF"), "VAS": ("#111111", "#FFFFFF"),
    "CRU": ("#1D4FA3", "#FFFFFF"), "CAM": ("#1B1B1B", "#F5F5F5"), "GRE": ("#1E8BD0", "#111111"), "INT": ("#D11F2F", "#FFFFFF"),
    "BAH": ("#1C4CA0", "#E2231A"), "VIT": ("#D21F2A", "#111111"), "CAP": ("#C8102E", "#111111"), "CFC": ("#0E6B3A", "#FFFFFF"),
    "RBB": ("#F4F4F4", "#D6182B"), "MIR": ("#F2C230", "#0D6E3A"), "CHA": ("#169E58", "#FFFFFF"), "REM": ("#163A7A", "#FFFFFF"),
}
DEFAULT_COLORS = ("#26B47D", "#0D1117")
# Generic alternatives (original, not any club's real kit), tried in order when needed.
GENERIC = [("#FFFFFF", "#1B1B1B", "plain"), ("#151515", "#F2F2F2", "plain"), ("#FFD31A", "#14305C", "sash"), ("#7CC8FF", "#0E2A4F", "hoops"),
           ("#FF7A00", "#141414", "plain"), ("#6A2BD1", "#FFFFFF", "sash"), ("#D9254A", "#FFFFFF", "hoops"), ("#1F8F4E", "#FFFFFF", "plain")]
KEEPERS = ["#F5B83D", "#9B6BFF", "#2EC4B6", "#FF5FA2", "#C6F24E", "#232323", "#FF8C1A", "#5CE1E6"]
# Thresholds (CIEDE2000 units). Shirts must be clearly different at match size; lightness
# alone must also separate them so the kits never rely only on hue.
SHIRT_MIN = 32.0
LIGHTNESS_MIN = 18.0
KEEPER_MIN = 28.0


@dataclass(frozen=True)
class Kit:
    id: str            # HOME, AWAY, THIRD, GENERIC-n, GK-n
    shirt: str
    shorts: str
    socks: str
    trim: str
    number: str
    pattern: str = "plain"   # plain | stripes | hoops | sash
    generic: bool = False


# ------------------------------------------------------------------ colour science
def _srgb_to_lab(hex_color: str) -> tuple[float, float, float]:
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    x = (lin[0] * 0.4124 + lin[1] * 0.3576 + lin[2] * 0.1805) / 0.95047
    y = lin[0] * 0.2126 + lin[1] * 0.7152 + lin[2] * 0.0722
    z = (lin[0] * 0.0193 + lin[1] * 0.1192 + lin[2] * 0.9505) / 1.08883
    f = [t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116 for t in (x, y, z)]
    return 116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])


def delta_e(c1: str, c2: str) -> float:
    """CIEDE2000 colour difference between two hex colours."""
    l1, a1, b1 = _srgb_to_lab(c1)
    l2, a2, b2 = _srgb_to_lab(c2)
    avg_l = (l1 + l2) / 2
    c1_, c2_ = math.hypot(a1, b1), math.hypot(a2, b2)
    avg_c = (c1_ + c2_) / 2
    g = 0.5 * (1 - math.sqrt(avg_c ** 7 / (avg_c ** 7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + g), a2 * (1 + g)
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    avg_cp = (c1p + c2p) / 2
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    if abs(h1p - h2p) > 180:
        avg_hp = (h1p + h2p + 360) / 2
    else:
        avg_hp = (h1p + h2p) / 2
    t = (1 - 0.17 * math.cos(math.radians(avg_hp - 30)) + 0.24 * math.cos(math.radians(2 * avg_hp))
         + 0.32 * math.cos(math.radians(3 * avg_hp + 6)) - 0.20 * math.cos(math.radians(4 * avg_hp - 63)))
    dh = h2p - h1p
    if abs(dh) > 180:
        dh += -360 if h2p > h1p else 360
    if c1p * c2p == 0:
        dh = 0
    dl, dc = l2 - l1, c2p - c1p
    dhh = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dh / 2))
    sl = 1 + 0.015 * (avg_l - 50) ** 2 / math.sqrt(20 + (avg_l - 50) ** 2)
    sc = 1 + 0.045 * avg_cp
    sh = 1 + 0.015 * avg_cp * t
    d_theta = 30 * math.exp(-(((avg_hp - 275) / 25) ** 2))
    rc = 2 * math.sqrt(avg_cp ** 7 / (avg_cp ** 7 + 25 ** 7))
    rt = -rc * math.sin(math.radians(2 * d_theta))
    return math.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dhh / sh) ** 2 + rt * (dc / sc) * (dhh / sh))


def lightness(color: str) -> float:
    return _srgb_to_lab(color)[0]


def ink(color: str) -> str:
    return "#111111" if lightness(color) > 62 else "#FFFFFF"


# ------------------------------------------------------------------ kits of a club
def club_kits(club: str) -> list[Kit]:
    primary, secondary = CLUB_COLORS.get(club, DEFAULT_COLORS)
    generic = club not in CLUB_COLORS
    home = Kit("HOME", primary, secondary, primary, secondary, ink(primary), generic=generic)
    # Away / third: generic inversions of the club palette (labelled generic, not official).
    away = Kit("AWAY", secondary, primary, secondary, primary, ink(secondary), "plain", True)
    third_shirt = "#FFFFFF" if lightness(primary) < 55 and lightness(secondary) < 55 else "#151515"
    third = Kit("THIRD", third_shirt, primary, third_shirt, primary, ink(third_shirt), "sash", True)
    return [home, away, third]


def kit_distance(a: Kit, b: Kit) -> float:
    """Weighted by visible area at match size: shirt 65%, shorts 25%, socks 10%."""
    return 0.65 * delta_e(a.shirt, b.shirt) + 0.25 * delta_e(a.shorts, b.shorts) + 0.10 * delta_e(a.socks, b.socks)


def clash(a: Kit, b: Kit) -> bool:
    shirt = delta_e(a.shirt, b.shirt)
    if shirt < SHIRT_MIN:
        return True
    # Same lightness: only hue separates them (fails for colour-blind players) -> need more.
    if abs(lightness(a.shirt) - lightness(b.shirt)) < LIGHTNESS_MIN and shirt < SHIRT_MIN * 1.6 and a.pattern == b.pattern:
        return True
    return kit_distance(a, b) < SHIRT_MIN * 0.9


def select_kits(home: str, away: str) -> dict[str, dict[str, object]]:
    """Official selection for a match: home wears its first kit; the away side the first of
    its kits (then generic ones) that does not clash; keepers stand out from everybody."""
    home_kit = club_kits(home)[0]
    candidates = club_kits(away) + [Kit(f"GENERIC-{i + 1}", s, sh, s, sh, ink(s), p, True) for i, (s, sh, p) in enumerate(GENERIC)]
    away_kit = next((k for k in candidates if not clash(home_kit, k)), None)
    if away_kit is None:
        away_kit = max(candidates, key=lambda k: kit_distance(home_kit, k))
    outfield = [home_kit, away_kit]

    def keeper(avoid: list[str], tag: str) -> Kit:
        best = max(KEEPERS, key=lambda c: min(delta_e(c, x) for x in avoid))
        for c in KEEPERS:
            if min(delta_e(c, x) for x in avoid) >= KEEPER_MIN:
                best = c
                break
        shorts = "#1E1E24" if lightness(best) > 45 else "#F2F2F2"
        return Kit(tag, best, shorts, best, shorts, ink(best), "plain", True)

    shirts = [k.shirt for k in outfield]
    home_gk = keeper(shirts, "GK-1")
    away_gk = keeper(shirts + [home_gk.shirt], "GK-2")
    return {"home": asdict(home_kit), "away": asdict(away_kit), "home_gk": asdict(home_gk), "away_gk": asdict(away_gk)}
