"""Sand strips - now loaded from database with polygon support."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Any


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
    geometry: list[tuple[float, float]] | None = None  # Polygon coordinates
    area_m2: float | None = None
    source: str = "manual"
    validated: bool = False

    def as_public_dict(self) -> dict:
        d = asdict(self)
        return d


# Cache for loaded strips
_STRIPS_CACHE: list[SandStrip] | None = None


def load_strips_from_db() -> list[SandStrip]:
    """Load all strips from database, with fallback to hardcoded list."""
    global _STRIPS_CACHE
    if _STRIPS_CACHE is not None:
        return _STRIPS_CACHE
    
    try:
        # Import db here to avoid circular import
        from app import db
        
        # Try to load from database
        sb = db.get_supabase()
        result = sb.table("strips").select("*").execute()
        
        if result.data:
            strips = []
            for row in result.data:
                # Parse geometry if stored as JSON string
                geometry = None
                if row.get("geometry"):
                    if isinstance(row["geometry"], str):
                        geometry_data = json.loads(row["geometry"])
                    else:
                        geometry_data = row["geometry"]
                    geometry = [(coord[0], coord[1]) for coord in geometry_data]
                
                strip = SandStrip(
                    id=row["id"],
                    name=row["name"],
                    parent_name=row.get("parent_name"),
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    facing_deg=float(row["facing_deg"]) if row.get("facing_deg") else None,
                    openness_angle=float(row["openness_angle"]) if row.get("openness_angle") else None,
                    notes=row.get("notes"),
                    geometry=geometry,
                    area_m2=float(row["area_m2"]) if row.get("area_m2") else None,
                    source=row.get("source", "manual"),
                    validated=row.get("validated", False),
                )
                strips.append(strip)
            
            _STRIPS_CACHE = strips
            return strips
    except Exception:
        # Database not available or error - fall back to hardcoded
        pass
    
    # Fallback to hardcoded beaches
    _STRIPS_CACHE = [
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
    
    return _STRIPS_CACHE


STRIPS = load_strips_from_db()


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters (WGS84 sphere)."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def point_in_polygon(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
    """Check if point is inside polygon using ray casting algorithm."""
    if not polygon or len(polygon) < 3:
        return False
    
    inside = False
    p1_lat, p1_lon = polygon[0]
    
    for i in range(1, len(polygon) + 1):
        p2_lat, p2_lon = polygon[i % len(polygon)]
        
        if lon > min(p1_lon, p2_lon):
            if lon <= max(p1_lon, p2_lon):
                if lat <= max(p1_lat, p2_lat):
                    if p1_lon != p2_lon:
                        lat_intersection = (lon - p1_lon) * (p2_lat - p1_lat) / (p2_lon - p1_lon) + p1_lat
                    if p1_lat == p2_lat or lat <= lat_intersection:
                        inside = not inside
        
        p1_lat, p1_lon = p2_lat, p2_lon
    
    return inside


def nearest_strip(lat: float, lon: float) -> tuple[SandStrip, float]:
    """Find nearest strip, considering both polygons and points."""
    strips = load_strips_from_db()
    
    # First check if we're inside any polygon
    for s in strips:
        if s.geometry and point_in_polygon(lat, lon, s.geometry):
            return s, 0.0  # Distance is 0 when inside the beach
    
    # Otherwise find nearest by centroid distance
    best = min(strips, key=lambda s: haversine_m(lat, lon, s.lat, s.lon))
    
    # For polygon beaches, calculate distance to nearest edge
    if best.geometry:
        min_dist = float('inf')
        for coord in best.geometry:
            dist = haversine_m(lat, lon, coord[0], coord[1])
            min_dist = min(min_dist, dist)
        return best, min_dist
    
    return best, haversine_m(lat, lon, best.lat, best.lon)


def get_strip(strip_id: str) -> SandStrip | None:
    strips = load_strips_from_db()
    for s in strips:
        if s.id == strip_id:
            return s
    return None
