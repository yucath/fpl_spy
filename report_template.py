"""
report_template.py — renders the report payload (see report.build_payload) to a
standalone HTML string for headless-Chromium -> single tall PNG.

Entry point (stable):
    render_report_html(payload: dict) -> str

All charts are inline SVG computed in Python. No external assets, no JS.
Designed at a fixed 1200px width; height unbounded (long infographic).
"""

from __future__ import annotations

import html
import math
from typing import List, Optional, Sequence

# --------------------------------------------------------------------------- #
#  Palette / design tokens
# --------------------------------------------------------------------------- #
BG          = "#070b16"     # page base (near-black navy)
PANEL       = "#101728"     # card surface
PANEL_2     = "#0b1120"     # deeper card surface
STROKE      = "#20304d"     # borders
STROKE_SOFT = "#18233a"
TEXT        = "#eef2fb"     # primary text
MUTED       = "#8ea0c2"     # secondary text
FAINT       = "#5d6f92"     # tertiary text
ACCENT      = "#2df3a0"     # FPL green/teal (primary pop)
ACCENT_DK   = "#12b57a"
MAGENTA     = "#ff3d92"     # magenta/purple pop
PURPLE      = "#8b6dff"
GOLD        = "#ffd23f"
UP          = "#2df3a0"
DOWN        = "#ff5d73"
FLAT        = "#5d6f92"

# distinct series colors for the multi-line season race chart
SERIES_COLORS = [
    "#2df3a0", "#ff3d92", "#8b6dff", "#ffd23f", "#4fc3ff", "#ff9f45",
    "#42e6c8", "#f76bdc", "#9be15d", "#ff6b6b", "#c084fc", "#38bdf8",
]

CHIP_SHORT = {
    "wildcard": "WC", "freehit": "FH", "bboost": "BB", "3xc": "TC",
    "Wildcard": "WC", "Free Hit": "FH", "Bench Boost": "BB",
    "Triple Captain": "TC",
}
CHIP_EMOJI = {
    "Wildcard": "🃏", "Free Hit": "🎟️", "Bench Boost": "🚀",
    "Triple Captain": "©️",
}


# --------------------------------------------------------------------------- #
#  Small helpers
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
    """Format an overall (global) rank compactly, e.g. 141975 -> 142k."""
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


def _pts(points: Sequence[float]) -> List[float]:
    return [float(p) for p in points]


def _poly_points(xs: Sequence[float], ys: Sequence[float]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in zip(xs, ys))


# --------------------------------------------------------------------------- #
#  SVG chart builders
# --------------------------------------------------------------------------- #
def sparkline(values: Sequence[float], w: int = 240, h: int = 54,
              color: str = ACCENT, fill: bool = True) -> str:
    """Area+line sparkline. Marks best (up) and worst (down) points."""
    vals = _pts(values)
    if not vals:
        return f'<svg width="{w}" height="{h}"></svg>'
    if len(vals) == 1:
        cy = h / 2
        return (
            f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<line x1="6" y1="{cy:.1f}" x2="{w-6}" y2="{cy:.1f}" '
            f'stroke="{STROKE}" stroke-width="1.5" stroke-dasharray="3 4"/>'
            f'<circle cx="{w/2:.1f}" cy="{cy:.1f}" r="4.5" fill="{color}"/>'
            f'</svg>'
        )
    pad = 6
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    n = len(vals)
    xs = [pad + (w - 2 * pad) * i / (n - 1) for i in range(n)]
    ys = [(h - pad) - (h - 2 * pad) * (v - lo) / rng for v in vals]
    line = _poly_points(xs, ys)
    area = f"{xs[0]:.2f},{h-pad:.2f} " + line + f" {xs[-1]:.2f},{h-pad:.2f}"
    imax = vals.index(hi)
    imin = vals.index(lo)
    gid = f"sg{abs(hash((tuple(vals), w, color))) % 100000}"
    fill_svg = ""
    if fill:
        fill_svg = (
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{color}" stop-opacity="0.34"/>'
            f'<stop offset="1" stop-color="{color}" stop-opacity="0"/>'
            f'</linearGradient></defs>'
            f'<polygon points="{area}" fill="url(#{gid})"/>'
        )
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">{fill_svg}'
        f'<polyline points="{line}" fill="none" stroke="{color}" '
        f'stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{xs[imax]:.2f}" cy="{ys[imax]:.2f}" r="3.6" fill="{color}"/>'
        f'<circle cx="{xs[imin]:.2f}" cy="{ys[imin]:.2f}" r="3.2" '
        f'fill="{BG}" stroke="{DOWN}" stroke-width="2"/>'
        f'</svg>'
    )


