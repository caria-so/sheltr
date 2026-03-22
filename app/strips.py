"""Curated sand strips + haversine nearest strip."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SandStrip:
    id: str
    name: str
    parent_name: str | None
    lat: float
    lon: float
    facing_deg: float | None  # seaward direction, degrees (0=N, 90=E)
    openness_angle: float | None  # angular width of sea opening; None → default in scoring
    notes: str | None = None

    def as_public_dict(self) -> dict:
        d = asdict(self)
        return d


# Manually curated — keep in sync with Supabase `strips` seed (see supabase_setup_spec.md).
STRIPS: list[SandStrip] = [
    SandStrip(
        id="capitana",
        name="Capitana",
        parent_name="Capitana",
        lat=39.205068,
        lon=9.318388,
        facing_deg=10.0,
        openness_angle=None,
        notes="Short uniform beach facing Gulf of Cagliari (N).",
    ),
    SandStrip(
        id="mortorius",
        name="Mortorius",
        parent_name="Mortorius",
        lat=39.199177,
        lon=9.325747,
        facing_deg=None,
        openness_angle=None,
        notes="Opposite orientation to Baja Azzurra.",
    ),
    SandStrip(
        id="baja_azzurra_cala",
        name="Baja Azzurra (cala)",
        parent_name="Baja Azzurra",
        lat=39.201005,
        lon=9.323482,
        facing_deg=None,
        openness_angle=None,
        notes="Cala side.",
    ),
    SandStrip(
        id="baja_azzurra_promontory",
        name="Baja Azzurra (promontory)",
        parent_name="Baja Azzurra",
        lat=39.200300,
        lon=9.322702,
        facing_deg=None,
        openness_angle=None,
        notes="Promontory strip.",
    ),
    SandStrip(
        id="poetto_west",
        name="Poetto (Marina Piccola)",
        parent_name="Poetto",
        lat=39.2130,
        lon=9.1350,
        facing_deg=180.0,
        openness_angle=None,
        notes="Sheltered from W/NW by Sella del Diavolo.",
    ),
    SandStrip(
        id="poetto_east",
        name="Poetto (Margine Rosso)",
        parent_name="Poetto",
        lat=39.2200,
        lon=9.1900,
        facing_deg=180.0,
        openness_angle=None,
        notes="Open; less terrain shielding than west.",
    ),
]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters (WGS84 sphere)."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def nearest_strip(lat: float, lon: float) -> tuple[SandStrip, float]:
    best = min(STRIPS, key=lambda s: haversine_m(lat, lon, s.lat, s.lon))
    return best, haversine_m(lat, lon, best.lat, best.lon)


def get_strip(strip_id: str) -> SandStrip | None:
    for s in STRIPS:
        if s.id == strip_id:
            return s
    return None
