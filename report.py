"""
report.py — data payload + single-image rendering for the FPL mini-league report.

Two responsibilities:

1. build_payload(...)  -> a single JSON-serialisable dict describing each
   manager's season and the mini-league picture. This is the *contract* the
   HTML template (report_template.render_report_html) consumes.

2. render_html_to_png(...) -> render a (tall) HTML file to ONE high-DPI PNG
   using the same headless Chrome the Facebook sender relies on.

Names are always real manager names (player_name), never FPL team names.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List, Optional


# --------------------------------------------------------------------------- #
# Data payload
# --------------------------------------------------------------------------- #
def _net(gw_row: dict) -> int:
    """NET points for a history row = gross points - transfer cost."""
    return gw_row.get("points", 0) - gw_row.get("event_transfers_cost", 0)


def _season_series(manager: dict, up_to_gw: int) -> dict:
    """Per-gameweek season series for one manager, up to and including up_to_gw."""
    history = manager.get("history", {}).get("current", [])
    rows = [r for r in history if r["event"] <= up_to_gw]

    gws = [r["event"] for r in rows]
    net = [_net(r) for r in rows]
    gross = [r.get("points", 0) for r in rows]
    overall_rank = [r.get("overall_rank") for r in rows]
    bench = [r.get("points_on_bench", 0) for r in rows]
    value = [round(r.get("value", 0) / 10, 1) for r in rows]

    cumulative: List[int] = []
    running = 0
    for n in net:
        running += n
        cumulative.append(running)

    best = worst = None
    if net:
        bi = max(range(len(net)), key=lambda i: net[i])
        wi = min(range(len(net)), key=lambda i: net[i])
        best = {"gw": gws[bi], "points": net[bi]}
        worst = {"gw": gws[wi], "points": net[wi]}

    chips = [
        {"gw": c["event"], "chip": c["name"]}
        for c in manager.get("history", {}).get("chips", [])
        if c.get("event", 10 ** 9) <= up_to_gw
    ]

    return {
        "gws": gws,
        "net_points": net,
        "gross_points": gross,
        "cumulative": cumulative,
        "overall_rank": overall_rank,
        "bench_points": bench,
        "team_value": value,
        "avg": round(sum(net) / len(net), 1) if net else 0,
        "best_gw": best,
        "worst_gw": worst,
        "bench_points_total": sum(bench),
        "hits_total": sum(r.get("event_transfers_cost", 0) for r in rows),
        "transfers_total": sum(r.get("event_transfers", 0) for r in rows),
        "chips_used": chips,
    }


def _form(series: dict) -> dict:
    """Hot/cold form: last-5 average vs season average."""
    net = series["net_points"]
    if not net:
        return {"last5_avg": 0, "season_avg": 0, "diff": 0, "state": "steady"}
    last5 = net[-5:]
    last5_avg = round(sum(last5) / len(last5), 1)
    season_avg = series["avg"]
    diff = round(last5_avg - season_avg, 1)
    state = "hot" if diff >= 5 else "cold" if diff <= -5 else "steady"
    return {"last5_avg": last5_avg, "season_avg": season_avg, "diff": diff, "state": state}


def _league_rank_trajectory(managers: List[dict], up_to_gw: int) -> Dict[int, List[Optional[int]]]:
    """For each manager entry_id, their mini-league position after each gameweek."""
    # cumulative net totals per manager per gw
    per_gw_totals: Dict[int, Dict[int, int]] = {}  # gw -> {entry_id: cumulative}
    running: Dict[int, int] = {m["entry"]: 0 for m in managers}
    for gw in range(1, up_to_gw + 1):
        for m in managers:
            row = next((r for r in m.get("history", {}).get("current", []) if r["event"] == gw), None)
            if row is not None:
                running[m["entry"]] += _net(row)
        per_gw_totals[gw] = dict(running)

    trajectory: Dict[int, List[Optional[int]]] = {m["entry"]: [] for m in managers}
    for gw in range(1, up_to_gw + 1):
        totals = per_gw_totals[gw]
        order = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        rank_of = {eid: idx + 1 for idx, (eid, _) in enumerate(order)}
        for m in managers:
            trajectory[m["entry"]].append(rank_of.get(m["entry"]))
    return trajectory


def _weekly_wins(managers: List[dict], up_to_gw: int, name_of) -> List[dict]:
    """Fractional weekly wins per manager (ties split the win)."""
    wins: Dict[int, float] = {m["entry"]: 0.0 for m in managers}
    weeks: Dict[int, List[int]] = {m["entry"]: [] for m in managers}
    for gw in range(1, up_to_gw + 1):
        scores = []
        for m in managers:
            row = next((r for r in m.get("history", {}).get("current", []) if r["event"] == gw), None)
            if row is not None:
                scores.append((m["entry"], _net(row)))
        if not scores:
            continue
        top = max(s for _, s in scores)
        winners = [eid for eid, s in scores if s == top]
        share = 1.0 / len(winners)
        for eid in winners:
            wins[eid] += share
            weeks[eid].append(gw)
    out = [
        {"name": name_of[eid], "wins": round(w, 2), "weeks": weeks[eid]}
        for eid, w in wins.items()
    ]
    out.sort(key=lambda x: x["wins"], reverse=True)
    return out


def _remap_fun_facts(fun_facts: dict, team_to_real: Dict[str, str]) -> dict:
    """fun_facts use team names internally; translate to real names."""
    remapped = {}
    for key, fact in (fun_facts or {}).items():
        if isinstance(fact, dict) and "manager" in fact:
            fact = dict(fact)
            fact["manager"] = team_to_real.get(fact["manager"], fact["manager"])
        remapped[key] = fact
    return remapped


def build_payload(
    mini_league_data: dict,
    gameweek: int,
    league_name: str,
    detail_by_entry: Dict[int, dict],
    current_scores: List[dict],
    fun_facts: dict,
    ai_insights: Optional[str],
    gw_average: float,
    is_final: bool,
    season_label: str = "",
) -> dict:
    """Assemble the full report payload. Uses real manager names throughout."""
    managers = mini_league_data["standings"]["results"]
    name_of = {m["entry"]: m.get("player_name") or m["entry_name"] for m in managers}
    team_to_real = {m["entry_name"]: name_of[m["entry"]] for m in managers}
    team_name_of = {m["entry"]: m.get("team_name", m["entry_name"]) for m in managers}

    trajectory = _league_rank_trajectory(managers, gameweek)

    # NET gw points per manager (from current_scores, which is keyed by team name)
    gw_net_by_team = {cs["manager"]: cs for cs in current_scores}

    manager_blocks: List[dict] = []
    for m in managers:
        eid = m["entry"]
        detail = detail_by_entry.get(eid, {})
        series = _season_series(m, gameweek)
        cs = gw_net_by_team.get(m["entry_name"], {})

        manager_blocks.append({
            "entry_id": eid,
            "name": name_of[eid],
            "team_name": team_name_of[eid],
            "rank": m.get("rank"),
            "prev_rank": m.get("last_rank"),
            "rank_movement": (m.get("last_rank", 0) or 0) - (m.get("rank", 0) or 0),
            "total_points": m.get("total", 0),
            "gw_points": cs.get("net_points", detail.get("Points", 0)),
            "gw_gross": cs.get("gross_points", 0),
            "gw_hit": cs.get("transfer_cost", 0),
            "overall_rank": m.get("manager_details", {}).get("summary_overall_rank"),
            "captain": detail.get("Captain"),
            "captain_points": detail.get("Captain Points"),
            "vice_captain": detail.get("Vice-Captain"),
            "vice_captain_points": detail.get("Vice-Captain Points"),
            "chip": _pretty_chip(detail.get("Chip Used")),
            "formation": detail.get("Formation"),
            "bench_points": detail.get("Points on Bench"),
            "team_value": detail.get("Team Value"),
            "bank": detail.get("Bank Money"),
            "transfers": detail.get("Transfers"),
            "transfer_cost": detail.get("Transfer Cost"),
            "top_scorer": detail.get("Top Scorer"),
            "top_scorer_points": detail.get("Top Scorer Points"),
            "top_scorer_played": detail.get("Top Scorer Played"),
            "underperformer": detail.get("Underperformer"),
            "underperformer_points": detail.get("Underperformer Points"),
            "defensive_points": detail.get("Defensive Points"),
            "attacking_points": detail.get("Attacking Points"),
            "season": {**series, "league_rank": trajectory.get(eid, [])},
            "form": _form(series),
        })

    manager_blocks.sort(key=lambda x: (x["rank"] is None, x["rank"]))

    # league-wide
    gw_standings = sorted(
        (
            {"name": name_of[m["entry"]],
             "gw_points": gw_net_by_team.get(m["entry_name"], {}).get("net_points", 0)}
            for m in managers
        ),
        key=lambda x: x["gw_points"], reverse=True,
    )

    # league average net points per gameweek
    league_avg_series = []
    for gw in range(1, gameweek + 1):
        vals = []
        for m in managers:
            row = next((r for r in m.get("history", {}).get("current", []) if r["event"] == gw), None)
            if row is not None:
                vals.append(_net(row))
        league_avg_series.append(round(sum(vals) / len(vals), 1) if vals else 0)

    movements = [
        {"name": b["name"], "change": b["rank_movement"]}
        for b in manager_blocks if b["rank_movement"]
    ]
    biggest_riser = max(movements, key=lambda x: x["change"], default=None)
    biggest_faller = min(movements, key=lambda x: x["change"], default=None)

    # ----------------------------------------------------------------------- #
    # Captaincy trends: most-captained players across the league this GW
    # ----------------------------------------------------------------------- #
    cap_counts: Dict[int, int] = {}
    cap_pts: Dict[int, int] = {}
    cap_names_map: Dict[int, str] = {}
    for m in managers:
        gw_picks = m.get("gameweek_data", {}).get(str(gameweek), {}).get("picks", [])
        cap = next((p for p in gw_picks if p.get("is_captain")), None)
        if cap:
            pid = cap["element"]
            cap_counts[pid] = cap_counts.get(pid, 0) + 1
            # Player name comes from detail_by_entry indirectly; look at pick
            # The caller has built player_id_to_name inside main(); we don't have it
            # here, so we use whatever name is stored in each manager's Captain field.
    # Enrich cap_names from detail_by_entry (Captain field stores the name)
    for m in managers:
        eid = m["entry"]
        cap_name = detail_by_entry.get(eid, {}).get("Captain", "")
        cap_pts_val = detail_by_entry.get(eid, {}).get("Captain Points", 0)
        gw_picks = m.get("gameweek_data", {}).get(str(gameweek), {}).get("picks", [])
        cap = next((p for p in gw_picks if p.get("is_captain")), None)
        if cap and cap_name:
            pid = cap["element"]
            cap_names_map[pid] = cap_name
            cap_pts[pid] = cap_pts_val

    captaincy_trends = sorted(
        [
            {"player": cap_names_map.get(pid, f"Player #{pid}"),
             "count": cnt, "pct": round(cnt / len(managers) * 100),
             "gw_pts": cap_pts.get(pid, 0)}
            for pid, cnt in cap_counts.items()
        ],
        key=lambda x: x["count"], reverse=True
    )

    # ----------------------------------------------------------------------- #
    # Power rankings: form-weighted (60% last-3 avg + 40% season avg)
    # ----------------------------------------------------------------------- #
    power_rows = []
    for b in manager_blocks:
        net_series = b["season"].get("net_points", [])
        if not net_series:
            continue
        s_avg = b["season"].get("avg", 0)
        recent = net_series[-3:] if len(net_series) >= 3 else net_series
        r_avg = round(sum(recent) / len(recent), 1) if recent else 0
        score = round(0.6 * r_avg + 0.4 * s_avg, 1)
        power_rows.append({
            "name": b["name"],
            "score": score,
            "league_rank": b["rank"] or 99,
            "recent_avg": r_avg,
            "season_avg": s_avg,
        })
    power_rows.sort(key=lambda x: x["score"], reverse=True)
    for pr, row in enumerate(power_rows, 1):
        row["power_rank"] = pr
        row["delta"] = (row["league_rank"] or 99) - pr  # positive = ranked higher than expected

    # ----------------------------------------------------------------------- #
    # Season bench leaderboard
    # ----------------------------------------------------------------------- #
    bench_leaderboard = sorted(
        [
            {"name": b["name"],
             "season_bench": b["season"].get("bench_points_total", 0),
             "gw_bench": b.get("bench_points", 0) or 0}
            for b in manager_blocks
        ],
        key=lambda x: x["season_bench"], reverse=True
    )

    # ----------------------------------------------------------------------- #
    # Rivalries: closest overall gaps between adjacent managers
    # ----------------------------------------------------------------------- #
    sorted_by_total = sorted(manager_blocks, key=lambda x: x["total_points"], reverse=True)
    rivalries = []
    for i in range(len(sorted_by_total) - 1):
        a, b_item = sorted_by_total[i], sorted_by_total[i + 1]
        gap = a["total_points"] - b_item["total_points"]
        rivalries.append({"leader": a["name"], "chaser": b_item["name"], "gap": gap})

    return {
        "meta": {
            "gameweek": gameweek,
            "is_final": is_final,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "league_name": league_name,
            "season_label": season_label,
            "num_managers": len(managers),
            "gw_average": round(gw_average, 1),
        },
        "managers": manager_blocks,
        "league": {
            "gw_standings": gw_standings,
            "weekly_wins": _weekly_wins(managers, gameweek, name_of),
            "avg_series": league_avg_series,
            "biggest_riser": biggest_riser if biggest_riser and biggest_riser["change"] > 0 else None,
            "biggest_faller": biggest_faller if biggest_faller and biggest_faller["change"] < 0 else None,
            "captaincy_trends": captaincy_trends,
            "power_rankings": power_rows,
            "bench_leaderboard": bench_leaderboard,
            "rivalries": rivalries,
        },
        "highlights": _remap_fun_facts(fun_facts, team_to_real),
        "narrative": (ai_insights or "").strip(),
    }


_CHIP_LABELS = {
    "wildcard": "Wildcard",
    "freehit": "Free Hit",
    "bboost": "Bench Boost",
    "3xc": "Triple Captain",
    "manager": "Assistant Manager",
}


def _pretty_chip(chip) -> Optional[str]:
    if not chip or chip in ("No Chip Used", None):
        return None
    return _CHIP_LABELS.get(chip, chip)


def write_payload(payload: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# HTML -> single tall high-DPI PNG
# --------------------------------------------------------------------------- #
def _find_browser() -> Optional[str]:
    """Locate a Chrome/Chromium binary across platforms."""
    import shutil
    for cand in (
        os.environ.get("CHROME_BIN"),
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/snap/chromium/current/usr/lib/chromium-browser/chrome",
    ):
        if cand and os.path.exists(cand):
            return cand
    return None


def render_html_to_png(
    html_path: str,
    png_path: str,
    width: int = 1200,
    scale: float = 2.0,
) -> str:
    """
    Render an HTML file to a single full-height PNG.

    width  : CSS pixel width of the layout (the report is designed at this width).
    scale  : device pixel ratio; 2.0 => crisp / zoomable without pixelation.

    Primary path uses Selenium + Chrome DevTools Protocol (full-page capture,
    works on the x86 deployment machine). Falls back to a headless-Chrome CLI
    render + auto-trim for locked-down environments (e.g. snap-confined
    Chromium on ARM) where the WebDriver can't launch the browser.
    """
    try:
        return _render_via_selenium(html_path, png_path, width, scale)
    except Exception as e:  # pragma: no cover - environment dependent
        return _render_via_cli(html_path, png_path, width, scale, reason=str(e))


def _render_via_selenium(html_path, png_path, width, scale) -> str:
    import base64
    import shutil
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--hide-scrollbars")
    options.add_argument(f"--window-size={width},2000")

    browser = _find_browser()
    if browser:
        options.binary_location = browser

    driver_path = os.environ.get("CHROMEDRIVER") or shutil.which("chromedriver")
    if driver_path and os.path.exists(driver_path):
        driver = webdriver.Chrome(service=Service(executable_path=driver_path), options=options)
    else:
        driver = webdriver.Chrome(options=options)

    try:
        driver.get("file://" + os.path.abspath(html_path))
        driver.implicitly_wait(2)
        metrics = driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
        css = metrics.get("cssContentSize") or metrics["contentSize"]
        full_w = width
        full_h = int(css["height"]) + 1
        result = driver.execute_cdp_cmd("Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": full_w, "height": full_h, "scale": scale},
        })
        with open(png_path, "wb") as f:
            f.write(base64.b64decode(result["data"]))
    finally:
        driver.quit()
    return png_path


def _render_via_cli(html_path, png_path, width, scale, reason="") -> str:
    """Fallback: headless-Chrome CLI render into a tall canvas, then auto-trim."""
    import subprocess

    browser = _find_browser()
    if not browser:
        raise RuntimeError(f"No Chrome/Chromium binary found (selenium failed: {reason})")

    tall = 30000  # generous canvas; trimmed afterwards
    cmd = [
        browser, "--headless=new", "--no-sandbox", "--disable-gpu",
        "--hide-scrollbars", f"--force-device-scale-factor={scale}",
        f"--window-size={width},{tall}", f"--screenshot={os.path.abspath(png_path)}",
        "file://" + os.path.abspath(html_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    _autotrim_bottom(png_path)
    return png_path


def _autotrim_bottom(png_path: str) -> None:
    """Trim uniform background rows from the bottom of the rendered image."""
    try:
        from PIL import Image, ImageChops
        Image.MAX_IMAGE_PIXELS = None  # the tall canvas is intentionally huge
        im = Image.open(png_path).convert("RGB")
        # Background colour sampled from the very bottom-left pixel.
        bg = im.getpixel((0, im.height - 1))
        bg_img = Image.new("RGB", im.size, bg)
        diff = ImageChops.difference(im, bg_img)
        bbox = diff.getbbox()
        if bbox:
            # keep full width, trim height to content (+ small padding)
            top = 0
            bottom = min(im.height, bbox[3] + 24)
            im.crop((0, top, im.width, bottom)).save(png_path)
    except Exception:
        pass  # leave the untrimmed image rather than fail