def hbar_chart(rows: List[tuple], w: int = 520, bar_h: int = 26, gap: int = 12,
               color: str = ACCENT, label_w: int = 150,
               max_val: Optional[float] = None, unit: str = "") -> str:
    """Horizontal bar chart. rows = [(label, value, highlight_bool), ...]."""
    if not rows:
        return ""
    vals = [r[1] for r in rows]
    mx = max_val if max_val is not None else (max(vals) or 1)
    mx = mx or 1
    n = len(rows)
    val_w = 54
    track_w = w - label_w - val_w
    h = n * bar_h + (n - 1) * gap
    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    for i, (label, val, hi) in enumerate(rows):
        y = i * (bar_h + gap)
        bw = max(2.0, track_w * (float(val) / mx))
        c = GOLD if hi else color
        out.append(
            f'<text x="{label_w-12}" y="{y+bar_h*0.5+5:.0f}" text-anchor="end" '
            f'fill="{TEXT if hi else MUTED}" font-size="15" '
            f'font-weight="{700 if hi else 500}">{esc(label)}</text>'
        )
        out.append(
            f'<rect x="{label_w}" y="{y}" width="{track_w}" height="{bar_h}" '
            f'rx="6" fill="{STROKE_SOFT}"/>'
        )
        out.append(
            f'<rect x="{label_w}" y="{y}" width="{bw:.1f}" height="{bar_h}" '
            f'rx="6" fill="{c}"/>'
        )
        vlabel = (f"{val:g}" if isinstance(val, float) else f"{val}") + unit
        out.append(
            f'<text x="{label_w+track_w+10}" y="{y+bar_h*0.5+5:.0f}" '
            f'fill="{TEXT}" font-size="15" font-weight="700" '
            f'font-family="ui-monospace,Menlo,monospace">{esc(vlabel)}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def race_chart(managers: List[dict], w: int = 1120, h: int = 470,
               mode: str = "rank") -> str:
    """Multi-line season-race chart.

    mode="rank"  -> mini-league position (1 at top).
    mode="cum"   -> cumulative points.
    Labels every series at the right edge, de-collided.
    """
    gws = None
    for m in managers:
        g = m.get("season", {}).get("gws") or []
        if len(g) > (len(gws) if gws else 0):
            gws = g
    if not gws or len(gws) < 2:
        return ""

    pad_l, pad_r, pad_t, pad_b = 46, 176, 22, 34
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
        allc = [c for m in managers for c in (m.get("season", {}).get("cumulative") or [])]
        vmin, vmax = (min(allc), max(allc)) if allc else (0, 1)

        def sy(v):
            return pad_t + plot_h - plot_h * (v - vmin) / ((vmax - vmin) or 1)
        step = max(1, round((vmax - vmin) / 4))
        y_ticks = list(range(int(vmin), int(vmax) + 1, step))

    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    for t in y_ticks:
        yy = sy(t)
        out.append(
            f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{pad_l+plot_w}" y2="{yy:.1f}" '
            f'stroke="{STROKE_SOFT}" stroke-width="1"/>'
        )
        lbl = f"#{t}" if mode == "rank" else fnum(t)
        out.append(
            f'<text x="{pad_l-10}" y="{yy+4:.1f}" text-anchor="end" '
            f'fill="{FAINT}" font-size="12">{lbl}</text>'
        )
    xt_count = min(len(gws), 8)
    xstep = max(1, (len(gws) - 1) // max(1, xt_count - 1))
    for i in range(0, len(gws), xstep):
        gw = gws[i]
        xx = sx(gw)
        out.append(
            f'<text x="{xx:.1f}" y="{h-12}" text-anchor="middle" '
            f'fill="{FAINT}" font-size="12">GW{gw}</text>'
        )

    label_anchors = []
    for idx, m in enumerate(managers):
        s = m.get("season", {})
        mg = s.get("gws") or []
        series = (s.get("league_rank") if mode == "rank" else s.get("cumulative")) or []
        pts = list(zip(mg, series))
        if len(pts) < 2:
            continue
        color = SERIES_COLORS[idx % len(SERIES_COLORS)]
        is_leader = (m.get("rank") == 1)
        xs = [sx(g) for g, _ in pts]
        ys = [sy(v) for _, v in pts]
        wln = 3.6 if is_leader else 1.9
        op = 1.0 if is_leader else 0.75
        out.append(
            f'<polyline points="{_poly_points(xs, ys)}" fill="none" '
            f'stroke="{color}" stroke-width="{wln}" stroke-opacity="{op}" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        out.append(
            f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="{4 if is_leader else 3}" '
            f'fill="{color}"/>'
        )
        label_anchors.append((ys[-1], color, m.get("name", ""), is_leader))

    label_anchors.sort(key=lambda t: t[0])
    min_gap = 19
    placed = []
    for y0, *_ in label_anchors:
        y = y0
        if placed and y < placed[-1] + min_gap:
            y = placed[-1] + min_gap
        placed.append(y)
    lx = pad_l + plot_w + 12
    for (orig, color, name, is_leader), y in zip(label_anchors, placed):
        short = name.split()[0] if name else ""
        out.append(
            f'<line x1="{pad_l+plot_w}" y1="{orig:.1f}" x2="{lx-3}" y2="{y:.1f}" '
            f'stroke="{color}" stroke-width="1" stroke-opacity="0.5"/>'
        )
        out.append(f'<circle cx="{lx+2}" cy="{y:.1f}" r="3.4" fill="{color}"/>')
        out.append(
            f'<text x="{lx+11}" y="{y+4:.1f}" fill="{TEXT if is_leader else MUTED}" '
            f'font-size="12.5" font-weight="{700 if is_leader else 500}">'
            f'{esc(short)}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def split_donut(def_pts, att_pts, size: int = 108) -> str:
    """Donut splitting defensive vs attacking points."""
    d = max(0.0, float(def_pts or 0))
    a = max(0.0, float(att_pts or 0))
    tot = d + a
    r = size / 2 - 10
    cx = cy = size / 2
    sw = 13
    circ = 2 * math.pi * r
    if tot <= 0:
        return (
            f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="{STROKE}" stroke-width="{sw}"/>'
            f'<text x="{cx}" y="{cy+5}" text-anchor="middle" fill="{FAINT}" '
            f'font-size="13">n/a</text></svg>'
        )
    a_len = circ * (a / tot)
    d_len = circ - a_len
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'<g transform="rotate(-90 {cx} {cy})">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{MAGENTA}" '
        f'stroke-width="{sw}" stroke-dasharray="{a_len:.2f} {circ:.2f}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{ACCENT}" '
        f'stroke-width="{sw}" stroke-dasharray="{d_len:.2f} {circ:.2f}" '
        f'stroke-dashoffset="{-a_len:.2f}"/>'
        f'</g>'
        f'<text x="{cx}" y="{cy-2}" text-anchor="middle" fill="{TEXT}" '
        f'font-size="20" font-weight="800">{int(tot)}</text>'
        f'<text x="{cx}" y="{cy+15}" text-anchor="middle" fill="{FAINT}" '
        f'font-size="10" letter-spacing="1">A/D PTS</text>'
        f'</svg>'
    )


def movement_badge(mv) -> str:
    try:
        mv = int(mv)
    except (ValueError, TypeError):
        mv = 0
    if mv > 0:
        return f'<span class="mv up">▲ {mv}</span>'
    if mv < 0:
        return f'<span class="mv down">▼ {abs(mv)}</span>'
    return '<span class="mv flat">–</span>'


# --------------------------------------------------------------------------- #
#  Section renderers
# --------------------------------------------------------------------------- #
def render_hero(meta: dict) -> str:
    is_final = bool(meta.get("is_final"))
    badge = (
        '<span class="badge final">✓ FINAL</span>' if is_final
        else '<span class="badge live"><span class="dot"></span>LIVE</span>'
    )
    season = meta.get("season_label") or ""
    season_html = f' · {esc(season)}' if season else ""
    return f"""
    <header class="hero">
      <div class="hero-top">
        <div class="hero-kicker">FANTASY PREMIER LEAGUE · MINI-LEAGUE REPORT</div>
        {badge}
      </div>
      <h1 class="hero-title">{esc(meta.get('league_name',''))}</h1>
      <div class="hero-sub">Gameweek {esc(meta.get('gameweek',''))}{season_html}</div>
      <div class="hero-stats">
        <div class="hstat"><div class="hstat-v">{esc(meta.get('gameweek',''))}</div>
          <div class="hstat-l">Gameweek</div></div>
        <div class="hstat"><div class="hstat-v">{esc(meta.get('num_managers',''))}</div>
          <div class="hstat-l">Managers</div></div>
        <div class="hstat"><div class="hstat-v accent">{fnum(meta.get('gw_average'),1)}</div>
          <div class="hstat-l">GW Average</div></div>
        <div class="hstat"><div class="hstat-v small">{esc(meta.get('generated_at',''))}</div>
          <div class="hstat-l">Generated</div></div>
      </div>
    </header>"""


def render_league_table(managers: List[dict]) -> str:
    if not managers:
        return ""
    gwmax = max((abs(m.get("gw_points", 0)) for m in managers), default=1) or 1
    totmin = min((m.get("total_points", 0) for m in managers), default=0)
    totmax = max((m.get("total_points", 0) for m in managers), default=1)
    totrng = (totmax - totmin) or 1
    rows = []
    for m in managers:
        rank = m.get("rank", 0)
        leader = rank == 1
        gw = m.get("gw_points", 0)
        hit = m.get("gw_hit", 0)
        chip = m.get("chip")
        chip_html = ""
        if chip:
            em = CHIP_EMOJI.get(chip, "🎯")
            chip_html = f'<span class="tag chip">{em} {esc(chip)}</span>'
        hit_html = f'<span class="tag hit">-{esc(hit)}</span>' if hit else ""
        gw_w = 100 * abs(gw) / gwmax
        tot_frac = (m.get("total_points", 0) - totmin) / totrng
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "")
        rankcell = (f'<span class="rk-num">{esc(rank)}</span>'
                    f'<span class="rk-medal">{medal}</span>')
        rows.append(f"""
        <div class="lt-row{' leader' if leader else ''}">
          <div class="lt-rank">{rankcell}</div>
          <div class="lt-mv">{movement_badge(m.get('rank_movement'))}</div>
          <div class="lt-name">
            <div class="nm">{esc(m.get('name',''))} {chip_html}{hit_html}</div>
            <div class="tm">{esc(m.get('team_name',''))}</div>
          </div>
          <div class="lt-total">
            <div class="tot-v">{fnum(m.get('total_points'))}</div>
            <div class="tot-bar"><span style="width:{tot_frac*100:.1f}%"></span></div>
          </div>
          <div class="lt-gw">
            <div class="gw-v">{esc(gw)}</div>
            <div class="gw-bar"><span style="width:{gw_w:.1f}%"></span></div>
          </div>
          <div class="lt-or">{compact_rank(m.get('overall_rank'))}</div>
        </div>""")
    return f"""
    <section class="card">
      <div class="sec-head"><span class="sec-ico">🏆</span>
        <h2>League Table</h2>
        <span class="sec-note">total points · this GW · global rank</span></div>
      <div class="lt-head">
        <div>#</div><div>+/-</div><div>Manager</div>
        <div>Total</div><div>GW</div><div>Global</div>
      </div>
      <div class="lt">{''.join(rows)}</div>
    </section>"""


