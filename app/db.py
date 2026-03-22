"""Supabase client + score_snapshots + observations + terrain cache + image storage."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

_supabase: Client | None = None


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        url = os.environ.get("SUPABASE_URL") or os.environ.get("PROJECT_URL")
        key = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("PUBLISHABLE_KEY")
        if not url or not key:
            raise RuntimeError(
                "Set SUPABASE_URL (or PROJECT_URL) and SUPABASE_ANON_KEY (or PUBLISHABLE_KEY)",
            )
        _supabase = create_client(url, key)
    return _supabase


# ── Terrain cache (best-effort) ────────────────────────────────────────────


def round_coord(x: float) -> float:
    return round(x, 5)


def cache_terrain(lat: float, lon: float, elevation_m: float) -> None:
    try:
        sb = get_supabase()
        sb.table("terrain_cache").upsert(
            {
                "lat": round_coord(lat),
                "lon": round_coord(lon),
                "elevation_m": elevation_m,
                "fetched_at": datetime.now(UTC).isoformat(),
            },
        ).execute()
    except Exception:
        pass


def get_cached_elevation(lat: float, lon: float) -> float | None:
    try:
        sb = get_supabase()
        res = (
            sb.table("terrain_cache")
            .select("elevation_m")
            .eq("lat", round_coord(lat))
            .eq("lon", round_coord(lon))
            .maybe_single()
            .execute()
        )
        if res is None or not isinstance(res.data, dict):
            return None
        return float(res.data["elevation_m"])
    except Exception:
        return None


# ── Image storage ─────────────────────────────────────────────────────────

BUCKET = "observation-photos"


def upload_image(file_bytes: bytes, content_type: str) -> str:
    """Upload an image to Supabase Storage. Returns the public URL."""
    sb = get_supabase()
    ext = "jpg"
    if "png" in content_type:
        ext = "png"
    elif "webp" in content_type:
        ext = "webp"
    path = f"{datetime.now(UTC).strftime('%Y/%m/%d')}/{uuid4().hex}.{ext}"
    sb.storage.from_(BUCKET).upload(
        path,
        file_bytes,
        {"content-type": content_type},
    )
    return sb.storage.from_(BUCKET).get_public_url(path)


# ── Score snapshots (auto, every /api/score call) ──────────────────────────


def write_snapshot(payload: dict[str, Any]) -> str | None:
    """Insert a score_snapshots row. Returns id (uuid str) or None on error."""
    try:
        sb = get_supabase()
        res = sb.table("score_snapshots").insert(payload).execute()
        if res.data:
            return str(res.data[0].get("id", ""))
        return None
    except Exception:
        return None


# ── Observations (user-triggered, linked to a snapshot) ────────────────────


def write_observation(payload: dict[str, Any]) -> str:
    sb = get_supabase()
    res = sb.table("observations").insert(payload).execute()
    if not res.data:
        raise RuntimeError("insert returned no row")
    return str(res.data[0].get("id", ""))


def get_observations(strip_id: str | None, limit: int = 100) -> list[dict]:
    """Observations joined with their snapshot for history display."""
    sb = get_supabase()
    q = (
        sb.table("observations")
        .select("*, score_snapshots(wind_dir_deg, wind_speed_kmh, wind_gusts_kmh, scores_json)")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if strip_id:
        q = q.eq("strip_id", strip_id)
    try:
        res = q.execute()
    except Exception:
        # Fall back if join fails (table missing, etc)
        q2 = (
            sb.table("observations")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if strip_id:
            q2 = q2.eq("strip_id", strip_id)
        res = q2.execute()
    return res.data or []


def get_accuracy(strip_id: str) -> dict[str, Any]:
    """Predicted vs felt stats for a strip, with wind-quadrant breakdown."""
    rows = get_observations(strip_id, limit=5000)
    with_felt = [r for r in rows if r.get("felt_comfort") is not None]

    def avg(vals: list[float]) -> float | None:
        return sum(vals) / len(vals) if vals else None

    def predicted_for(row: dict) -> float | None:
        snap = row.get("score_snapshots")
        if isinstance(snap, dict):
            sj = snap.get("scores_json")
            if isinstance(sj, dict):
                v = sj.get(strip_id)
                if v is not None:
                    return float(v)
        # Legacy: predicted_score on the observation itself
        ps = row.get("predicted_score")
        return float(ps) if ps is not None else None

    def wind_dir_for(row: dict) -> float | None:
        snap = row.get("score_snapshots")
        if isinstance(snap, dict):
            wd = snap.get("wind_dir_deg")
            if wd is not None:
                return float(wd)
        wd = row.get("wind_dir_deg")
        return float(wd) if wd is not None else None

    pred_vals = [p for r in with_felt if (p := predicted_for(r)) is not None]
    felt_vals = [float(r["felt_comfort"]) for r in with_felt]

    quadrants: dict[str, list[dict]] = {"N": [], "E": [], "S": [], "W": []}

    def wind_quadrant(deg: float) -> str:
        d = deg % 360
        if d >= 315 or d < 45:
            return "N"
        if d < 135:
            return "E"
        if d < 225:
            return "S"
        return "W"

    for r in with_felt:
        wd = wind_dir_for(r)
        if wd is not None:
            quadrants[wind_quadrant(wd)].append(r)

    def quad_stats(qrows: list[dict]) -> dict[str, Any]:
        pf = [p for x in qrows if (p := predicted_for(x)) is not None]
        ff = [float(x["felt_comfort"]) for x in qrows if x.get("felt_comfort") is not None]
        apq, afq = avg(pf), avg(ff)
        return {
            "count": len(qrows),
            "avg_predicted": round(apq, 1) if apq is not None else None,
            "avg_felt": round(afq, 1) if afq is not None else None,
        }

    ap, af = avg(pred_vals), avg(felt_vals)
    return {
        "strip_id": strip_id,
        "count": len(with_felt),
        "avg_predicted": round(ap, 1) if ap is not None else None,
        "avg_felt": round(af, 1) if af is not None else None,
        "by_quadrant": {k: quad_stats(v) for k, v in quadrants.items()},
    }
