"""Sheltr FastAPI — all routes under /api; serves static SPA."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import db, scoring, strips, terrain, wind

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

app = FastAPI(title="sheltr", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "sheltr"}


@app.get("/")
def index() -> FileResponse:
    if not (STATIC / "index.html").is_file():
        raise HTTPException(404, "static/index.html missing")
    return FileResponse(STATIC / "index.html")


@app.get("/api/strips")
def api_strips() -> list[dict]:
    return [s.as_public_dict() for s in strips.STRIPS]


@app.get("/api/nearest")
def api_nearest(lat: float = Query(...), lon: float = Query(...)) -> dict:
    s, d = strips.nearest_strip(lat, lon)
    return {"strip": s.as_public_dict(), "distance_m": d}


@app.get("/api/wind")
async def api_wind(lat: float = Query(...), lon: float = Query(...)) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        w = await wind.fetch_wind(lat, lon, client=client)
    return wind.wind_to_dict(w)


@app.get("/api/terrain")
async def api_terrain(lat: float = Query(...), lon: float = Query(...)) -> dict:
    async with httpx.AsyncClient(timeout=90.0) as client:
        t = await terrain.fetch_terrain(lat, lon, client=client)
    return terrain.terrain_to_dict(t)


@app.get("/api/score")
async def api_score(
    lat: float = Query(...),
    lon: float = Query(...),
    strip_id: str | None = Query(default=None),
    observer_accuracy: float | None = Query(default=None),
) -> dict | list[dict]:
    async with httpx.AsyncClient(timeout=90.0) as client:
        w = await wind.fetch_wind(lat, lon, client=client)
        terr = await terrain.fetch_terrain(lat, lon, client=client)

    if strip_id:
        s = strips.get_strip(strip_id)
        if not s:
            raise HTTPException(404, "unknown strip_id")
        sh = scoring.shelter_score(s, w, terr, terrain_validated=True)
        result = {
            "strip_id": s.id,
            "strip": s.as_public_dict(),
            "wind": wind.wind_to_dict(w),
            "terrain": terrain.terrain_to_dict(terr),
            "score": scoring.score_to_dict(sh),
        }
    else:
        ranked = scoring.score_all_strips(w, lat, lon, terr)
        result = {
            "lat": lat,
            "lon": lon,
            "wind": wind.wind_to_dict(w),
            "terrain": terrain.terrain_to_dict(terr),
            "ranked": ranked,
        }

    # Auto-write a score_snapshot (best-effort, never blocks response)
    scores_map = {}
    if strip_id:
        scores_map[strip_id] = result["score"]["predicted"] if isinstance(result.get("score"), dict) else None
    else:
        for item in result.get("ranked", []):
            scores_map[item["strip_id"]] = item["score"]

    snap_row = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "observer_lat": lat,
        "observer_lon": lon,
        "observer_accuracy": observer_accuracy,
        "wind_dir_deg": w.direction_deg,
        "wind_speed_kmh": w.speed_kmh,
        "wind_gusts_kmh": w.gusts_kmh,
        "terrain_shield_json": terr.shield,
        "scores_json": scores_map,
    }
    snap_id = db.write_snapshot(snap_row)
    if isinstance(result, dict):
        result["snapshot_id"] = snap_id

    return result


@app.post("/api/upload-image")
async def api_upload_image(file: UploadFile) -> dict:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "file must be an image")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "image too large (10 MB max)")
    try:
        url = db.upload_image(data, file.content_type)
    except Exception as e:
        raise HTTPException(500, {"error": "upload_failed", "message": str(e)}) from e
    return {"url": url}


@app.post("/api/observations")
def api_observations_post(body: dict[str, Any] = Body(...)) -> dict:
    if "strip_id" not in body:
        raise HTTPException(400, "strip_id is required")
    row: dict[str, Any] = {
        "snapshot_id": body.get("snapshot_id"),
        "strip_id": body["strip_id"],
        "felt_sand_wind": body.get("felt_sand_wind"),
        "felt_water_state": body.get("felt_water_state"),
        "felt_comfort": body.get("felt_comfort"),
        "notes": body.get("notes"),
        "image_url": body.get("image_url"),
    }
    row = {k: v for k, v in row.items() if v is not None}
    try:
        oid = db.write_observation(row)
    except Exception as e:
        raise HTTPException(500, {"error": "insert_failed", "message": str(e)}) from e
    return {"id": oid}


@app.get("/api/observations")
def api_observations_get(
    strip_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    return db.get_observations(strip_id, limit=limit)


@app.get("/api/accuracy")
def api_accuracy(strip_id: str = Query(...)) -> dict:
    return db.get_accuracy(strip_id)