def render_race(managers: List[dict]) -> str:
    svg = race_chart(managers, mode="rank")
    if not svg:
        return ""
    return f"""
    <section class="card">
      <div class="sec-head"><span class="sec-ico">📈</span>
        <h2>The Season Race</h2>
        <span class="sec-note">mini-league position after each gameweek · top = 1st</span></div>
      <div class="chart-wrap">{svg}</div>
    </section>"""


def render_weekly_wins(league: dict) -> str:
    ww = league.get("weekly_wins") or []
    ww = [w for w in ww if (w.get("wins") or 0) > 0]
    if not ww:
        return ""
    ww = sorted(ww, key=lambda w: w.get("wins", 0), reverse=True)
    rows = [(w.get("name", "").split()[0], w.get("wins", 0), i == 0)
            for i, w in enumerate(ww)]
    chart = hbar_chart(rows, w=540, color=PURPLE, label_w=110)
    return f"""
    <section class="card half">
      <div class="sec-head"><span class="sec-ico">👑</span>
        <h2>Weekly Wins</h2>
        <span class="sec-note">GW top-score crowns</span></div>
      <div class="chart-wrap tight">{chart}</div>
    </section>"""


def render_gw_standings(league: dict) -> str:
    gs = league.get("gw_standings") or []
    if not gs:
        return ""
    rows = [(g.get("name", "").split()[0], g.get("gw_points", 0), i == 0)
            for i, g in enumerate(gs)]
    chart = hbar_chart(rows, w=540, color=ACCENT, label_w=110)
    return f"""
    <section class="card half">
      <div class="sec-head"><span class="sec-ico">⚡</span>
        <h2>This Gameweek</h2>
        <span class="sec-note">net points scored</span></div>
      <div class="chart-wrap tight">{chart}</div>
    </section>"""


