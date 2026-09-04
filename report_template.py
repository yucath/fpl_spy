"""
report_template.py — newspaper-style HTML report for the FPL mini-league.

Entry point (stable):
    render_report_html(payload: dict) -> str

No external assets, no JS, no CDN. Pure inline HTML/CSS.
Designed at 1200px fixed width.
"""

from __future__ import annotations

import html
import math
from datetime import datetime
from typing import List, Optional, Sequence

# --------------------------------------------------------------------------- #
#  Design tokens — newspaper palette
# --------------------------------------------------------------------------- #
BG        = "#faf8f0"   # aged newsprint
PAPER     = "#f5f2e8"   # slightly darker panel bg
INK       = "#1a1a1a"   # primary text
INK_2     = "#3a3a3a"   # secondary text
MUTED     = "#6b6b6b"   # tertiary text
RULE      = "#c8b89a"   # divider lines
HEADLINE  = "#8b0000"   # dark red headline
ACCENT    = "#c8960c"   # gold accent (pullquote rules, etc.)
UP        = "#1a5c1a"   # green for rises
DOWN      = "#8b0000"   # red for falls / negative

# Series colours for multi-line chart
SERIES_COLORS = [
    "#8b0000", "#1a5c1a", "#1a3a8b", "#7b4f00", "#5a0072",
    "#005f5f", "#7a1a00", "#004a24", "#003d7a", "#6b3d00",
    "#4a006b", "#003838", "#5c1a00", "#1a4a00", "#00286b",
]


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def fnum(x, dp: int = 0) -> str:
    try:
        if x is None:
            return "—"
        if dp == 0:
            return f"{int(round(float(x))):,}"
        return f"{float(x):,.{dp}f}"
    except (ValueError, TypeError):
        return esc(x)


def compact_rank(x) -> str:
    try:
        n = int(x)
    except (ValueError, TypeError):
        return "—"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n/1000:.0f}k"
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return f"{n:,}"


def _pts(values) -> List[float]:
    return [float(p) for p in values]


def _poly(xs, ys) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in zip(xs, ys))


# --------------------------------------------------------------------------- #
#  SVG charts
# --------------------------------------------------------------------------- #
def sparkline(values, w: int = 200, h: int = 44, color: str = HEADLINE) -> str:
    vals = _pts(values)
    if not vals:
        return f'<svg width="{w}" height="{h}"></svg>'
    if len(vals) == 1:
        cy = h / 2
        return (
            f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<line x1="4" y1="{cy:.1f}" x2="{w-4}" y2="{cy:.1f}" '
            f'stroke="{RULE}" stroke-width="1.5" stroke-dasharray="3 4"/>'
            f'<circle cx="{w/2:.1f}" cy="{cy:.1f}" r="3.5" fill="{color}"/>'
            f'</svg>'
        )
    pad = 5
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    n = len(vals)
    xs = [pad + (w - 2 * pad) * i / (n - 1) for i in range(n)]
    ys = [(h - pad) - (h - 2 * pad) * (v - lo) / rng for v in vals]
    line = _poly(xs, ys)
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f'<polyline points="{line}" fill="none" stroke="{color}" '
        f'stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{xs[-1]:.2f}" cy="{ys[-1]:.2f}" r="3" fill="{color}"/>'
        f'</svg>'
    )


