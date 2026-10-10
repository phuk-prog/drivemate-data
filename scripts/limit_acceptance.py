#!/usr/bin/env python3
"""Speed-limit and speed-camera acceptance check against generated map files (OpenStreetMap only).

For each checkpoint (lat, lon, heading plus expect_mph, expect_no_data or expect_camera_within_m)
reports MATCH, MISMATCH or NO_DATA. The limit lookup mirrors the Android app
(OwnMap.limitsAlong + SpeedLimitMatcher): the half-degree square limits-<floor(lat*2)>_<floor(lon*2)>.json,
nearest mapped segment within 15 m, ignoring segments that cross the heading (35..145 degrees apart),
km/h shown as whole mph.

Usage: limit_acceptance.py --limits-dir DIR --cameras cameras-uk.json --checkpoints FILE
                           [--report out.json] [--summary summary.md]
Exit status 1 only when a checkpoint is a MISMATCH.
"""
import argparse
import json
import math
import os
import sys

MPH = 1.609344
NEAR_M = 15.0
EARTH = 6371008.8


def square_name(lat, lon):
    return f"limits-{math.floor(lat * 2)}_{math.floor(lon * 2)}.json"


def _xy(lat0, lat, lon, lon0):
    return (math.radians(lon - lon0) * math.cos(math.radians(lat0)) * EARTH, math.radians(lat - lat0) * EARTH)


def distance_m(lat1, lon1, lat2, lon2):
    x, y = _xy(lat1, lat2, lon2, lon1)
    return math.hypot(x, y)


def bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d = math.radians(lon2 - lon1)
    y = math.sin(d) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(d)
    return math.degrees(math.atan2(y, x)) % 360


def angle_diff(a, b):
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


def point_to_segment_m(lat, lon, a, b):
    """Distance in metres from (lat, lon) to segment a-b, each (lat, lon)."""
    px, py = 0.0, 0.0
    ax, ay = _xy(lat, a[0], a[1], lon)
    bx, by = _xy(lat, b[0], b[1], lon)
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / n))
    return math.hypot(ax + t * dx - px, ay + t * dy - py)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def lookup_limit(limits_dir, lat, lon, heading):
    """Return (mph or None, reason). None means no mapped limit near the point."""
    doc = load_json(os.path.join(limits_dir, square_name(lat, lon)))
    if doc is None:
        return None, "square file missing"
    best, best_d = None, NEAR_M
    for way in doc.get("ways", []):
        kmh, pts = way[0], way[1]
        for i in range(len(pts) - 1):
            a = (pts[i][1], pts[i][0])
            b = (pts[i + 1][1], pts[i + 1][0])
            if heading is not None:
                diff = angle_diff(heading, bearing(a[0], a[1], b[0], b[1]))
                if 35 < diff < 145:
                    continue
            d = point_to_segment_m(lat, lon, a, b)
            if d < best_d:
                best_d, best = d, kmh
    if best is None:
        return None, "no mapped limit within 15 m"
    return round(best / MPH), "ok"


def nearest_camera_m(cameras, lat, lon):
    best = None
    for el in (cameras or {}).get("elements", []):
        if el.get("type") != "node" or "lat" not in el:
            continue
        d = distance_m(lat, lon, el["lat"], el["lon"])
        if best is None or d < best:
            best = d
    return best


def check_one(cp, limits_dir, cameras):
    out = {"id": cp.get("id"), "name": cp.get("name"), "lat": cp["lat"], "lon": cp["lon"], "source": cp.get("source")}
    if "expect_camera_within_m" in cp:
        want = float(cp["expect_camera_within_m"])
        out["expected"] = f"camera within {want:g} m"
        if cameras is None:
            out.update(status="NO_DATA", detail="cameras file missing")
            return out
        d = nearest_camera_m(cameras, cp["lat"], cp["lon"])
        out["nearest_camera_m"] = None if d is None else round(d, 1)
        out["status"] = "MATCH" if d is not None and d <= want else "MISMATCH"
        out["detail"] = "no camera in file" if d is None else f"nearest camera {d:.1f} m away"
        return out
    heading = cp.get("heading")
    out["heading"] = heading
    mph, why = lookup_limit(limits_dir, cp["lat"], cp["lon"], heading)
    out["found_mph"] = mph
    if cp.get("expect_no_data"):
        out["expected"] = "no limit"
        if mph is None:
            out.update(status="MATCH" if why != "square file missing" else "NO_DATA", detail=why)
        else:
            out.update(status="MISMATCH", detail=f"found {mph} mph")
        return out
    want = cp["expect_mph"]
    out["expected"] = f"{want} mph"
    if mph is None:
        out.update(status="NO_DATA", detail=why)
    elif mph == want:
        out.update(status="MATCH", detail=f"{mph} mph")
    else:
        out.update(status="MISMATCH", detail=f"found {mph} mph")
    return out


def run(limits_dir, cameras_path, checkpoints_path):
    spec = load_json(checkpoints_path)
    if not spec or not spec.get("checkpoints"):
        raise SystemExit(f"no checkpoints in {checkpoints_path}")
    cameras = load_json(cameras_path) if cameras_path else None
    results = [check_one(cp, limits_dir, cameras) for cp in spec["checkpoints"]]
    counts = {k: sum(1 for r in results if r["status"] == k) for k in ("MATCH", "MISMATCH", "NO_DATA")}
    return {"region": spec.get("region"), "counts": counts, "results": results}


def markdown(report):
    c = report["counts"]
    lines = [f"### Speed limit and camera acceptance ({report.get('region')})",
             f"MATCH {c['MATCH']}, MISMATCH {c['MISMATCH']}, NO_DATA {c['NO_DATA']}", "",
             "| Result | Checkpoint | Expected | Detail |", "|---|---|---|---|"]
    for r in report["results"]:
        lines.append(f"| {r['status']} | {r['id']} | {r['expected']} | {r['detail']} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limits-dir", required=True)
    ap.add_argument("--cameras")
    ap.add_argument("--checkpoints", required=True)
    ap.add_argument("--report")
    ap.add_argument("--summary")
    a = ap.parse_args(argv)
    report = run(a.limits_dir, a.cameras, a.checkpoints)
    text = markdown(report)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
    if a.summary:
        with open(a.summary, "a", encoding="utf-8") as f:
            f.write(text)
    return 1 if report["counts"]["MISMATCH"] else 0


if __name__ == "__main__":
    sys.exit(main())