def render_highlights(highlights: dict) -> str:
    if not highlights:
        return ""
    cards = []

    def card(emoji, kicker, name, big, sub, accent):
        return f"""
        <div class="hl-card" style="--hlc:{accent}">
          <div class="hl-emoji">{emoji}</div>
          <div class="hl-kick">{esc(kicker)}</div>
          <div class="hl-name">{esc(name)}</div>
          <div class="hl-big">{big}</div>
          <div class="hl-sub">{esc(sub)}</div>
        </div>"""

    h = highlights
    if h.get("comeback"):
        c = h["comeback"]
        cards.append(card("📈", "Comeback King", c.get("manager", ""),
                          f'#{esc(c.get("prev_rank","?"))} → #{esc(c.get("current_rank","?"))}',
                          f'climbed {abs(c.get("change",0))} place(s)', ACCENT))
    if h.get("choke"):
        c = h["choke"]
        cards.append(card("📉", "Biggest Choke", c.get("manager", ""),
                          f'#{esc(c.get("prev_rank","?"))} → #{esc(c.get("current_rank","?"))}',
                          f'dropped {abs(c.get("change",0))} place(s)', DOWN))
    if h.get("captain_fail"):
        c = h["captain_fail"]
        cards.append(card("🤡", "Captain Flop", c.get("manager", ""),
                          esc(c.get("captain", "")),
                          f'armband returned just {c.get("points",0)} pts', GOLD))
    if h.get("differential_hero"):
        c = h["differential_hero"]
        own = c.get("ownership_pct")
        owns = f'{own:g}% owned' if own is not None else "low-owned punt"
        cards.append(card("💎", "Differential Gem", c.get("manager", ""),
                          esc(c.get("player", "")),
                          f'{c.get("points",0)} pts · {owns}', PURPLE))
    if h.get("bench_hero"):
        c = h["bench_hero"]
        cards.append(card("🪑", "Bench Heartbreak", c.get("manager", ""),
                          esc(c.get("player", "")),
                          f'{c.get("points",0)} pts left on the bench', MAGENTA))
    if not cards:
        return ""
    return f"""
    <section class="card">
      <div class="sec-head"><span class="sec-ico">🎬</span>
        <h2>Gameweek Highlights</h2>
        <span class="sec-note">the heroes, villains &amp; heartbreak</span></div>
      <div class="hl-grid n{len(cards)}">{''.join(cards)}</div>
    </section>"""


def _form_badge(form: dict) -> str:
    state = (form or {}).get("state", "steady")
    diff = (form or {}).get("diff", 0)
    conf = {
        "hot":    ("🔥", "HOT", "hot"),
        "cold":   ("🥶", "COLD", "cold"),
        "steady": ("➖", "STEADY", "steady"),
    }.get(state, ("➖", "STEADY", "steady"))
    sign = "+" if (diff or 0) >= 0 else ""
    return (f'<span class="form-badge {conf[2]}">{conf[0]} {conf[1]} '
            f'<b>{sign}{fnum(diff,1)}</b></span>')


def render_manager_card(m: dict, idx: int) -> str:
    s = m.get("season", {}) or {}
    color = SERIES_COLORS[idx % len(SERIES_COLORS)]
    spark = sparkline(s.get("net_points") or [], w=250, h=56, color=color)
    donut = split_donut(m.get("defensive_points"), m.get("attacking_points"))
    best = s.get("best_gw") or {}
    worst = s.get("worst_gw") or {}
    rank = m.get("rank", 0)

    cap = m.get("captain", "")
    capp = m.get("captain_points", 0)
    cap_cls = "bad" if (capp is not None and capp <= 2) else "good"

    chip = m.get("chip")
    chip_pill = (f'<span class="mc-chip">{CHIP_EMOJI.get(chip,"🎯")} {esc(chip)}</span>'
                 if chip else "")
    hit = m.get("gw_hit", 0)
    hit_pill = f'<span class="mc-hit">-{esc(hit)} hit</span>' if hit else ""

    chips_used = s.get("chips_used") or []
    chip_dots = ""
    if chips_used:
        items = "".join(
            f'<span class="cu">{CHIP_SHORT.get(c.get("chip"), "?")}'
            f'<i>GW{esc(c.get("gw",""))}</i></span>'
            for c in chips_used
        )
        chip_dots = (f'<div class="mc-chips"><span class="cu-lbl">CHIPS</span>'
                     f'{items}</div>')

    ts_played = m.get("top_scorer_played")
    ts_mark = "" if ts_played else " (DNP)"

    return f"""
    <div class="mc" style="--mc:{color}">
      <div class="mc-top">
        <div class="mc-rank">{esc(rank)}</div>
        <div class="mc-id">
          <div class="mc-name">{esc(m.get('name',''))}</div>
          <div class="mc-team">{esc(m.get('team_name',''))}</div>
        </div>
        <div class="mc-gw">
          <div class="mc-gw-v">{esc(m.get('gw_points',0))}</div>
          <div class="mc-gw-l">GW PTS</div>
        </div>
      </div>
      <div class="mc-tags">
        {_form_badge(m.get('form'))}
        <span class="mc-meta">📐 {esc(m.get('formation',''))}</span>
        {chip_pill}{hit_pill}
      </div>
      <div class="mc-mid">
        <div class="mc-spark">
          <div class="mc-spark-hd">SEASON FORM · net pts / GW</div>
          {spark}
          <div class="mc-bw">
            <span class="bw-good">▲ Best GW{esc(best.get('gw','—'))} · {esc(best.get('points','—'))}</span>
            <span class="bw-bad">▼ Worst GW{esc(worst.get('gw','—'))} · {esc(worst.get('points','—'))}</span>
          </div>
        </div>
        <div class="mc-donut">
          {donut}
          <div class="mc-donut-key">
            <span><i style="background:{MAGENTA}"></i>Att {esc(m.get('attacking_points',0))}</span>
            <span><i style="background:{ACCENT}"></i>Def {esc(m.get('defensive_points',0))}</span>
          </div>
        </div>
      </div>
      <div class="mc-grid">
        <div class="kv"><span class="k">© Captain</span>
          <span class="v cap-{cap_cls}">{esc(cap)} · {esc(capp)}</span></div>
        <div class="kv"><span class="k">⭐ Top Scorer</span>
          <span class="v">{esc(m.get('top_scorer',''))} · {esc(m.get('top_scorer_points',0))}{ts_mark}</span></div>
        <div class="kv"><span class="k">🪑 Bench</span>
          <span class="v">{esc(m.get('bench_points',0))} pts</span></div>
        <div class="kv"><span class="k">🌍 Global Rank</span>
          <span class="v">{compact_rank(m.get('overall_rank'))}</span></div>
        <div class="kv"><span class="k">💰 Team Value</span>
          <span class="v">£{fnum(m.get('team_value'),1)}m</span></div>
        <div class="kv"><span class="k">🏦 In Bank</span>
          <span class="v">£{fnum(m.get('bank'),1)}m</span></div>
        <div class="kv"><span class="k">🔁 Transfers</span>
          <span class="v">{esc(s.get('transfers_total',0))} · {esc(s.get('hits_total',0))}pt hits</span></div>
        <div class="kv"><span class="k">📊 Season Avg</span>
          <span class="v">{fnum(s.get('avg'),1)} pts</span></div>
      </div>
      {chip_dots}
    </div>"""


