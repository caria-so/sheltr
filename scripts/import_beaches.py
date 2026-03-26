"""Import South Sardinia beaches from OpenStreetMap into Supabase."""

import json
import math
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from app.db import get_supabase

load_dotenv()

# South Sardinia bounding box (roughly Cagliari province)
SOUTH_SARDINIA_BBOX = {
    "min_lat": 38.85,
    "max_lat": 39.65,
    "min_lon": 8.35,
    "max_lon": 9.75
}


def calculate_centroid(coords: list[tuple[float, float]]) -> tuple[float, float]:
    """Calculate centroid of polygon coordinates."""
    if not coords:
        return (0, 0)
    lat_sum = sum(lat for lat, lon in coords)
    lon_sum = sum(lon for lat, lon in coords)
    return (lat_sum / len(coords), lon_sum / len(coords))


def calculate_beach_facing(coords: list[tuple[float, float]]) -> float | None:
    """Calculate predominant facing direction of a beach (perpendicular to coastline)."""
    if len(coords) < 2:
        return None
    
    # Take middle segment of beach for orientation
    mid = len(coords) // 2
    if mid > 0:
        lat1, lon1 = coords[mid - 1]
        lat2, lon2 = coords[mid]
        
        # Calculate bearing along coastline
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        coastline_bearing = math.degrees(math.atan2(dlon, dlat))
        
        # Beach faces perpendicular to coastline (add 90 degrees)
        # Assume beach faces seaward (towards open water)
        facing = (coastline_bearing + 90) % 360
        return facing
    return None


def calculate_area(coords: list[tuple[float, float]]) -> float:
    """Calculate approximate area using shoelace formula (in m²)."""
    if len(coords) < 3:
        return 0
    
    # Convert to meters using simple equirectangular projection
    lat_center = sum(lat for lat, _ in coords) / len(coords)
    m_per_deg_lat = 111320
    m_per_deg_lon = 111320 * math.cos(math.radians(lat_center))
    
    # Convert coords to meters
    coords_m = [(lat * m_per_deg_lat, lon * m_per_deg_lon) for lat, lon in coords]
    
    # Shoelace formula
    area = 0
    for i in range(len(coords_m)):
        j = (i + 1) % len(coords_m)
        area += coords_m[i][0] * coords_m[j][1]
        area -= coords_m[j][0] * coords_m[i][1]
    
    return abs(area) / 2


def fetch_beaches_overpass():
    """Fetch beaches from OpenStreetMap using Overpass API."""
    print("Fetching beaches from OpenStreetMap...")
    
    # Simpler query - just get beaches and sandy areas
    query = f"""
    [out:json][timeout:90];
    (
      // Natural beaches
      way["natural"="beach"]({SOUTH_SARDINIA_BBOX['min_lat']},{SOUTH_SARDINIA_BBOX['min_lon']},{SOUTH_SARDINIA_BBOX['max_lat']},{SOUTH_SARDINIA_BBOX['max_lon']});
      // Leisure beaches  
      way["leisure"="beach"]({SOUTH_SARDINIA_BBOX['min_lat']},{SOUTH_SARDINIA_BBOX['min_lon']},{SOUTH_SARDINIA_BBOX['max_lat']},{SOUTH_SARDINIA_BBOX['max_lon']});
    );
    out geom;
    """
    
    # Try multiple times with increasing timeout
    for attempt in range(3):
        try:
            timeout = 120 + (attempt * 60)  # 120s, 180s, 240s
            print(f"Attempt {attempt + 1}/3 (timeout: {timeout}s)...")
            
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    "https://overpass-api.de/api/interpreter",
                    data={"data": query}
                )
                response.raise_for_status()
                return response.json()
        except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
            if attempt == 2:  # Last attempt
                print(f"Failed after 3 attempts: {e}")
                print("\nFalling back to local sample data...")
                return get_fallback_beaches()
            else:
                print(f"Attempt {attempt + 1} failed, retrying...")
                continue
    
    return get_fallback_beaches()


