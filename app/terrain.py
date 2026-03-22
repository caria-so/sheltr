"""OpenTopoData radial sampling + shielding (terrain_cache via db)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import httpx

from app import db

# Public API datasets change; `copernicus30m` was removed (400 INVALID_REQUEST).
# srtm90m is global and stable — see https://www.opentopodata.org/datasets/srtm/
OPEN_TOPO = "https://api.opentopodata.org/v1/srtm90m"

# Elevation angle (degrees) at which sector shielding saturates at 1.0. Tune from field data.
SHIELD_FULL_ANGLE = 8.0

SECTOR_KEYS = [str(i * 22.5) for i in range(16)]  # "0.0" vs "0" — JSON uses short strings
DISTANCES_M = (200.0, 500.0, 1_000.0, 2_000.0, 5_000.0)


@dataclass
class TerrainProfile:
    raw: dict[str, float]  # sector key → max elevation MSL seen along ray (m)
    shield: dict[str, float]  # sector key → 0 open … 1 blocked

    def to_dict(self) -> dict:
        return {"raw": self.raw, "shield": self.shield}


def destination_point(lat: float, lon: float, bearing_deg: float, distance_m: float) -> tuple[float, float]:
    """WGS84 sphere forward geodesic (good enough for 5 km sampling)."""
    r = 6_371_000.0
    br = math.radians(bearing_deg)
    φ1 = math.radians(lat)
    λ1 = math.radians(lon)
    δ = distance_m / r
    sinφ1, cosφ1 = math.sin(φ1), math.cos(φ1)
    φ2 = math.asin(sinφ1 * math.cos(δ) + cosφ1 * math.sin(δ) * math.cos(br))
    λ2 = λ1 + math.atan2(
        math.sin(br) * math.sin(δ) * cosφ1,
        math.cos(δ) - sinφ1 * math.sin(φ2),
    )
    out_lat = math.degrees(φ2)
    out_lon = (math.degrees(λ2) + 540) % 360 - 180
    return out_lon, out_lat


def sample_points(lat: float, lon: float) -> list[tuple[float, float, float, float]]:
    """(lon, lat, direction_deg, distance_m) for 16 × 5 samples."""
    out: list[tuple[float, float, float, float]] = []
    for i in range(16):
        direction = i * 22.5
        for d in DISTANCES_M:
            plon, plat = destination_point(lat, lon, direction, d)
            out.append((plon, plat, direction, d))
    return out


async def _fetch_elevations_batch(
    coords: list[tuple[float, float]],
    *,
    client: httpx.AsyncClient,
) -> dict[tuple[float, float], float]:
    """OpenTopoData pipe-separated locations; returns dict keyed by rounded (lon, lat)."""
    if not coords:
        return {}
    # Chunk to stay under typical URL limits
    chunk_size = 80
    merged: dict[tuple[float, float], float] = {}
    for start in range(0, len(coords), chunk_size):
        chunk = coords[start : start + chunk_size]
        locs = "|".join(f"{lat},{lon}" for lon, lat in chunk)
        r = await client.get(OPEN_TOPO, params={"locations": locs})
        r.raise_for_status()
        js = r.json()
        for res in js.get("results") or []:
            loc = res.get("location") or {}
            if "lat" not in loc:
                continue
            lat = float(loc["lat"])
            lng = loc.get("lon", loc.get("lng"))
            if lng is None:
                continue
            lon = float(lng)
            el = res.get("elevation")
            merged[(round(lon, 5), round(lat, 5))] = float(el) if el is not None else 0.0
    return merged


def sector_key(direction_deg: float) -> str:
    i = int(round(direction_deg / 22.5)) % 16
    return str(i * 22.5)


async def fetch_elevations(
    points: list[tuple[float, float]],
    *,
    client: httpx.AsyncClient,
) -> dict[tuple[float, float], float]:
    """Fetch elevations; uses Supabase terrain_cache first."""
    unique: dict[tuple[float, float], tuple[float, float]] = {}
    for lon, lat in points:
        k = (round(lon, 5), round(lat, 5))
        unique[k] = (lon, lat)

    out: dict[tuple[float, float], float] = {}
    missing: list[tuple[float, float]] = []
    for k, (lon, lat) in unique.items():
        cached = db.get_cached_elevation(lat, lon)
        if cached is not None:
            out[k] = cached
        else:
            missing.append((lon, lat))

    if missing:
        fetched = await _fetch_elevations_batch(missing, client=client)
        for k, el in fetched.items():
            lon, lat = k
            db.cache_terrain(lat, lon, el)
            out[k] = el
        # retry any still missing
        for lon, lat in missing:
            k = (round(lon, 5), round(lat, 5))
            if k not in out:
                out[k] = 0.0

    return out


def compute_shielding(
    elevations: dict[tuple[float, float], float],
    origin_lat: float,
    origin_lon: float,
    samples: list[tuple[float, float, float, float]],
) -> TerrainProfile:
    """Build raw + shield dicts keyed by sector string (0 … 337.5)."""
    origin_key = (round(origin_lon, 5), round(origin_lat, 5))
    elev0 = elevations.get(origin_key, 0.0)

    raw_by_sector: dict[str, list[float]] = {k: [] for k in SECTOR_KEYS}
    angles_by_sector: dict[str, list[float]] = {k: [] for k in SECTOR_KEYS}

    for plon, plat, direction, dist in samples:
        k = (round(plon, 5), round(plat, 5))
        el = elevations.get(k, elev0)
        sk = sector_key(direction)
        raw_by_sector[sk].append(el)
        horiz = max(dist, 1.0)
        angle_deg = math.degrees(math.atan2(max(0.0, el - elev0), horiz))
        angles_by_sector[sk].append(angle_deg)

    raw: dict[str, float] = {}
    shield: dict[str, float] = {}
    for sk in SECTOR_KEYS:
        vals = raw_by_sector.get(sk) or [elev0]
        raw[sk] = max(vals)
        ang = max(angles_by_sector.get(sk) or [0.0])
        shield[sk] = max(
            0.0,
            min(1.0, ang / SHIELD_FULL_ANGLE),
        )

    return TerrainProfile(raw=raw, shield=shield)


async def fetch_terrain(lat: float, lon: float, *, client: httpx.AsyncClient | None = None) -> TerrainProfile:
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=60.0)
    try:
        samples = sample_points(lat, lon)
        pts = [(lon, lat) for lon, lat, _, _ in samples]
        # origin elevation
        origin_elev = await _fetch_elevations_batch([(lon, lat)], client=client)
        if origin_elev:
            for k, el in origin_elev.items():
                db.cache_terrain(lat, lon, el)
        all_pts = list({*pts, (lon, lat)})
        coords = [(lon, lat) for lon, lat in all_pts]
        elevations = await fetch_elevations(coords, client=client)
        if (round(lon, 5), round(lat, 5)) not in elevations:
            elevations[(round(lon, 5), round(lat, 5))] = next(iter(origin_elev.values()), 0.0)
        return compute_shielding(elevations, lat, lon, samples)
    finally:
        if own:
            await client.aclose()


def terrain_to_dict(t: TerrainProfile) -> dict:
    return asdict(t)