def render_manager_cards(managers: List[dict]) -> str:
    if not managers:
        return ""
    cards = "".join(render_manager_card(m, i) for i, m in enumerate(managers))
    return f"""
    <section class="card">
      <div class="sec-head"><span class="sec-ico">🧾</span>
        <h2>Manager Dossiers</h2>
        <span class="sec-note">the season so far, manager by manager</span></div>
      <div class="mc-grid-wrap">{cards}</div>
    </section>"""


def render_captaincy_trends(league: dict) -> str:
    """Who captained what across the league + power rankings + bench leaderboard."""
    trends = league.get("captaincy_trends") or []
    power = league.get("power_rankings") or []
    bench = league.get("bench_leaderboard") or []
    rivalries = (league.get("rivalries") or [])[:6]

    if not (trends or power or bench):
        return ""

    # Captain donut bars
    cap_html = ""
    if trends:
        max_cnt = trends[0]["count"] if trends else 1
        rows = []
        for t in trends[:5]:
            pct = t["count"] / max_cnt * 100
            pts_txt = f'{t["gw_pts"]}pts' if t["gw_pts"] else "—"
            owned_txt = f'{t["pct"]}% of mgrs'
            rows.append(f"""
            <div class="ct-row">
              <div class="ct-name">{esc(t['player'])}</div>
              <div class="ct-bar-wrap">
                <div class="ct-bar" style="width:{pct:.0f}%"></div>
              </div>
              <div class="ct-meta">{esc(owned_txt)} · {esc(pts_txt)}</div>
            </div>""")
        cap_html = f"""
        <div class="extra-panel">
          <div class="ep-head">⚽ Captaincy Trends</div>
          {''.join(rows)}
        </div>"""

    # Power rankings table
    pw_html = ""
    if power:
        rows = []
        for p in power[:8]:
            delta = p.get("delta", 0)
            if delta >= 2:
                arrow = f'<span class="pr-up">▲{delta}</span>'
            elif delta <= -2:
                arrow = f'<span class="pr-dn">▼{abs(delta)}</span>'
            else:
                arrow = '<span class="pr-flat">—</span>'
            rows.append(f"""
            <div class="pr-row">
              <span class="pr-rank">#{esc(p['power_rank'])}</span>
              <span class="pr-name">{esc(p['name'])}</span>
              <span class="pr-score">{esc(p['score'])}</span>
              {arrow}
            </div>""")
        pw_html = f"""
        <div class="extra-panel">
          <div class="ep-head">📊 Power Rankings <span class="ep-note">form-weighted avg</span></div>
          {''.join(rows)}
        </div>"""

    # Bench leaderboard
    bn_html = ""
    if bench:
        rows = []
        for b in bench[:6]:
            gw_note = f'+{b["gw_bench"]}' if b["gw_bench"] else "—"
            rows.append(f"""
            <div class="pr-row">
              <span class="pr-name">{esc(b['name'])}</span>
              <span class="pr-score">{esc(b['season_bench'])}pts</span>
              <span class="pr-flat">GW: {esc(gw_note)}</span>
            </div>""")
        bn_html = f"""
        <div class="extra-panel">
          <div class="ep-head">🪑 Bench Pain <span class="ep-note">season total</span></div>
          {''.join(rows)}
        </div>"""

    # Rivalries
    rv_html = ""
    if rivalries:
        items = "".join(
            f'<div class="rv-item">'
            f'<span class="rv-a">{esc(r["leader"])}</span>'
            f'<span class="rv-gap">+{esc(r["gap"])}pts</span>'
            f'<span class="rv-b">{esc(r["chaser"])}</span>'
            f'</div>'
            for r in rivalries[:5]
        )
        rv_html = f"""
        <div class="extra-panel extra-panel-wide">
          <div class="ep-head">⚔️ Rivalries <span class="ep-note">current overall gaps</span></div>
          <div class="rv-grid">{items}</div>
        </div>"""

    inner = "".join(filter(None, [cap_html, pw_html, bn_html, rv_html]))
    return f"""
    <section class="card">
      <div class="sec-head"><span class="sec-ico">📈</span>
        <h2>League Intel</h2>
        <span class="sec-note">captaincy · power rankings · bench pain · rivalries</span>
      </div>
      <div class="extra-grid">{inner}</div>
    </section>"""


def render_narrative(narrative: str) -> str:
    if not narrative or not narrative.strip():
        return ""
    paras = [p.strip() for p in narrative.split("\n") if p.strip()]
    body = "".join(f"<p>{esc(p)}</p>" for p in paras)
    return f"""
    <section class="card pundit">
      <div class="sec-head"><span class="sec-ico">🎙️</span>
        <h2>The Pundit's Take</h2>
        <span class="sec-note">AI-written recap</span></div>
      <div class="pundit-body">
        <span class="quote-mark">“</span>
        {body}
      </div>
    </section>"""