def get_fallback_beaches():
    """Return sample beaches if API fails."""
    # Major beaches in South Sardinia
    return {
        "elements": [
            {
                "type": "way",
                "id": 1,
                "tags": {"name": "Poetto", "natural": "beach"},
                "geometry": [
                    {"lat": 39.2041, "lon": 9.1547},
                    {"lat": 39.2065, "lon": 9.1580},
                    {"lat": 39.2089, "lon": 9.1613},
                    {"lat": 39.2113, "lon": 9.1646},
                    {"lat": 39.2137, "lon": 9.1679},
                ]
            },
            {
                "type": "way",
                "id": 2,
                "tags": {"name": "Chia", "natural": "beach"},
                "geometry": [
                    {"lat": 38.8917, "lon": 8.8742},
                    {"lat": 38.8934, "lon": 8.8758},
                    {"lat": 38.8951, "lon": 8.8774},
                    {"lat": 38.8968, "lon": 8.8790},
                ]
            },
            {
                "type": "way", 
                "id": 3,
                "tags": {"name": "Porto Pino", "natural": "beach"},
                "geometry": [
                    {"lat": 39.0397, "lon": 8.5894},
                    {"lat": 39.0415, "lon": 8.5912},
                    {"lat": 39.0433, "lon": 8.5930},
                    {"lat": 39.0451, "lon": 8.5948},
                ]
            },
            {
                "type": "way",
                "id": 4,
                "tags": {"name": "Villasimius", "natural": "beach"},
                "geometry": [
                    {"lat": 39.1212, "lon": 9.5145},
                    {"lat": 39.1228, "lon": 9.5162},
                    {"lat": 39.1244, "lon": 9.5179},
                    {"lat": 39.1260, "lon": 9.5196},
                ]
            },
            {
                "type": "way",
                "id": 5,
                "tags": {"name": "Costa Rei", "natural": "beach"},
                "geometry": [
                    {"lat": 39.2554, "lon": 9.5745},
                    {"lat": 39.2572, "lon": 9.5763},
                    {"lat": 39.2590, "lon": 9.5781},
                    {"lat": 39.2608, "lon": 9.5799},
                ]
            }
        ]
    }


def process_osm_beaches(osm_data):
    """Process OSM data into beach records."""
    beaches = []
    seen_names = set()
    
    for element in osm_data.get("elements", []):
        if element.get("type") != "way":
            continue
            
        tags = element.get("tags", {})
        name = tags.get("name", tags.get("name:it", tags.get("name:sc")))
        
        if not name:
            continue
            
        # Get coordinates from geometry
        geometry = element.get("geometry", [])
        if not geometry:
            continue
            
        coords = [(node["lat"], node["lon"]) for node in geometry]
        
        # Skip very small areas (likely errors)
        area = calculate_area(coords)
        if area < 100:  # Less than 100m²
            continue
        
        # Calculate beach properties
        centroid = calculate_centroid(coords)
        facing = calculate_beach_facing(coords)
        
        # Create unique ID
        beach_id = f"osm_{element['id']}"
        
        # Handle duplicate names
        display_name = name
        if name in seen_names:
            # Add area or coordinates to distinguish
            display_name = f"{name} ({centroid[0]:.3f},{centroid[1]:.3f})"
        seen_names.add(name)
        
        beach_data = {
            "id": beach_id,
            "name": display_name,
            "parent_name": tags.get("place", None),
            "lat": round(centroid[0], 6),
            "lon": round(centroid[1], 6),
            "facing_deg": round(facing, 1) if facing else None,
            "geometry": coords,  # Store as polygon
            "area_m2": round(area, 0),
            "source": "openstreetmap",
            "osm_id": element["id"],
            "osm_tags": tags,
            "validated": False
        }
        
        beaches.append(beach_data)
    
    return beaches


def import_to_supabase(beaches):
    """Import beaches to Supabase database."""
    sb = get_supabase()
    
    print(f"Importing {len(beaches)} beaches to Supabase...")
    
    for beach in beaches:
        # Prepare data for strips table
        strip_data = {
            "id": beach["id"],
            "name": beach["name"],
            "parent_name": beach["parent_name"],
            "lat": beach["lat"],
            "lon": beach["lon"],
            "facing_deg": beach["facing_deg"],
            "geometry": json.dumps(beach["geometry"]),  # Store as JSON
            "area_m2": beach["area_m2"],
            "source": beach["source"],
            "validated": beach["validated"],
            "notes": f"OSM ID: {beach['osm_id']}"
        }
        
        try:
            # Upsert to handle duplicates
            sb.table("strips").upsert(strip_data).execute()
            print(f"✓ Imported: {beach['name']}")
        except Exception as e:
            print(f"✗ Failed to import {beach['name']}: {e}")


def main():
    """Main import function."""
    print("=== South Sardinia Beach Import ===")
    print(f"Bounding box: {SOUTH_SARDINIA_BBOX}")
    
    # Fetch from OSM
    osm_data = fetch_beaches_overpass()
    print(f"Fetched {len(osm_data.get('elements', []))} elements from OSM")
    
    # Process beaches
    beaches = process_osm_beaches(osm_data)
    print(f"Processed {len(beaches)} valid beaches")
    
    # Sort by area (largest first) for better visibility
    beaches.sort(key=lambda x: x["area_m2"], reverse=True)
    
    # Show summary
    print("\nTop 10 beaches by area:")
    for beach in beaches[:10]:
        print(f"  - {beach['name']}: {beach['area_m2']:,.0f}m² @ ({beach['lat']:.4f},{beach['lon']:.4f})")
    
    # Import to database
    response = input("\nProceed with import to Supabase? (y/n): ")
    if response.lower() == 'y':
        import_to_supabase(beaches)
        print(f"\n✅ Import complete! {len(beaches)} beaches added.")
    else:
        print("Import cancelled.")
        
    # Save local backup
    backup_file = Path(__file__).parent / "beaches_backup.json"
    with open(backup_file, "w") as f:
        json.dump(beaches, f, indent=2)
    print(f"Backup saved to {backup_file}")


if __name__ == "__main__":
    main()