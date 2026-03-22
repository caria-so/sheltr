"""Shelter score from wind + strip geometry + terrain shielding."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from app.strips import STRIPS, SandStrip, haversine_m
from app.terrain import TerrainProfile, sector_key
from app.wind import WindData


@dataclass
class ShieldScore:
    predicted: float  # 0–10
    exposure: float  # 0–1 higher = more exposed / worse shelter
    sand_label: str  # sheltered / moderate / exposed / avoid
    confidence: str  # geometry_only / terrain_validated


def angular_exposure(wind_from_deg: float, beach_facing_deg: float | None) -> float:
    """How much onshore exposure from wind vs beach orientation, 0–1."""
    if beach_facing_deg is None:
        return 0.5
    # Smallest angle between wind-from direction and seaward-facing direction
    a = wind_from_deg % 360
    b = beach_facing_deg % 360
    diff = abs(((a - b) + 180) % 360 - 180)
    # cos(diff): 1 = aligned, 0 at 90°, -1 opposite
    c = math.cos(math.radians(diff))
    return max(0.0, min(1.0, (c + 1.0) / 2.0))


def terrain_shield_for_wind(wind_from_deg: float, terrain: TerrainProfile) -> float:
    sk = sector_key(wind_from_deg)
    return float(terrain.shield.get(sk, 0.0))


def _speed_factor(speed_kmh: float) -> float:
    return max(0.0, min(1.0, speed_kmh / 40.0))


def _label(predicted: float) -> str:
    """Higher predicted = better shelter (10 = calm); labels match that."""
    if predicted >= 7.5:
        return "sheltered"
    if predicted >= 5.0:
        return "moderate"
    if predicted >= 2.5:
        return "exposed"
    return "avoid"


def shelter_score(
    strip: SandStrip,
    wind: WindData,
    terrain: TerrainProfile,
    *,
    terrain_validated: bool = True,
) -> ShieldScore:
    shield_w = terrain_shield_for_wind(wind.direction_deg, terrain)
    ang = angular_exposure(wind.direction_deg, strip.facing_deg)
    # Wind vs beach orientation + terrain openness in wind sector (1 − shield).
    # Single terrain term — opening was redundant with (1 − shield_w).
    openness = 1.0 - shield_w
    exposure = 0.50 * ang + 0.50 * openness
    exposure = max(0.0, min(1.0, exposure))
    sf = _speed_factor(wind.speed_kmh)
    core = (1.0 - exposure) * 0.70 + sf * 0.30
    predicted = max(0.0, min(10.0, core * 10.0))
    return ShieldScore(
        predicted=predicted,
        exposure=exposure,
        sand_label=_label(predicted),
        confidence="terrain_validated" if terrain_validated else "geometry_only",
    )


def score_to_dict(s: ShieldScore) -> dict:
    return asdict(s)


def score_all_strips(
    wind: WindData,
    lat: float,
    lon: float,
    terrain: TerrainProfile,
) -> list[dict]:
    """Rank all strips best-first using shared wind + terrain at observer."""
    scored: list[tuple[float, SandStrip, ShieldScore, float]] = []
    for strip in STRIPS:
        sh = shelter_score(strip, wind, terrain, terrain_validated=True)
        dist = haversine_m(lat, lon, strip.lat, strip.lon)
        scored.append((sh.predicted, strip, sh, dist))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "strip_id": strip.id,
            "strip": strip.as_public_dict(),
            "score": round(sh.predicted, 1),
            "label": sh.sand_label,
            "exposure": round(sh.exposure, 3),
            "distance_m": round(dist, 0),
        }
        for _, strip, sh, dist in scored
    ]