def render_footer(meta: dict) -> str:
    season = meta.get("season_label")
    seg = f" · {esc(season)}" if season else ""
    return f"""
    <footer class="footer">
      <div>{esc(meta.get('league_name',''))} · Gameweek {esc(meta.get('gameweek',''))}{seg}</div>
      <div class="foot-mono">Generated {esc(meta.get('generated_at',''))} · FPL Spy automated report</div>
    </footer>"""


# --------------------------------------------------------------------------- #
#  Master
# --------------------------------------------------------------------------- #
def render_report_html(payload: dict) -> str:
    meta = payload.get("meta", {}) or {}
    managers = payload.get("managers", []) or []
    league = payload.get("league", {}) or {}
    highlights = payload.get("highlights", {}) or {}
    narrative = payload.get("narrative", "") or ""

    twin = (
        f'<div class="row2">{render_gw_standings(league)}'
        f'{render_weekly_wins(league)}</div>'
    )

    body = "".join([
        render_hero(meta),
        render_league_table(managers),
        render_race(managers),
        twin,
        render_highlights(highlights),
        render_captaincy_trends(league),
        render_manager_cards(managers),
        render_narrative(narrative),
        render_footer(meta),
    ])

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<style>
{CSS}
</style></head>
<body>
<div class="page">
{body}
</div>
</body></html>"""


# --------------------------------------------------------------------------- #
#  CSS
# --------------------------------------------------------------------------- #
CSS = f"""
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: {BG}; }}
body {{
  width: 1200px; margin: 0; background:
    radial-gradient(1200px 620px at 12% -8%, rgba(45,243,160,0.10), transparent 60%),
    radial-gradient(1100px 640px at 96% 4%, rgba(255,61,146,0.10), transparent 58%),
    {BG};
  color: {TEXT};
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  font-variant-numeric: tabular-nums;
}}
.page {{ width: 1200px; padding: 40px 40px 30px; }}