def race_chart(managers: List[dict], w: int = 1100, h: int = 360, mode: str = "rank") -> str:
    gws = None
    for m in managers:
        g = (m.get("season") or {}).get("gws") or []
        if len(g) > (len(gws) if gws else 0):
            gws = g
    if not gws or len(gws) < 2:
        return ""

    pad_l, pad_r, pad_t, pad_b = 36, 140, 16, 28
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    gmin, gmax = min(gws), max(gws)
    grng = (gmax - gmin) or 1

    def sx(gw):
        return pad_l + plot_w * (gw - gmin) / grng

    if mode == "rank":
        n_mgr = len(managers)
        vmin, vmax = 1, max(2, n_mgr)

        def sy(v):
            return pad_t + plot_h * (v - vmin) / ((vmax - vmin) or 1)
        y_ticks = sorted({1, max(1, n_mgr // 2), n_mgr})
    else:
        allc = [c for m in managers for c in ((m.get("season") or {}).get("cumulative") or [])]
        vmin, vmax = (min(allc), max(allc)) if allc else (0, 1)

        def sy(v):
            return pad_t + plot_h - plot_h * (v - vmin) / ((vmax - vmin) or 1)
        step = max(1, round((vmax - vmin) / 4))
        y_ticks = list(range(int(vmin), int(vmax) + 1, step))

    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    # grid lines
    for t in y_ticks:
        yy = sy(t)
        out.append(
            f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{pad_l+plot_w}" y2="{yy:.1f}" '
            f'stroke="{RULE}" stroke-width="0.7" stroke-dasharray="3 4"/>'
        )
        lbl = f"#{t}" if mode == "rank" else fnum(t)
        out.append(
            f'<text x="{pad_l-8}" y="{yy+4:.1f}" text-anchor="end" '
            f'fill="{MUTED}" font-size="11" font-family="Georgia,serif">{lbl}</text>'
        )
    xt_count = min(len(gws), 8)
    xstep = max(1, (len(gws) - 1) // max(1, xt_count - 1))
    for i in range(0, len(gws), xstep):
        gw = gws[i]
        xx = sx(gw)
        out.append(
            f'<text x="{xx:.1f}" y="{h-8}" text-anchor="middle" '
            f'fill="{MUTED}" font-size="11" font-family="Georgia,serif">GW{gw}</text>'
        )

    label_anchors = []
    for idx, m in enumerate(managers):
        s = m.get("season") or {}
        mg = s.get("gws") or []
        series = (s.get("league_rank") if mode == "rank" else s.get("cumulative")) or []
        pts = list(zip(mg, series))
        if len(pts) < 2:
            continue
        color = SERIES_COLORS[idx % len(SERIES_COLORS)]
        is_leader = m.get("rank") == 1
        xs2 = [sx(g) for g, _ in pts]
        ys2 = [sy(v) for _, v in pts]
        wln = 2.8 if is_leader else 1.4
        out.append(
            f'<polyline points="{_poly(xs2, ys2)}" fill="none" '
            f'stroke="{color}" stroke-width="{wln}" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        out.append(f'<circle cx="{xs2[-1]:.1f}" cy="{ys2[-1]:.1f}" r="{3 if is_leader else 2}" fill="{color}"/>')
        label_anchors.append((ys2[-1], color, m.get("name", ""), is_leader))

    label_anchors.sort(key=lambda t: t[0])
    min_gap = 16
    placed = []
    for y0, *_ in label_anchors:
        y = y0
        if placed and y < placed[-1] + min_gap:
            y = placed[-1] + min_gap
        placed.append(y)
    lx = pad_l + plot_w + 8
    for (orig, color, name, is_leader), y in zip(label_anchors, placed):
        short = name.split()[0] if name else ""
        out.append(
            f'<line x1="{pad_l+plot_w}" y1="{orig:.1f}" x2="{lx-2}" y2="{y:.1f}" '
            f'stroke="{color}" stroke-width="0.8" stroke-opacity="0.6"/>'
        )
        out.append(f'<circle cx="{lx+2}" cy="{y:.1f}" r="2.5" fill="{color}"/>')
        fw = "700" if is_leader else "500"
        out.append(
            f'<text x="{lx+9}" y="{y+4:.1f}" fill="{INK}" '
            f'font-size="11" font-weight="{fw}" font-family="Georgia,serif">'
            f'{esc(short)}</text>'
        )
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------- #
#  Section builders
# --------------------------------------------------------------------------- #
def render_masthead(meta: dict) -> str:
    league = esc(meta.get("league_name", "FPL Mini-League"))
    gw = esc(meta.get("gameweek", ""))
    generated = meta.get("generated_at", "")
    try:
        dt = datetime.strptime(generated, "%Y-%m-%d %H:%M")
        date_str = dt.strftime("%A, %d %B %Y").upper()
    except Exception:
        date_str = generated.upper()
    is_final = bool(meta.get("is_final"))
    status = "FINAL" if is_final else "LIVE UPDATE"
    managers = meta.get("num_managers", "")
    gw_avg = fnum(meta.get("gw_average"), 1)
    season = esc(meta.get("season_label") or "2025/26")
    return f"""
<header class="masthead">
  <div class="masthead-rule top-rule"></div>
  <div class="masthead-inner">
    <div class="masthead-meta-left">
      <div class="mast-kicker">FANTASY PREMIER LEAGUE · MINI-LEAGUE REPORT</div>
      <div class="mast-season">SEASON {season}</div>
    </div>
    <div class="masthead-title">
      <div class="mast-name">{league}</div>
      <div class="mast-sub">THE GAZETTE</div>
    </div>
    <div class="masthead-meta-right">
      <div class="mast-date">{date_str}</div>
      <div class="mast-gw">GAMEWEEK {gw} &nbsp;·&nbsp; {status}</div>
      <div class="mast-stats">{managers} managers · avg {gw_avg} pts</div>
    </div>
  </div>
  <div class="masthead-rule"></div>
  <div class="masthead-rule thin-rule"></div>
</header>"""


def render_banner(managers: List[dict], narrative: str) -> str:
    """Big headline from narrative first line + winner callout."""
    if not managers:
        return ""
    leader = managers[0]
    first_line = ""
    if narrative:
        first_line = narrative.strip().split("\n")[0].strip()
        # strip leading 'GW#: ' prefix
        if first_line and ":" in first_line[:8]:
            first_line = first_line.split(":", 1)[1].strip()
    if not first_line:
        first_line = f"{esc(leader.get('name',''))} leads the pack"
    return f"""
<div class="banner">
  <div class="banner-rule"></div>
  <h1 class="banner-headline">{esc(first_line)}</h1>
  <div class="banner-deck">
    GW{esc(leader.get('season',{}).get('gws',['?'])[-1] if leader.get('season',{}).get('gws') else '?')}
    LEADER: <strong>{esc(leader.get('name',''))}</strong>
    · {fnum(leader.get('total_points'))} pts total
    · {fnum(leader.get('gw_points'))} this week
  </div>
  <div class="banner-rule"></div>
</div>"""


def render_three_col(managers: List[dict], league: dict, narrative: str,
                     player_photos: dict = None) -> str:
    """Three-column layout: league table | captain picks | match report."""
    return f"""
<div class="three-col">
  <div class="col-left">
    {_league_table(managers)}
  </div>
  <div class="col-mid">
    {_captain_column(managers, player_photos or {})}
  </div>
  <div class="col-right">
    {_match_report(narrative)}
  </div>
</div>"""


def _league_table(managers: List[dict]) -> str:
    rows = []
    for m in managers:
        rank = m.get("rank", 0)
        leader = rank == 1
        mv = (m.get("last_rank") or m.get("prev_rank") or rank) - rank
        if mv > 0:
            mv_html = f'<span class="mv-up">▲</span>'
        elif mv < 0:
            mv_html = f'<span class="mv-dn">▼</span>'
        else:
            mv_html = '<span class="mv-flat">—</span>'
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "")
        chip = m.get("chip")
        chip_tag = f'<span class="lt-chip">{esc(chip[:2].upper())}</span>' if chip else ""
        hit = m.get("gw_hit", 0)
        hit_tag = f'<span class="lt-hit">-{hit}</span>' if hit else ""
        rows.append(f"""
    <tr class="{'lt-leader' if leader else ''}">
      <td class="lt-rk">{medal or rank}</td>
      <td class="lt-mv">{mv_html}</td>
      <td class="lt-nm">{esc(m.get('name',''))} {chip_tag}{hit_tag}</td>
      <td class="lt-tot">{fnum(m.get('total_points'))}</td>
      <td class="lt-gw">{fnum(m.get('gw_points'))}</td>
    </tr>""")
    return f"""
<div class="col-head">LEAGUE TABLE</div>
<table class="lt">
  <thead><tr>
    <th>#</th><th></th><th>Manager</th><th>Total</th><th>GW</th>
  </tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>"""


def _captain_column(managers: List[dict], player_photos: dict) -> str:
    rows = []
    for m in managers[:8]:
        cap = m.get("captain") or "—"
        cap_pts = m.get("captain_points")
        pts_str = f"{cap_pts}" if cap_pts is not None else "?"
        chip = m.get("chip")
        chip_tag = f' <span class="lt-chip">{esc(chip[:2].upper() if chip else "")}</span>' if chip else ""
        rows.append(f"""
    <div class="cap-row">
      <div class="cap-info">
        <div class="cap-mgr">{esc(m.get('name',''))}{chip_tag}</div>
        <div class="cap-player">© {esc(cap)}</div>
      </div>
      <div class="cap-pts {'cap-good' if (cap_pts or 0) >= 10 else 'cap-meh'}">{pts_str}pts</div>
    </div>""")
    return f"""
<div class="col-head">CAPTAIN PICKS</div>
<div class="cap-list">{''.join(rows)}</div>"""


def _match_report(narrative: str) -> str:
    if not narrative or not narrative.strip():
        return '<div class="col-head">MATCH REPORT</div><p class="no-narrative">No report available.</p>'
    paras = [p.strip() for p in narrative.split("\n") if p.strip()]
    # skip first line — used as banner headline
    body_paras = paras[1:] if len(paras) > 1 else paras
    parts = []
    for i, p in enumerate(body_paras):
        if i == 0:
            # drop-cap on first real paragraph
            first_char = esc(p[0]) if p else ""
            rest = esc(p[1:]) if len(p) > 1 else ""
            parts.append(f'<p class="report-para dropcap"><span class="drop">{first_char}</span>{rest}</p>')
        else:
            parts.append(f'<p class="report-para">{esc(p)}</p>')
    return f"""
<div class="col-head">MATCH REPORT</div>
{''.join(parts)}"""


def render_stats_strip(managers: List[dict], league: dict) -> str:
    """Four stat boxes: GW winner | Biggest riser | Bench pain | Captain of the week."""
    gw_top = sorted(managers, key=lambda m: m.get("gw_points", 0) or 0, reverse=True)
    gw_winner = gw_top[0] if gw_top else {}
    riser = league.get("biggest_riser")
    bench_lb = (league.get("bench_leaderboard") or [])
    bench_top = bench_lb[0] if bench_lb else {}
    # captain of the week: manager with highest captain points
    cap_best = max(managers, key=lambda m: m.get("captain_points", 0) or 0, default={})

    def stat_box(emoji, kicker, name, stat, sub):
        return f"""
    <div class="stat-box">
      <div class="stat-emoji">{emoji}</div>
      <div class="stat-kicker">{esc(kicker)}</div>
      <div class="stat-name">{esc(name)}</div>
      <div class="stat-value">{esc(stat)}</div>
      <div class="stat-sub">{esc(sub)}</div>
    </div>"""

    gw_pts = fnum(gw_winner.get("gw_points"))
    riser_html = stat_box(
        "📈", "BIGGEST RISER",
        (riser or {}).get("name", "—"),
        f'+{(riser or {}).get("change", 0)} place(s)',
        "moved up this week"
    ) if riser else stat_box("📈", "BIGGEST RISER", "—", "—", "no movement")

    return f"""
<div class="stats-strip">
  {stat_box("⚡", "GW TOP SCORER", gw_winner.get('name',''), f'{gw_pts} pts', f'© {esc(gw_winner.get("captain",""))}')}
  {riser_html}
  {stat_box("🪑", "BENCH PAIN KING", bench_top.get('name','—'), f'{fnum(bench_top.get("season_bench","—"))} pts', 'season bench points')}
  {stat_box("🎯", "BEST CAPTAIN", cap_best.get('name','—'), f'{fnum(cap_best.get("captain_points","—"))} pts', f'© {esc(cap_best.get("captain",""))}')}
</div>"""


def render_race_section(managers: List[dict]) -> str:
    svg = race_chart(managers, mode="rank")
    if not svg:
        return ""
    return f"""
<section class="np-section">
  <div class="np-section-head">
    <span class="np-head-rule"></span>
    <span class="np-head-title">THE SEASON RACE</span>
    <span class="np-head-rule"></span>
  </div>
  <div class="chart-box">{svg}</div>
  <div class="chart-caption">Mini-league position after each gameweek · 1st place at top</div>
</section>"""


def render_manager_cards(managers: List[dict]) -> str:
    cards = []
    for idx, m in enumerate(managers):
        color = SERIES_COLORS[idx % len(SERIES_COLORS)]
        s = m.get("season") or {}
        spark = sparkline(s.get("net_points") or [], w=180, h=40, color=color)
        rank = m.get("rank", 0)
        gw_pts = m.get("gw_points", 0)
        cap = m.get("captain") or "—"
        cap_pts = m.get("captain_points", 0) or 0
        cap_cls = "cap-good" if cap_pts >= 10 else ("cap-meh" if cap_pts >= 6 else "cap-bad")
        chip = m.get("chip")
        chip_html = f'<span class="mc-chip">{esc(chip)}</span>' if chip else ""
        hit = m.get("gw_hit", 0)
        hit_html = f'<span class="mc-hit">-{hit}pt</span>' if hit else ""
        bench = m.get("bench_points") or 0
        or_rank = compact_rank(m.get("overall_rank"))
        cards.append(f"""
    <div class="mc" style="border-top-color:{color}">
      <div class="mc-top">
        <div class="mc-rank" style="color:{color}">{rank}</div>
        <div class="mc-id">
          <div class="mc-name">{esc(m.get('name',''))}</div>
          <div class="mc-team">{esc(m.get('team_name',''))}</div>
        </div>
        <div class="mc-gwv" style="color:{color}">{fnum(gw_pts)}</div>
      </div>
      <div class="mc-tags">{chip_html}{hit_html}</div>
      <div class="mc-spark">{spark}</div>
      <div class="mc-stats">
        <div class="mcs"><span class="mcs-k">Captain</span><span class="mcs-v {cap_cls}">© {esc(cap)} · {cap_pts}pts</span></div>
        <div class="mcs"><span class="mcs-k">Bench</span><span class="mcs-v">{fnum(bench)} pts</span></div>
        <div class="mcs"><span class="mcs-k">Total</span><span class="mcs-v">{fnum(m.get('total_points'))} pts</span></div>
        <div class="mcs"><span class="mcs-k">Global</span><span class="mcs-v">{or_rank}</span></div>
      </div>
    </div>""")
    return f"""
<section class="np-section">
  <div class="np-section-head">
    <span class="np-head-rule"></span>
    <span class="np-head-title">MANAGER DOSSIERS</span>
    <span class="np-head-rule"></span>
  </div>
  <div class="mc-grid">{''.join(cards)}</div>
</section>"""


def render_intel(league: dict) -> str:
    power = (league.get("power_rankings") or [])[:8]
    cap_trends = (league.get("captaincy_trends") or [])[:5]
    rivalries = (league.get("rivalries") or [])[:5]

    # Power rankings
    pw_rows = ""
    for p in power:
        delta = p.get("delta", 0)
        if delta >= 2:
            arrow = f'<span class="mv-up">▲{delta}</span>'
        elif delta <= -2:
            arrow = f'<span class="mv-dn">▼{abs(delta)}</span>'
        else:
            arrow = '<span class="mv-flat">—</span>'
        pw_rows += f"""
    <div class="intel-row">
      <span class="intel-rank">#{esc(p['power_rank'])}</span>
      <span class="intel-name">{esc(p['name'])}</span>
      <span class="intel-val">{esc(p['score'])}</span>
      {arrow}
    </div>"""

    # Captaincy trends
    cap_rows = ""
    max_cnt = cap_trends[0]["count"] if cap_trends else 1
    for t in cap_trends:
        pct = t["count"] / max_cnt * 100
        pts = f'{t["gw_pts"]}pts' if t.get("gw_pts") else "—"
        cap_rows += f"""
    <div class="ct-row">
      <div class="ct-name">{esc(t['player'])}</div>
      <div class="ct-bar-wrap"><div class="ct-bar" style="width:{pct:.0f}%"></div></div>
      <div class="ct-meta">{esc(t['pct'])}% · {esc(pts)}</div>
    </div>"""

    # Rivalries
    rv_rows = ""
    for r in rivalries:
        rv_rows += f"""
    <div class="rv-row">
      <span class="rv-a">{esc(r['leader'])}</span>
      <span class="rv-gap">+{esc(r['gap'])}pts ahead</span>
      <span class="rv-b">{esc(r['chaser'])}</span>
    </div>"""

    return f"""
<section class="np-section">
  <div class="np-section-head">
    <span class="np-head-rule"></span>
    <span class="np-head-title">LEAGUE INTEL</span>
    <span class="np-head-rule"></span>
  </div>
  <div class="intel-grid">
    <div class="intel-panel">
      <div class="intel-panel-head">POWER RANKINGS <span class="intel-note">form-weighted</span></div>
      {pw_rows}
    </div>
    <div class="intel-panel">
      <div class="intel-panel-head">CAPTAINCY TRENDS</div>
      {cap_rows}
    </div>
    <div class="intel-panel">
      <div class="intel-panel-head">CLOSEST RIVALRIES</div>
      {rv_rows}
    </div>
  </div>
</section>"""


def render_footer(meta: dict) -> str:
    season = meta.get("season_label") or ""
    seg = f" · {esc(season)}" if season else ""
    gw = meta.get("gameweek", "")
    league = esc(meta.get("league_name", ""))
    generated = meta.get("generated_at", "")
    return f"""
<footer class="np-footer">
  <div class="footer-rule"></div>
  <div class="footer-inner">
    <span>{league} · Gameweek {esc(str(gw))}{seg}</span>
    <span class="footer-right">Generated {esc(generated)} · FPL Spy automated report</span>
  </div>
</footer>"""


# --------------------------------------------------------------------------- #
#  Master entry point
# --------------------------------------------------------------------------- #
def render_report_html(payload: dict) -> str:
    meta = payload.get("meta") or {}
    managers = payload.get("managers") or []
    league = payload.get("league") or {}
    narrative = payload.get("narrative") or ""
    player_photos = payload.get("player_photos") or {}

    body = "".join([
        render_masthead(meta),
        render_banner(managers, narrative),
        render_three_col(managers, league, narrative, player_photos),
        render_stats_strip(managers, league),
        render_race_section(managers),
        render_manager_cards(managers),
        render_intel(league),
        render_footer(meta),
    ])

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>FPL Report – GW{meta.get('gameweek','')}</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">{body}</div>
</body></html>"""


# --------------------------------------------------------------------------- #
#  CSS — newspaper style
# --------------------------------------------------------------------------- #
CSS = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ background: {BG}; color: {INK}; }}
body {{
  width: 1200px; margin: 0 auto;
  font-family: Georgia, "Times New Roman", Times, serif;
  font-size: 15px; line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}}
.page {{ width: 1200px; padding: 28px 40px 40px; }}

/* ---- Masthead ---- */
.masthead {{ margin-bottom: 18px; }}
.masthead-rule {{ height: 4px; background: {INK}; margin: 4px 0; }}
.top-rule {{ height: 8px; }}
.thin-rule {{ height: 1px; margin-top: 2px; }}
.masthead-inner {{
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 0;
}}
.masthead-meta-left, .masthead-meta-right {{
  font-size: 10px; letter-spacing: 0.8px; color: {MUTED};
  text-transform: uppercase; line-height: 1.6; min-width: 200px;
}}
.masthead-meta-right {{ text-align: right; }}
.mast-kicker {{ font-weight: 700; color: {INK_2}; }}
.masthead-title {{ text-align: center; flex: 1; }}
.mast-name {{
  font-size: 42px; font-weight: 900; letter-spacing: -1px; line-height: 1;
  color: {INK};
}}
.mast-sub {{
  font-size: 11px; letter-spacing: 5px; color: {MUTED}; margin-top: 3px;
  text-transform: uppercase;
}}
.mast-gw {{ font-weight: 700; color: {HEADLINE}; }}
.mast-stats {{ font-size: 10px; color: {MUTED}; }}

/* ---- Banner ---- */
.banner {{ margin-bottom: 18px; }}
.banner-rule {{ height: 2px; background: {RULE}; margin: 6px 0; }}
.banner-headline {{
  font-size: 34px; font-weight: 900; line-height: 1.1; color: {HEADLINE};
  text-align: center; padding: 6px 0;
  text-transform: uppercase; letter-spacing: -0.5px;
}}
.banner-deck {{
  text-align: center; font-size: 13px; color: {INK_2}; letter-spacing: 0.3px;
  margin-top: 4px; font-style: italic;
}}

/* ---- Three-column layout ---- */
.three-col {{
  display: grid; grid-template-columns: 320px 240px 1fr;
  gap: 0; margin-bottom: 18px;
  border: 1px solid {RULE};
}}
.col-left {{ border-right: 1px solid {RULE}; padding: 16px 14px; }}
.col-mid {{ border-right: 1px solid {RULE}; padding: 16px 14px; }}
.col-right {{ padding: 16px 16px; }}
.col-head {{
  font-size: 10px; font-weight: 800; letter-spacing: 2px; text-transform: uppercase;
  color: {MUTED}; border-bottom: 2px solid {INK}; padding-bottom: 5px; margin-bottom: 10px;
}}

/* ---- League table ---- */
.lt {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.lt thead tr {{ border-bottom: 1px solid {RULE}; }}
.lt th {{
  font-size: 10px; letter-spacing: 0.8px; color: {MUTED}; text-transform: uppercase;
  font-weight: 700; padding: 3px 4px; text-align: right;
}}
.lt th:nth-child(3) {{ text-align: left; }}
.lt td {{ padding: 5px 4px; vertical-align: middle; border-bottom: 1px solid {RULE}; }}
.lt tbody tr:last-child td {{ border-bottom: none; }}
.lt-leader td {{ background: #fffbea; font-weight: 700; }}
.lt-rk {{ font-size: 16px; font-weight: 800; text-align: center; color: {INK}; }}
.lt-mv {{ text-align: center; }}
.lt-nm {{ font-size: 13px; font-weight: 600; color: {INK}; }}
.lt-tot {{ text-align: right; font-weight: 800; font-size: 14px; font-variant-numeric: tabular-nums; }}
.lt-gw {{ text-align: right; font-weight: 700; color: {HEADLINE}; font-variant-numeric: tabular-nums; }}
.lt-chip {{
  font-size: 9px; font-weight: 800; background: #e8e0ff; color: #4a00a0;
  border-radius: 3px; padding: 1px 4px; vertical-align: middle; margin-left: 2px;
}}
.lt-hit {{
  font-size: 9px; font-weight: 800; background: #ffe0e0; color: {HEADLINE};
  border-radius: 3px; padding: 1px 4px; vertical-align: middle; margin-left: 2px;
}}
.mv-up {{ color: {UP}; font-weight: 800; font-size: 11px; }}
.mv-dn {{ color: {DOWN}; font-weight: 800; font-size: 11px; }}
.mv-flat {{ color: {MUTED}; font-size: 11px; }}

/* ---- Captain column ---- */
.cap-list {{ display: flex; flex-direction: column; gap: 8px; }}
.cap-row {{
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 6px 0; border-bottom: 1px solid {RULE};
}}
.cap-row:last-child {{ border-bottom: none; }}
.cap-mgr {{ font-size: 12px; font-weight: 700; color: {INK}; }}
.cap-player {{ font-size: 11px; color: {MUTED}; margin-top: 1px; }}
.cap-pts {{ font-size: 16px; font-weight: 800; text-align: right; min-width: 44px; }}
.cap-good {{ color: {UP}; }}
.cap-meh {{ color: {INK_2}; }}

/* ---- Match report ---- */
.report-para {{
  font-size: 14px; line-height: 1.65; color: {INK}; margin-bottom: 10px;
  text-align: justify; hyphens: auto;
}}
.report-para.dropcap {{ margin-top: 4px; }}
.drop {{
  float: left; font-size: 52px; line-height: 0.78; font-weight: 900; color: {HEADLINE};
  margin: 4px 6px -2px 0; font-family: Georgia, serif;
}}
.no-narrative {{ color: {MUTED}; font-style: italic; font-size: 13px; }}

/* ---- Stats strip ---- */
.stats-strip {{
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 0; border: 1px solid {RULE}; margin-bottom: 18px;
}}
.stat-box {{
  padding: 16px 16px; border-right: 1px solid {RULE}; text-align: center;
}}
.stat-box:last-child {{ border-right: none; }}
.stat-emoji {{ font-size: 24px; margin-bottom: 4px; }}
.stat-kicker {{ font-size: 9px; letter-spacing: 1.5px; color: {MUTED}; text-transform: uppercase; font-weight: 700; }}
.stat-name {{ font-size: 14px; font-weight: 800; color: {INK}; margin-top: 4px; }}
.stat-value {{ font-size: 22px; font-weight: 900; color: {HEADLINE}; margin-top: 2px; }}
.stat-sub {{ font-size: 10px; color: {MUTED}; margin-top: 2px; }}

/* ---- Section header ---- */
.np-section {{ margin-bottom: 22px; }}
.np-section-head {{
  display: flex; align-items: center; gap: 12px; margin-bottom: 14px;
}}
.np-head-rule {{ flex: 1; height: 2px; background: {RULE}; }}
.np-head-title {{
  font-size: 11px; font-weight: 800; letter-spacing: 2.5px; text-transform: uppercase;
  color: {INK_2}; white-space: nowrap;
}}

/* ---- Race chart ---- */
.chart-box {{
  border: 1px solid {RULE}; padding: 12px; background: {PAPER};
  overflow-x: auto;
}}
.chart-caption {{ font-size: 10px; color: {MUTED}; text-align: center; margin-top: 6px; }}

/* ---- Manager cards ---- */
.mc-grid {{
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
}}
.mc {{
  border: 1px solid {RULE}; border-top: 3px solid; background: {PAPER};
  padding: 12px 12px 10px;
}}
.mc-top {{ display: flex; align-items: center; gap: 10px; }}
.mc-rank {{ font-size: 24px; font-weight: 900; }}
.mc-id {{ flex: 1; min-width: 0; }}
.mc-name {{ font-size: 13px; font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.mc-team {{ font-size: 10px; color: {MUTED}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.mc-gwv {{ font-size: 20px; font-weight: 900; font-variant-numeric: tabular-nums; }}
.mc-tags {{ display: flex; gap: 5px; flex-wrap: wrap; margin: 6px 0 4px; font-size: 10px; }}
.mc-chip {{
  background: #e8e0ff; color: #4a00a0; border-radius: 3px;
  padding: 1px 5px; font-weight: 800;
}}
.mc-hit {{
  background: #ffe0e0; color: {HEADLINE}; border-radius: 3px;
  padding: 1px 5px; font-weight: 800;
}}
.mc-spark {{ margin: 4px 0; }}
.mc-stats {{ margin-top: 6px; border-top: 1px solid {RULE}; padding-top: 6px; display: flex; flex-direction: column; gap: 3px; }}
.mcs {{ display: flex; justify-content: space-between; font-size: 11px; }}
.mcs-k {{ color: {MUTED}; }}
.mcs-v {{ font-weight: 700; text-align: right; }}
.cap-good {{ color: {UP}; }}
.cap-bad {{ color: {DOWN}; }}
.cap-meh {{ color: {INK_2}; }}

/* ---- Intel section ---- */
.intel-grid {{
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 0; border: 1px solid {RULE};
}}
.intel-panel {{ padding: 14px 14px; border-right: 1px solid {RULE}; }}
.intel-panel:last-child {{ border-right: none; }}
.intel-panel-head {{
  font-size: 10px; font-weight: 800; letter-spacing: 1.5px; text-transform: uppercase;
  color: {INK_2}; border-bottom: 1px solid {RULE}; padding-bottom: 6px; margin-bottom: 10px;
}}
.intel-note {{ font-weight: 500; color: {MUTED}; letter-spacing: 0; }}
.intel-row {{
  display: flex; align-items: center; gap: 8px;
  padding: 5px 0; border-bottom: 1px solid {RULE}; font-size: 12px;
}}
.intel-row:last-child {{ border-bottom: none; }}
.intel-rank {{ font-weight: 800; color: {MUTED}; min-width: 24px; }}
.intel-name {{ flex: 1; font-weight: 600; }}
.intel-val {{ font-weight: 800; color: {HEADLINE}; min-width: 36px; text-align: right; }}
/* Captaincy bars */
.ct-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 7px; font-size: 12px; }}
.ct-row:last-child {{ margin-bottom: 0; }}
.ct-name {{ font-weight: 600; min-width: 90px; }}
.ct-bar-wrap {{ flex: 1; background: {RULE}; border-radius: 2px; height: 8px; overflow: hidden; }}
.ct-bar {{ height: 100%; background: {HEADLINE}; border-radius: 2px; }}
.ct-meta {{ font-size: 10px; color: {MUTED}; white-space: nowrap; min-width: 70px; text-align: right; }}
/* Rivalries */
.rv-row {{
  display: flex; align-items: center; gap: 8px;
  padding: 5px 0; border-bottom: 1px solid {RULE}; font-size: 12px;
}}
.rv-row:last-child {{ border-bottom: none; }}
.rv-a {{ font-weight: 700; flex: 1; }}
.rv-gap {{
  font-size: 10px; font-weight: 800; background: #fffbea; border: 1px solid {ACCENT};
  border-radius: 3px; padding: 1px 5px; white-space: nowrap; color: {ACCENT};
}}
.rv-b {{ font-size: 11px; color: {MUTED}; flex: 1; text-align: right; }}

/* ---- Footer ---- */
.np-footer {{ margin-top: 20px; }}
.footer-rule {{ height: 3px; background: {INK}; margin-bottom: 2px; }}
.footer-inner {{
  display: flex; justify-content: space-between; font-size: 10px;
  color: {MUTED}; padding: 4px 0; letter-spacing: 0.5px;
}}
.footer-right {{ text-align: right; }}
"""
