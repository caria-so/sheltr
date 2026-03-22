"""Open-Meteo current wind."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import httpx

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


@dataclass
class WindData:
    direction_deg: float  # meteorological: direction wind blows FROM
    speed_kmh: float
    gusts_kmh: float | None
    direction_label: str


def _compass_16(deg: float) -> str:
    dirs = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    i = int((deg % 360) / 22.5 + 0.5) % 16
    return dirs[i]


async def fetch_wind(lat: float, lon: float, *, client: httpx.AsyncClient | None = None) -> WindData:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "wind_speed_unit": "kmh",
    }
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        r = await client.get(OPEN_METEO, params=params)
        r.raise_for_status()
        js = r.json()
        cur = js.get("current") or {}
        spd = float(cur.get("wind_speed_10m", 0))
        direc = float(cur.get("wind_direction_10m", 0))
        gust = cur.get("wind_gusts_10m")
        gust_f = float(gust) if gust is not None else None
        return WindData(
            direction_deg=direc,
            speed_kmh=spd,
            gusts_kmh=gust_f,
            direction_label=_compass_16(direc),
        )
    finally:
        if own:
            await client.aclose()


def wind_to_dict(w: WindData) -> dict:
    return asdict(w)