/* ------- Hero ------- */
.hero {{
  position: relative; padding: 34px 38px 30px; margin-bottom: 26px;
  border-radius: 22px; overflow: hidden;
  background:
    linear-gradient(135deg, rgba(45,243,160,0.14), rgba(139,109,255,0.10) 55%, rgba(255,61,146,0.14)),
    {PANEL};
  border: 1px solid {STROKE};
  box-shadow: 0 24px 60px rgba(0,0,0,0.45);
}}
.hero-top {{ display:flex; justify-content:space-between; align-items:center; }}
.hero-kicker {{ color:{ACCENT}; font-weight:800; letter-spacing:2.5px; font-size:13px; }}
.hero-title {{ font-size:56px; line-height:1.02; margin:16px 0 6px; font-weight:900;
  letter-spacing:-1px;
  background: linear-gradient(90deg, #ffffff, #cfe9ff 60%, {ACCENT});
  -webkit-background-clip:text; background-clip:text; color:transparent; }}
.hero-sub {{ color:{MUTED}; font-size:20px; font-weight:600; }}
.hero-stats {{ display:flex; gap:14px; margin-top:26px; }}
.hstat {{ flex:1; background: rgba(7,11,22,0.55); border:1px solid {STROKE};
  border-radius:14px; padding:14px 16px; }}
.hstat-v {{ font-size:30px; font-weight:900; letter-spacing:-0.5px; }}
.hstat-v.small {{ font-size:18px; font-weight:800; }}
.hstat-v.accent {{ color:{ACCENT}; }}
.hstat-l {{ color:{FAINT}; font-size:12px; margin-top:4px; letter-spacing:0.8px;
  text-transform:uppercase; font-weight:700; }}

.badge {{ font-size:13px; font-weight:800; padding:7px 14px; border-radius:999px;
  letter-spacing:1px; display:inline-flex; align-items:center; gap:8px; }}
.badge.final {{ background:rgba(45,243,160,0.16); color:{ACCENT};
  border:1px solid rgba(45,243,160,0.4); }}
.badge.live {{ background:rgba(255,61,146,0.16); color:{MAGENTA};
  border:1px solid rgba(255,61,146,0.4); }}
.badge.live .dot {{ width:9px; height:9px; border-radius:50%; background:{MAGENTA};
  box-shadow:0 0 0 4px rgba(255,61,146,0.25); }}

/* ------- Cards / sections ------- */
.card {{ background: {PANEL}; border:1px solid {STROKE}; border-radius:20px;
  padding:24px 26px; margin-bottom:22px; box-shadow: 0 14px 40px rgba(0,0,0,0.32); }}
.sec-head {{ display:flex; align-items:center; gap:12px; margin-bottom:18px; }}
.sec-head h2 {{ font-size:23px; margin:0; font-weight:850; letter-spacing:-0.3px; }}
.sec-ico {{ font-size:22px; }}
.sec-note {{ color:{FAINT}; font-size:13px; font-weight:500; margin-left:auto; }}
.row2 {{ display:flex; gap:22px; align-items:stretch; }}
.row2 .half {{ flex:1; margin-bottom:22px; }}
.chart-wrap {{ width:100%; }}
.chart-wrap.tight {{ padding-top:4px; }}

/* ------- League table ------- */
.lt-head, .lt-row {{
  display:grid; grid-template-columns: 58px 54px 1fr 168px 150px 92px;
  align-items:center; gap:8px;
}}
.lt-head {{ color:{FAINT}; font-size:11px; letter-spacing:1px; text-transform:uppercase;
  font-weight:800; padding:0 14px 10px; border-bottom:1px solid {STROKE}; }}
.lt-head > div:nth-child(4), .lt-head > div:nth-child(5) {{ }}
.lt-row {{ padding:12px 14px; border-radius:12px; margin-top:6px;
  background:{PANEL_2}; border:1px solid {STROKE_SOFT}; }}
.lt-row.leader {{ background:linear-gradient(90deg, rgba(255,210,63,0.14), rgba(45,243,160,0.06) 40%, {PANEL_2});
  border:1px solid rgba(255,210,63,0.4); }}
.lt-rank {{ display:flex; align-items:baseline; gap:5px; }}
.rk-num {{ font-size:22px; font-weight:900; }}
.rk-medal {{ font-size:16px; }}
.lt-name .nm {{ font-size:18px; font-weight:750; display:flex; align-items:center;
  gap:8px; flex-wrap:wrap; }}
.lt-name .tm {{ color:{FAINT}; font-size:13px; margin-top:2px; }}
.tot-v {{ font-size:20px; font-weight:850; font-family:ui-monospace,Menlo,monospace; }}
.tot-bar {{ height:5px; background:{STROKE_SOFT}; border-radius:3px; margin-top:5px;
  overflow:hidden; }}
.tot-bar span {{ display:block; height:100%; border-radius:3px;
  background:linear-gradient(90deg,{ACCENT_DK},{ACCENT}); }}
.gw-v {{ font-size:20px; font-weight:850; font-family:ui-monospace,Menlo,monospace;
  color:{ACCENT}; }}
.gw-bar {{ height:5px; background:{STROKE_SOFT}; border-radius:3px; margin-top:5px;
  overflow:hidden; }}
.gw-bar span {{ display:block; height:100%; border-radius:3px; background:{PURPLE}; }}
.lt-or {{ font-size:15px; color:{MUTED}; font-family:ui-monospace,Menlo,monospace;
  text-align:right; font-weight:600; }}

.mv {{ font-size:13px; font-weight:800; padding:3px 8px; border-radius:8px;
  white-space:nowrap; }}
.mv.up {{ color:{UP}; background:rgba(45,243,160,0.13); }}
.mv.down {{ color:{DOWN}; background:rgba(255,93,115,0.13); }}
.mv.flat {{ color:{FLAT}; background:rgba(93,111,146,0.13); }}

.tag {{ font-size:11px; font-weight:800; padding:2px 8px; border-radius:7px;
  letter-spacing:0.4px; }}
.tag.chip {{ background:rgba(139,109,255,0.18); color:{PURPLE};
  border:1px solid rgba(139,109,255,0.4); }}
.tag.hit {{ background:rgba(255,93,115,0.16); color:{DOWN};
  border:1px solid rgba(255,93,115,0.4); }}

/* ------- Highlights ------- */
.hl-grid {{ display:grid; grid-template-columns: repeat(5, 1fr); gap:14px; }}
.hl-grid.n1 {{ grid-template-columns: repeat(1, minmax(0,320px)); }}
.hl-grid.n2 {{ grid-template-columns: repeat(2, 1fr); }}
.hl-grid.n3 {{ grid-template-columns: repeat(3, 1fr); }}
.hl-grid.n4 {{ grid-template-columns: repeat(4, 1fr); }}
.hl-card {{ background:{PANEL_2}; border:1px solid {STROKE_SOFT}; border-radius:16px;
  padding:18px 16px; position:relative; overflow:hidden;
  border-top:3px solid var(--hlc); }}
.hl-emoji {{ font-size:30px; }}
.hl-kick {{ color:var(--hlc); font-weight:850; font-size:12px; letter-spacing:0.6px;
  text-transform:uppercase; margin-top:8px; }}
.hl-name {{ font-size:17px; font-weight:800; margin-top:6px; }}
.hl-big {{ font-size:15px; font-weight:700; color:{TEXT}; margin-top:8px; }}
.hl-sub {{ color:{FAINT}; font-size:12.5px; margin-top:4px; line-height:1.35; }}

/* ------- Manager cards ------- */
.mc-grid-wrap {{ display:grid; grid-template-columns: 1fr 1fr; gap:18px; }}
.mc {{ background:{PANEL_2}; border:1px solid {STROKE_SOFT}; border-radius:16px;
  padding:18px 18px 16px; border-left:4px solid var(--mc); }}
.mc-top {{ display:flex; align-items:center; gap:14px; }}
.mc-rank {{ width:44px; height:44px; border-radius:12px; flex:none;
  background:rgba(255,255,255,0.05); border:1px solid {STROKE};
  display:flex; align-items:center; justify-content:center;
  font-size:22px; font-weight:900; color:var(--mc); }}
.mc-id {{ flex:1; min-width:0; }}
.mc-name {{ font-size:19px; font-weight:800; white-space:nowrap; overflow:hidden;
  text-overflow:ellipsis; }}
.mc-team {{ color:{FAINT}; font-size:13px; margin-top:1px; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }}
.mc-gw {{ text-align:center; flex:none; }}
.mc-gw-v {{ font-size:26px; font-weight:900; color:var(--mc);
  font-family:ui-monospace,Menlo,monospace; line-height:1; }}
.mc-gw-l {{ font-size:10px; color:{FAINT}; letter-spacing:1px; margin-top:3px;
  font-weight:800; }}
.mc-tags {{ display:flex; flex-wrap:wrap; gap:7px; margin:14px 0 4px; align-items:center; }}
.form-badge {{ font-size:12px; font-weight:800; padding:4px 10px; border-radius:8px; }}
.form-badge b {{ font-weight:900; }}
.form-badge.hot {{ background:rgba(255,140,90,0.15); color:#ff8a5c;
  border:1px solid rgba(255,140,90,0.4); }}
.form-badge.cold {{ background:rgba(79,195,255,0.14); color:#6fd0ff;
  border:1px solid rgba(79,195,255,0.4); }}
.form-badge.steady {{ background:rgba(142,160,194,0.14); color:{MUTED};
  border:1px solid {STROKE}; }}
.mc-meta {{ font-size:12px; font-weight:700; color:{MUTED};
  background:rgba(255,255,255,0.04); padding:4px 10px; border-radius:8px;
  border:1px solid {STROKE_SOFT}; }}
.mc-chip {{ font-size:12px; font-weight:800; padding:4px 10px; border-radius:8px;
  background:rgba(139,109,255,0.18); color:{PURPLE};
  border:1px solid rgba(139,109,255,0.4); }}
.mc-hit {{ font-size:12px; font-weight:800; padding:4px 10px; border-radius:8px;
  background:rgba(255,93,115,0.16); color:{DOWN};
  border:1px solid rgba(255,93,115,0.4); }}
.mc-mid {{ display:flex; gap:16px; margin:14px 0 6px; align-items:center; }}
.mc-spark {{ flex:1; min-width:0; }}
.mc-spark-hd {{ font-size:10px; color:{FAINT}; letter-spacing:1px; font-weight:800;
  text-transform:uppercase; margin-bottom:4px; }}
.mc-bw {{ display:flex; justify-content:space-between; margin-top:4px; font-size:12px;
  font-weight:700; }}
.bw-good {{ color:{ACCENT}; }}
.bw-bad {{ color:{DOWN}; }}
.mc-donut {{ flex:none; text-align:center; }}
.mc-donut-key {{ margin-top:2px; }}
.mc-donut-key span {{ display:flex; align-items:center; gap:5px; font-size:11px;
  color:{MUTED}; font-weight:600; justify-content:flex-start; }}
.mc-donut-key i {{ width:9px; height:9px; border-radius:3px; display:inline-block; }}
.mc-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:6px 18px; margin-top:12px;
  border-top:1px solid {STROKE_SOFT}; padding-top:12px; }}
