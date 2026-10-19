#!/usr/bin/env python3
"""
Bounty Target Finder - local web app.

Reads the public, hourly-updated program feeds from
https://github.com/arkadiyt/bounty-targets-data and lets you filter programs
by scope keyword and reward type. It does not scan or touch any target.
"""

import csv
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from flask import Flask, Response, jsonify, render_template, request

BASE = "https://raw.githubusercontent.com/arkadiyt/bounty-targets-data/main/data/"
DATA_SOURCES = {
    "HackerOne": BASE + "hackerone_data.json",
    "Bugcrowd": BASE + "bugcrowd_data.json",
    "Intigriti": BASE + "intigriti_data.json",
    "YesWeHack": BASE + "yeswehack_data.json",
}

CACHE_TTL = 3600  # the source updates hourly, so fetch at most once per hour
SCOPE_PREVIEW = 5  # scopes sent per program in the browser view

app = Flask(__name__)

_cache = {name: {"data": [], "fetched": 0.0, "error": None} for name in DATA_SOURCES}
_lock = threading.Lock()


# --------------------------------------------------------------------------
# Feed loading
# --------------------------------------------------------------------------
def _fetch(platform):
    resp = requests.get(DATA_SOURCES[platform], timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("unexpected feed format")
    return data


def load_feeds():
    """Return the cached feeds, refreshing any that are older than CACHE_TTL."""
    with _lock:
        now = time.time()
        stale = [p for p, c in _cache.items() if now - c["fetched"] > CACHE_TTL]
        if stale:
            with ThreadPoolExecutor(max_workers=len(stale)) as pool:
                futures = {p: pool.submit(_fetch, p) for p in stale}
            for platform, fut in futures.items():
                try:
                    _cache[platform]["data"] = fut.result()
                    _cache[platform]["fetched"] = now
                    _cache[platform]["error"] = None
                except Exception as err:  # keep serving old data if we have it
                    _cache[platform]["error"] = str(err)
                    if _cache[platform]["data"]:
                        _cache[platform]["fetched"] = now - CACHE_TTL + 300  # retry in 5 min
        return {p: dict(c) for p, c in _cache.items()}


# --------------------------------------------------------------------------
# Normalising the different platform schemas
# --------------------------------------------------------------------------
def is_paid(entry):
    """HackerOne exposes a boolean; the others expose payout amounts."""
    if entry.get("offers_bounties") or entry.get("can_claim_bounty"):
        return True
    for key in ("max_payout", "max_bounty", "min_bounty"):
        value = entry.get(key)
        if isinstance(value, dict):
            value = value.get("value")
        try:
            if value and float(value) > 0:
                return True
        except (TypeError, ValueError):
            pass
    return False


def program_url(entry, platform):
    url = entry.get("url") or entry.get("link") or ""
    if not url and platform == "YesWeHack" and entry.get("slug"):
        url = "https://yeswehack.com/programs/" + str(entry["slug"])
    return url if url.startswith(("http://", "https://")) else ""


def scope_items(entry):
    targets = entry.get("targets")
    if isinstance(targets, dict) and isinstance(targets.get("in_scope"), list):
        return targets["in_scope"]
    if isinstance(entry.get("scopes"), list):
        return entry["scopes"]
    return []


def matching_scopes(entry, keywords):
    """Return [(identifier, asset_type)] where any keyword hits; [] = no match."""
    found = []
    for item in scope_items(entry):
        identifier, asset_type = "", ""
        if isinstance(item, dict):
            identifier = str(
                item.get("asset_identifier") or item.get("target")
                or item.get("endpoint") or item.get("uri") or item.get("name") or ""
            )
            asset_type = str(item.get("asset_type") or item.get("type") or "")
        elif isinstance(item, str):
            identifier = item
        if not identifier:
            continue
        haystack = (identifier + " " + asset_type).lower()
        if not keywords or any(k in haystack for k in keywords):
            found.append((identifier, asset_type))
    return found


def parse_keywords(raw):
    keywords = [k.strip().lower() for k in (raw or "").split(",") if k.strip()]
    return [] if "*" in keywords else keywords  # empty list = match everything


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------
def search(keywords, kind, platforms, display, scope_cap=None):
    feeds = load_feeds()
    per_platform = {}

    for platform in platforms:
        if platform not in feeds:
            continue
        rows = []
        for entry in feeds[platform]["data"]:
            if not isinstance(entry, dict) or entry.get("disabled") is True:
                continue
            paid = is_paid(entry)
            if kind == "vdp" and paid:
                continue
            if kind == "paid" and not paid:
                continue
            scopes = matching_scopes(entry, keywords)
            if not scopes:
                continue
            shown = scopes if scope_cap is None else scopes[:scope_cap]
            rows.append({
                "platform": platform,
                "name": " ".join(str(entry.get("name") or entry.get("title") or "Unknown program").split()),
                "url": program_url(entry, platform),
                "paid": paid,
                "scope_total": len(scopes),
                "scopes": [{"identifier": i, "type": t} for i, t in shown],
            })
        rows.sort(key=lambda r: r["name"].lower())
        per_platform[platform] = rows

    if display == "grouped":
        results = [r for p in platforms if p in per_platform for r in per_platform[p]]
    else:  # interleave: one from each platform in turn, so no platform dominates
        results, queues = [], [list(per_platform[p]) for p in platforms if p in per_platform]
        while any(queues):
            for q in queues:
                if q:
                    results.append(q.pop(0))

    counts = {p: len(rows) for p, rows in per_platform.items()}
    return results, counts, feeds


def request_filters():
    keywords = parse_keywords(request.args.get("keyword", ""))
    kind = request.args.get("kind", "vdp")
    kind = kind if kind in ("vdp", "paid", "all") else "vdp"
    display = "grouped" if request.args.get("display") == "grouped" else "interleave"
    chosen = [p for p in request.args.get("platforms", "").split(",") if p in DATA_SOURCES]
    return keywords, kind, display, chosen or list(DATA_SOURCES)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.get("/")
def index():
    return render_template("index.html", platforms=list(DATA_SOURCES))


@app.get("/api/search")
def api_search():
    keywords, kind, display, platforms = request_filters()
    results, counts, feeds = search(keywords, kind, platforms, display, SCOPE_PREVIEW)
    newest = max((f["fetched"] for f in feeds.values()), default=0)
    return jsonify({
        "total": len(results),
        "counts": counts,
        "errors": {p: f["error"] for p, f in feeds.items() if f["error"]},
        "updated": datetime.fromtimestamp(newest, timezone.utc).isoformat() if newest else None,
        "results": results,
    })


@app.get("/api/export")
def api_export():
    keywords, kind, display, platforms = request_filters()
    results, _, _ = search(keywords, kind, platforms, display, scope_cap=None)
    fmt = request.args.get("format", "json")

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["platform", "program", "reward_type", "program_url", "matching_scopes"])
        for r in results:
            writer.writerow([
                r["platform"], r["name"], "cash" if r["paid"] else "vdp", r["url"],
                " | ".join(f'{s["identifier"]} [{s["type"]}]' if s["type"] else s["identifier"]
                           for s in r["scopes"]),
            ])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=bb_targets_matched.csv"})

    return Response(json.dumps(results, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=bb_targets_matched.json"})


if __name__ == "__main__":
    # Bound to localhost only. Do not expose this with debug=True.
    app.run(host="127.0.0.1", port=5000, debug=False)