.kv {{ display:flex; justify-content:space-between; align-items:baseline; gap:8px;
  font-size:13.5px; padding:2px 0; }}
.kv .k {{ color:{FAINT}; font-weight:600; white-space:nowrap; }}
.kv .v {{ font-weight:750; text-align:right; }}
.kv .v.cap-good {{ color:{ACCENT}; }}
.kv .v.cap-bad {{ color:{DOWN}; }}
.mc-chips {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-top:12px;
  border-top:1px solid {STROKE_SOFT}; padding-top:12px; }}
.cu-lbl {{ font-size:10px; font-weight:800; color:{FAINT}; letter-spacing:1px; }}
.cu {{ font-size:11px; font-weight:800; color:{GOLD}; background:rgba(255,210,63,0.12);
  border:1px solid rgba(255,210,63,0.3); border-radius:7px; padding:3px 8px;
  display:inline-flex; align-items:center; gap:4px; }}
.cu i {{ font-style:normal; color:{FAINT}; font-weight:700; }}

/* ------- League Intel (captaincy / power rankings / bench / rivalries) ------- */
.extra-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
.extra-panel {{ background:{PANEL_2}; border:1px solid {STROKE_SOFT}; border-radius:12px;
  padding:16px; }}
.extra-panel-wide {{ grid-column:span 2; }}
.ep-head {{ font-size:13px; font-weight:800; color:{TEXT}; letter-spacing:0.5px;
  margin-bottom:12px; }}
.ep-note {{ font-size:11px; color:{FAINT}; font-weight:600; margin-left:6px; }}
/* Captaincy bar */
.ct-row {{ display:flex; align-items:center; gap:10px; margin-bottom:8px; }}
.ct-name {{ font-size:13px; font-weight:700; color:{TEXT}; min-width:90px; }}
.ct-bar-wrap {{ flex:1; background:rgba(255,255,255,0.06); border-radius:4px; height:10px;
  overflow:hidden; }}
.ct-bar {{ height:100%; background:linear-gradient(90deg,{ACCENT},{ACCENT_DK});
  border-radius:4px; transition:width 0.4s; }}
.ct-meta {{ font-size:11px; color:{MUTED}; white-space:nowrap; min-width:100px;
  text-align:right; }}
/* Power rankings */
.pr-row {{ display:flex; align-items:center; gap:10px; padding:5px 0;
  border-bottom:1px solid {STROKE_SOFT}; }}
.pr-row:last-child {{ border-bottom:none; }}
.pr-rank {{ font-size:12px; font-weight:800; color:{FAINT}; min-width:24px; }}
.pr-name {{ flex:1; font-size:13px; font-weight:700; color:{TEXT}; }}
.pr-score {{ font-size:13px; font-weight:800; color:{ACCENT}; min-width:48px;
  text-align:right; }}
.pr-up {{ color:{ACCENT}; font-size:12px; font-weight:800; min-width:28px;
  text-align:right; }}
.pr-dn {{ color:{DOWN}; font-size:12px; font-weight:800; min-width:28px;
  text-align:right; }}
.pr-flat {{ color:{FAINT}; font-size:12px; min-width:28px; text-align:right; }}
/* Rivalries */
.rv-grid {{ display:flex; flex-direction:column; gap:8px; }}
.rv-item {{ display:flex; align-items:center; gap:12px; padding:6px 0;
  border-bottom:1px solid {STROKE_SOFT}; }}
.rv-item:last-child {{ border-bottom:none; }}
.rv-a {{ font-size:13px; font-weight:700; color:{TEXT}; flex:1; }}
.rv-gap {{ font-size:12px; font-weight:800; color:{GOLD}; background:rgba(255,210,63,0.12);
  border:1px solid rgba(255,210,63,0.3); border-radius:6px; padding:2px 8px;
  white-space:nowrap; }}
.rv-b {{ font-size:13px; font-weight:600; color:{MUTED}; flex:1; text-align:right; }}

/* ------- Pundit ------- */
.pundit {{ background:
  linear-gradient(135deg, rgba(139,109,255,0.10), rgba(45,243,160,0.05)), {PANEL}; }}
.pundit-body {{ position:relative; padding-left:8px; }}
.quote-mark {{ position:absolute; top:-32px; left:-4px; font-size:90px; color:{PURPLE};
  opacity:0.28; font-family:Georgia,serif; line-height:1; }}
.pundit-body p {{ font-size:16.5px; line-height:1.62; color:#dfe7f6; margin:0 0 12px;
  font-weight:450; }}
.pundit-body p:first-of-type {{ font-size:18px; font-weight:600; color:{TEXT}; }}

/* ------- Footer ------- */
.footer {{ display:flex; justify-content:space-between; align-items:center;
  color:{FAINT}; font-size:13px; padding:18px 8px 0; border-top:1px solid {STROKE_SOFT};
  margin-top:6px; }}
.foot-mono {{ font-family:ui-monospace,Menlo,monospace; }}
"""
