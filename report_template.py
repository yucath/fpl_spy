"""
report_template.py — authentic broadsheet newspaper HTML report for FPL mini-league.
Entry point: render_report_html(payload: dict) -> str
"""

from __future__ import annotations

import base64
import html
import math
import os
import re
from datetime import datetime
from typing import List

# ── Design tokens ─────────────────────────────────────────────────────────── #
BG       = "#f7f4ef"   # warm newsprint
PAPER    = "#f0ede6"   # slightly darker panels
INK      = "#111111"
INK2     = "#3a3a3a"
MUTED    = "#666666"
RULE     = "#c0c0c0"   # column rules / table lines
HEADLINE = "#8b0000"   # crimson
ACCENT   = "#b8860b"   # gold
UP       = "#1a5c1a"
DOWN     = "#8b0000"
TALT     = "#edeae3"   # table alternate row
WHITE    = "#ffffff"

SERIES_COLORS = [
    "#8b0000","#1a5c1a","#1a3a8b","#7b4f00","#5a0072",
    "#005f5f","#7a1a00","#004a24","#003d7a","#6b3d00",
    "#4a006b","#003838","#5c1a00","#1a4a00","#00286b",
]


# ── Helpers ───────────────────────────────────────────────────────────────── #
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


def _initials(name: str) -> str:
    parts = name.split()
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def _image_data_uri(path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif",
            "webp": "webp"}.get(ext, "jpeg")
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:image/{mime};base64,{data}"


def _extract_pull_quote(text: str) -> str:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    best = ""
    for s in sentences:
        s = s.strip()
        if 60 <= len(s) <= 180 and not s.startswith("GW") and not s.startswith("Next week"):
            best = s
            break
    if not best and sentences:
        candidates = [s for s in sentences if 40 <= len(s) <= 200]
        best = candidates[len(candidates) // 2] if candidates else (sentences[0] if sentences else "")
    return best[:200] if best else ""


def _parse_narrative(narrative: str):
    """Parse AI narrative into (headline, story_paras, verdicts, teaser).

    Returns (headline, paras, verdicts, teaser) where:
      - paras: list of story paragraph strings
      - verdicts: list of (name, text) tuples for per-manager verdicts
      - teaser: closing teaser line
    """
    import re as _re
    lines = [l.strip() for l in narrative.strip().split("\n") if l.strip()]
    if not lines:
        return "", [], [], ""

    # Section markers
    VERDICT_MARKERS = {"MANAGER VERDICTS", "VERDICTS", "MANAGER VERDICT", "PLAYER VERDICTS"}
    TEASER_MARKERS = {"NEXT WEEK TEASER", "NEXT WEEK", "TEASER", "SUSPENSE CLOSER", "CLOSING"}

    raw_head = lines[0]
    if ":" in raw_head[:10]:
        raw_head = raw_head.split(":", 1)[1].strip()
    raw_head = raw_head.rstrip("!")

    section = "story"
    story_paras, verdicts, teaser_lines = [], [], []

    for line in lines[1:]:
        upper = line.upper().strip(":-–—.")
        if upper in VERDICT_MARKERS or upper.startswith("MANAGER VERDICT"):
            section = "verdicts"
            continue
        if upper in TEASER_MARKERS or upper.startswith("NEXT WEEK") or upper.startswith("SUSPENSE"):
            section = "teaser"
            continue

        if section == "story":
            story_paras.append(line)
        elif section == "verdicts":
            # Match "Name: verdict" or "Name — verdict"
            m = _re.match(r'^([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)[\s]*[:\-–—]\s*(.+)', line)
            if m:
                verdicts.append((m.group(1), m.group(2)))
            else:
                # Could be a verdict without the Name: prefix — treat as story paragraph
                story_paras.append(line)
        elif section == "teaser":
            teaser_lines.append(line)

    # If no explicit verdict section found, check for name-prefixed lines in story_paras
    if not verdicts:
        remaining_story, found_verdicts = [], []
        import re as _re2
        for p in story_paras:
            m = _re2.match(r'^([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)[\s]*[:\-–—]\s*(.+)', p)
            if m and len(p) < 200:
                found_verdicts.append((m.group(1), m.group(2)))
            else:
                remaining_story.append(p)
        if len(found_verdicts) >= 3:
            story_paras = remaining_story
            verdicts = found_verdicts

    teaser = " ".join(teaser_lines).strip()
    return raw_head, story_paras, verdicts, teaser


# ── SVG charts ────────────────────────────────────────────────────────────── #
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


def race_chart(managers: List[dict], w: int = 1100, h: int = 340, mode: str = "rank") -> str:
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

    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="background:{BG}">']
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


# ── Section builders ──────────────────────────────────────────────────────── #

def _edition_bar(meta: dict) -> str:
    gw = meta.get("gameweek", "?")
    generated = meta.get("generated_at", "")
    try:
        dt = datetime.strptime(generated, "%Y-%m-%d %H:%M")
        date_str = dt.strftime("%A, %d %B %Y")
    except Exception:
        date_str = generated
    return (
        f'<div class="edition-bar">Vol.&nbsp;{esc(str(gw))},&nbsp;No.&nbsp;1'
        f'&nbsp;&nbsp;|&nbsp;&nbsp;{esc(date_str)}'
        f'&nbsp;&nbsp;|&nbsp;&nbsp;Est.&nbsp;2024'
        f'&nbsp;&nbsp;|&nbsp;&nbsp;FREE</div>'
    )


def _masthead(meta: dict) -> str:
    league = esc(meta.get("league_name", "FPL Mini-League"))
    gw = esc(str(meta.get("gameweek", "")))
    generated = meta.get("generated_at", "")
    try:
        dt = datetime.strptime(generated, "%Y-%m-%d %H:%M")
        date_str = dt.strftime("%A, %d %B %Y").upper()
    except Exception:
        date_str = generated.upper()
    is_final = bool(meta.get("is_final"))
    status = "FINAL EDITION" if is_final else "LIVE UPDATE"
    season = esc(meta.get("season_label") or "2026/27")
    n_mgr = esc(str(meta.get("num_managers", "")))
    gw_avg = fnum(meta.get("gw_average"), 1)
    return f"""
<header class="masthead">
  <div class="mast-rule-thick"></div>
  <div class="mast-inner">
    <div class="mast-side mast-left">
      <div>FANTASY PREMIER LEAGUE</div>
      <div>MINI-LEAGUE REPORT</div>
      <div class="mast-season">SEASON {season}</div>
    </div>
    <div class="mast-center">
      <div class="mast-league">{league}</div>
      <div class="mast-gazette">THE GAZETTE</div>
    </div>
    <div class="mast-side mast-right">
      <div>{date_str}</div>
      <div class="mast-status">GW {gw} &nbsp;&middot;&nbsp; {status}</div>
      <div>{n_mgr} managers &nbsp;&middot;&nbsp; avg {gw_avg} pts</div>
    </div>
  </div>
  <div class="mast-rule-thick"></div>
  <div class="mast-rule-thin"></div>
</header>"""


def _section_nav(meta: dict) -> str:
    gw = meta.get("gameweek", "?")
    is_final = bool(meta.get("is_final"))
    status_cls = "nav-final" if is_final else "nav-live"
    status_txt = "FINAL" if is_final else "LIVE"
    return f"""
<nav class="section-nav">
  <span class="section-pill">SPORT</span>
  <span class="nav-sep">&middot;</span>
  <span class="nav-item">FPL ANALYSIS</span>
  <span class="nav-sep">&middot;</span>
  <span class="nav-item">GAMEWEEK {esc(str(gw))}</span>
  <span class="nav-sep">&middot;</span>
  <span class="{status_cls}">{status_txt}</span>
</nav>"""


def _hero(payload: dict, managers: List[dict], manager_photos: dict = None) -> str:
    path = payload.get("hero_image_path")
    leader = managers[0] if managers else {}
    leader_name = leader.get("name", "GW Winner")
    if path and os.path.isfile(path):
        try:
            uri = _image_data_uri(path)
            caption = (
                f"Gameweek {payload.get('meta', {}).get('gameweek', '')} winner: "
                f"{esc(leader_name)} — {fnum(leader.get('gw_points'))} points"
            )
            return f"""
<div class="hero-img-wrap">
  <img class="hero-img" src="{uri}" alt="GW Hero">
  <div class="img-caption">{caption}</div>
</div>"""
        except Exception:
            pass
    name = esc(leader_name)
    pts = fnum(leader.get("gw_points"))
    gw = esc(str(payload.get("meta", {}).get("gameweek", "")))

    # Try to show manager's profile photo
    photo_html = ""
    photo_path = (manager_photos or {}).get(leader_name)
    if photo_path and os.path.isfile(photo_path):
        try:
            uri = _image_data_uri(photo_path)
            photo_html = f'<img class="hp-photo" src="{uri}" alt="{esc(leader_name)}">'
        except Exception:
            pass
    if not photo_html:
        # Initials fallback
        initials = "".join(w[0].upper() for w in leader_name.split()[:2])
        photo_html = f'<div class="hp-initials">{initials}</div>'

    return f"""
<div class="hero-placeholder">
  {photo_html}
  <div class="hp-score">{pts}</div>
  <div style="flex:1">
    <div class="hp-week">Gameweek {gw} Winner</div>
    <div class="hp-name">{name}</div>
    <div class="hp-pts">{pts} points this week</div>
  </div>
</div>"""


def _lead_article(narrative: str, managers: List[dict], manager_photos: dict = None) -> str:
    headline, paras, verdicts, teaser = _parse_narrative(narrative)
    if not headline:
        headline = (managers[0].get("name", "This Week's Champion") + " Leads the Pack") if managers else "Weekly Report"
    leader = managers[0] if managers else {}
    last_gw = ""
    gws = (leader.get("season") or {}).get("gws") or []
    if gws:
        last_gw = str(gws[-1])
    deck = (
        f"{esc(leader.get('name',''))} storms to {fnum(leader.get('gw_points'))} points"
        + (f" in Gameweek {last_gw}" if last_gw else "")
        + ", delivering the highest score as drama unfolds across the mini-league."
    )

    full_body = " ".join(paras)
    pull = _extract_pull_quote(full_body)
    mid = max(1, len(paras) // 2)

    parts = []
    for i, p in enumerate(paras):
        if i == 0:
            first_char = esc(p[0]) if p else ""
            rest = esc(p[1:]) if len(p) > 1 else ""
            parts.append(
                f'<p class="article-para first-para">'
                f'<span class="drop">{first_char}</span>{rest}</p>'
            )
        else:
            if i == mid and pull:
                parts.append(f"""
<aside class="pull-quote">
  <div class="pq-open">&#8220;</div>
  <p class="pq-text">{esc(pull)}</p>
  <div class="pq-close">&#8221;</div>
</aside>""")
            parts.append(f'<p class="article-para">{esc(p)}</p>')

    # Manager verdicts grid — match name to full manager name for photo lookup
    name_map = {m.get("name", "").split()[0]: m.get("name", "") for m in managers}
    verdict_html = ""
    if verdicts:
        verdict_items = []
        for first_name, text in verdicts:
            full_name = name_map.get(first_name, first_name)
            photo_path = (manager_photos or {}).get(full_name)
            av_html = ""
            if photo_path and os.path.isfile(photo_path):
                try:
                    uri = _image_data_uri(photo_path)
                    av_html = f'<img class="vd-avatar" src="{uri}" alt="{esc(first_name)}">'
                except Exception:
                    pass
            if not av_html:
                initials = "".join(w[0].upper() for w in full_name.split()[:2])
                av_html = f'<span class="vd-initials">{initials}</span>'
            verdict_items.append(
                f'<div class="verdict-item">'
                f'<span class="vd-av-wrap">{av_html}</span>'
                f'<span class="verdict-name">{esc(first_name)}</span>'
                f'<span class="verdict-text">{esc(text)}</span>'
                f'</div>'
            )
        verdict_html = f"""
<div class="verdicts-section">
  <div class="verdicts-label">MANAGER VERDICTS</div>
  <div class="verdicts-grid">{''.join(verdict_items)}</div>
</div>"""

    # Teaser
    teaser_html = ""
    if teaser:
        teaser_html = f'<p class="article-teaser">{esc(teaser)}</p>'

    return f"""
<div class="lead-article">
  <span class="section-flag">SPORT</span>
  <h1 class="headline">{esc(headline)}</h1>
  <p class="deck">{deck}</p>
  <div class="byline">By the FPL Analytics Desk <span class="byline-sep">|</span> Published this week</div>
  <div class="byline-rule"></div>
  <div class="article-body">
    {''.join(parts)}
  </div>
  {verdict_html}
  {teaser_html}
</div>"""


def _league_table(managers: List[dict], manager_photos: dict = None) -> str:
    rows = []
    for i, m in enumerate(managers):
        rank = m.get("rank", 0)
        leader = rank == 1
        mv = (m.get("prev_rank") or rank) - rank
        if mv > 0:
            mv_html = '<span class="mv-up">&#9650;</span>'
        elif mv < 0:
            mv_html = '<span class="mv-dn">&#9660;</span>'
        else:
            mv_html = '<span class="mv-flat">&mdash;</span>'
        medal = {1: "&#127949;", 2: "&#127950;", 3: "&#127951;"}.get(rank, str(rank))
        chip = m.get("chip")
        chip_tag = (f' <span class="chip-tag">{esc(chip[:2].upper())}</span>') if chip else ""
        hit = m.get("gw_hit", 0)
        hit_tag = f' <span class="hit-tag">-{hit}</span>' if hit else ""
        row_cls = "lt-leader" if leader else ("lt-alt" if i % 2 == 1 else "")
        name = m.get("name", "")
        # Small avatar
        photo_path = (manager_photos or {}).get(name)
        if photo_path and os.path.isfile(photo_path):
            try:
                uri = _image_data_uri(photo_path)
                avatar_html = f'<img class="lt-avatar" src="{uri}" alt="{esc(name)}">'
            except Exception:
                initials = "".join(w[0].upper() for w in name.split()[:2])
                avatar_html = f'<span class="lt-initials">{initials}</span>'
        else:
            initials = "".join(w[0].upper() for w in name.split()[:2])
            avatar_html = f'<span class="lt-initials">{initials}</span>'
        rows.append(f"""
    <tr class="{row_cls}">
      <td class="lt-rk">{medal}</td>
      <td class="lt-mv">{mv_html}</td>
      <td class="lt-nm"><span class="lt-av-wrap">{avatar_html}</span>{esc(name)}{chip_tag}{hit_tag}</td>
      <td class="lt-num">{fnum(m.get('total_points'))}</td>
      <td class="lt-gw">{fnum(m.get('gw_points'))}</td>
    </tr>""")
    return f"""
<div class="sb-head">LEAGUE TABLE</div>
<table class="lt">
  <thead><tr>
    <th class="lt-rk">#</th><th></th><th>Manager</th>
    <th class="lt-num">Total</th><th class="lt-gw">GW</th>
  </tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>"""


def _captain_picks(managers: List[dict], manager_photos: dict) -> str:
    rows = []
    for m in managers[:10]:
        name = m.get("name", "")
        cap = m.get("captain") or "—"
        cap_pts = m.get("captain_points")
        pts_str = f"{cap_pts}" if cap_pts is not None else "?"
        chip = m.get("chip")
        chip_tag = f' <span class="chip-tag">{esc(chip[:2].upper())}</span>' if chip else ""
        good = (cap_pts or 0) >= 10
        photo_path = (manager_photos or {}).get(name)
        if photo_path and os.path.isfile(photo_path):
            try:
                uri = _image_data_uri(photo_path)
                avatar = f'<img class="mgr-avatar" src="{uri}" alt="{esc(name)}">'
            except Exception:
                avatar = f'<div class="mgr-initial">{esc(_initials(name))}</div>'
        else:
            avatar = f'<div class="mgr-initial">{esc(_initials(name))}</div>'
        rows.append(f"""
  <div class="cap-row">
    {avatar}
    <div class="cap-info">
      <div class="cap-mgr">{esc(name)}{chip_tag}</div>
      <div class="cap-player">&#169; {esc(cap)}</div>
    </div>
    <div class="cap-pts {'cap-good' if good else 'cap-meh'}">{pts_str}pts</div>
  </div>""")
    return f"""
<div class="sb-head">CAPTAIN PICKS</div>
<div class="cap-list">{''.join(rows)}</div>"""


def _sidebar(managers: List[dict], manager_photos: dict, league: dict = None) -> str:
    return f"""
<aside class="sidebar">
  <div class="sb-section">{_league_table(managers, manager_photos)}</div>
  <div class="sb-section">{_captain_picks(managers, manager_photos)}</div>
  {_sidebar_extras(managers, league or {})}
</aside>"""


def _divider(label: str = "") -> str:
    if label:
        return (
            f'<div class="section-divider">'
            f'<span class="div-rule"></span>'
            f'<span class="div-label">{esc(label)}</span>'
            f'<span class="div-rule"></span>'
            f'</div>'
        )
    return '<div class="section-divider-plain"></div>'


def _stats_strip(managers: List[dict], league: dict) -> str:
    gw_top = sorted(managers, key=lambda m: m.get("gw_points", 0) or 0, reverse=True)
    gw_winner = gw_top[0] if gw_top else {}
    riser = league.get("biggest_riser") or {}
    faller = league.get("biggest_faller") or {}
    bench_lb = (league.get("bench_leaderboard") or [])
    bench_top = bench_lb[0] if bench_lb else {}
    cap_best = max(managers, key=lambda m: m.get("captain_points", 0) or 0, default={})

    def box(emoji, kicker, name, value, sub):
        return (
            f'<div class="stat-box">'
            f'<div class="stat-emoji">{emoji}</div>'
            f'<div class="stat-kicker">{esc(kicker)}</div>'
            f'<div class="stat-name">{esc(name)}</div>'
            f'<div class="stat-value">{esc(value)}</div>'
            f'<div class="stat-sub">{esc(sub)}</div>'
            f'</div>'
        )

    return f"""
<section class="stats-section">
  {_divider("STATS DESK")}
  <div class="stats-grid">
    {box("&#9889;", "GW Top Scorer", gw_winner.get('name','—'), f'{fnum(gw_winner.get("gw_points"))} pts', f'Capt: {gw_winner.get("captain","—")}')}
    {box("&#128200;", "Biggest Riser", riser.get('name','—'), f'+{riser.get("change",0)} places', 'moved up this week')}
    {box("&#127919;", "Best Captain", cap_best.get('name','—'), f'{fnum(cap_best.get("captain_points","—"))} pts', f'Capt: {cap_best.get("captain","—")}')}
    {box("&#129681;", "Bench Pain King", bench_top.get('name','—'), f'{fnum(bench_top.get("season_bench","—"))} pts', 'season bench points left')}
  </div>
</section>"""


def _manager_dossiers(managers: List[dict], manager_photos: dict) -> str:
    cards = []
    for idx, m in enumerate(managers):
        color = SERIES_COLORS[idx % len(SERIES_COLORS)]
        s = m.get("season") or {}
        spark = sparkline(s.get("net_points") or [], w=160, h=36, color=color)
        rank = m.get("rank", 0)
        gw_pts = m.get("gw_points", 0)
        cap = m.get("captain") or "—"
        cap_pts = m.get("captain_points", 0) or 0
        cap_cls = "cap-good" if cap_pts >= 10 else ("cap-meh" if cap_pts >= 6 else "cap-bad")
        chip = m.get("chip")
        chip_html = f'<span class="chip-tag">{esc(chip)}</span>' if chip else ""
        hit = m.get("gw_hit", 0)
        hit_html = f'<span class="hit-tag">-{hit}pt</span>' if hit else ""
        or_rank = compact_rank(m.get("overall_rank"))
        bench = m.get("bench_points") or 0
        archetype = m.get("archetype") or ""
        arch_html = f'<div class="mc-arch">{esc(archetype)}</div>' if archetype else ""
        name = m.get("name", "")
        photo_path = (manager_photos or {}).get(name)
        if photo_path and os.path.isfile(photo_path):
            try:
                uri = _image_data_uri(photo_path)
                avatar = f'<img class="mc-avatar" src="{uri}" alt="{esc(name)}">'
            except Exception:
                avatar = f'<div class="mc-initial" style="background:{color}">{esc(_initials(name))}</div>'
        else:
            avatar = f'<div class="mc-initial" style="background:{color}">{esc(_initials(name))}</div>'

        tags = (chip_html + (" " if chip_html and hit_html else "") + hit_html) or "&nbsp;"
        cards.append(f"""
  <div class="mc" style="border-top:3px solid {color}">
    <div class="mc-header">
      {avatar}
      <div class="mc-id">
        <div class="mc-rank" style="color:{color}">#{rank}</div>
        <div class="mc-name">{esc(name)}</div>
        <div class="mc-team">{esc(m.get('team_name',''))}</div>
      </div>
      <div class="mc-gwv" style="color:{color}">{fnum(gw_pts)}</div>
    </div>
    {arch_html}
    <div class="mc-tags">{tags}</div>
    <div class="mc-spark">{spark}<div class="spark-cap">GW points trend</div></div>
    <table class="mc-stats">
      <tr><td class="mcs-k">Captain</td><td class="mcs-v {cap_cls}">&#169;&nbsp;{esc(cap)}&nbsp;&middot;&nbsp;{cap_pts}pts</td></tr>
      <tr class="mc-alt"><td class="mcs-k">Bench</td><td class="mcs-v">{fnum(bench)} pts</td></tr>
      <tr><td class="mcs-k">Season</td><td class="mcs-v">{fnum(m.get('total_points'))} pts</td></tr>
      <tr class="mc-alt"><td class="mcs-k">Global</td><td class="mcs-v">{or_rank}</td></tr>
    </table>
  </div>""")

    return f"""
<section class="dossier-section">
  {_divider("THIS WEEK'S SQUADS")}
  <div class="mc-grid">{''.join(cards)}</div>
</section>"""


def _race_section(managers: List[dict]) -> str:
    svg = race_chart(managers, mode="rank")
    if not svg:
        return ""
    return f"""
<section class="race-section">
  {_divider("THE SEASON RACE")}
  <div class="chart-wrap">{svg}</div>
  <div class="img-caption">Mini-league position after each gameweek &middot; 1st place at top</div>
</section>"""


def _sidebar_extras(managers: List[dict], league: dict) -> str:
    """Extra sidebar blocks: weekly wins record + GW form table."""
    sections = []

    # Weekly wins table
    weekly_wins = (league.get("weekly_wins") or [])
    winners = [w for w in weekly_wins if (w.get("wins") or 0) >= 1]
    if winners:
        rows = ""
        for w in sorted(winners, key=lambda x: -x.get("wins", 0))[:8]:
            weeks_str = ", ".join(f"GW{n}" for n in (w.get("weeks") or []))
            rows += (
                f'<tr><td class="lt-nm">{esc(w["name"])}</td>'
                f'<td class="lt-num" style="color:{HEADLINE}">{int(w["wins"])}</td>'
                f'<td style="font-size:10px;color:{MUTED};text-align:left;padding-left:4px">{esc(weeks_str)}</td></tr>'
            )
        sections.append(f"""
<div class="sb-head">WEEKLY WINS</div>
<table class="lt">
  <thead><tr><th style="text-align:left">Manager</th><th class="lt-num">W</th><th></th></tr></thead>
  <tbody>{rows}</tbody>
</table>""")

    # GW form — last 3 GWs, show pts per GW for each manager
    form_rows = ""
    for m in managers[:10]:
        pts_series = (m.get("season") or {}).get("net_points") or []
        gw_series  = (m.get("season") or {}).get("gws") or []
        recent = pts_series[-3:] if len(pts_series) >= 3 else pts_series
        if not recent:
            continue
        dots = ""
        for p in recent:
            col = HEADLINE if p >= 80 else ("#1a5c1a" if p >= 60 else MUTED)
            dots += f'<span style="color:{col};font-weight:700;margin-right:3px">{int(p)}</span>'
        form_rows += (
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:3px 0;border-bottom:1px solid {RULE};font-size:11.5px">'
            f'<span style="color:{INK};font-weight:600">{esc(m.get("name","").split()[0])}</span>'
            f'<span style="font-family:\'Courier New\',monospace">{dots}</span>'
            f'</div>'
        )
    if form_rows:
        sections.append(f"""
<div class="sb-head">RECENT FORM <span style="font-weight:400;font-size:9px">(last 3 GWs)</span></div>
{form_rows}""")

    # Bench leaderboard — top 5 bench wasters
    bench_lb = (league.get("bench_leaderboard") or [])[:5]
    if bench_lb:
        b_rows = ""
        for i, b in enumerate(bench_lb):
            alt = f' style="background:{TALT}"' if i % 2 == 1 else ""
            b_rows += (
                f'<tr{alt}><td class="lt-nm">{esc(b["name"])}</td>'
                f'<td class="lt-num" style="color:{HEADLINE}">{fnum(b.get("season_bench"))}</td>'
                f'<td class="lt-gw">{fnum(b.get("gw_bench"))}</td></tr>'
            )
        sections.append(f"""
<div class="sb-head">BENCH POINTS WASTED</div>
<table class="lt">
  <thead><tr><th style="text-align:left">Manager</th><th class="lt-num">Total</th><th class="lt-gw">GW</th></tr></thead>
  <tbody>{b_rows}</tbody>
</table>""")

    if not sections:
        return ""
    return "\n".join(f'<div class="sb-section">{s}</div>' for s in sections)


def _intel(league: dict) -> str:
    power = (league.get("power_rankings") or [])[:8]
    cap_trends = (league.get("captaincy_trends") or [])[:8]
    rivalries = (league.get("rivalries") or [])[:6]

    pw_rows = ""
    for i, p in enumerate(power):
        delta = p.get("delta", 0)
        if delta >= 2:
            arrow = f'<span class="mv-up">&#9650;{delta}</span>'
        elif delta <= -2:
            arrow = f'<span class="mv-dn">&#9660;{abs(delta)}</span>'
        else:
            arrow = '<span class="mv-flat">&mdash;</span>'
        alt = ' class="mc-alt"' if i % 2 == 1 else ""
        pw_rows += (
            f'<tr{alt}><td class="intel-rank">#{esc(str(p.get("power_rank","")))}</td>'
            f'<td class="intel-name">{esc(p.get("name",""))}</td>'
            f'<td class="intel-score">{esc(str(p.get("score","")))}</td>'
            f'<td style="text-align:center">{arrow}</td></tr>'
        )

    cap_rows = ""
    max_cnt = cap_trends[0]["count"] if cap_trends else 1
    for t in cap_trends:
        pct = t["count"] / max_cnt * 100
        pts = f'{t["gw_pts"]}pts' if t.get("gw_pts") is not None else "—"
        cap_rows += (
            f'<div class="ct-row">'
            f'<div class="ct-name">{esc(t.get("player",""))}</div>'
            f'<div class="ct-bar-wrap"><div class="ct-bar" style="width:{pct:.0f}%"></div></div>'
            f'<div class="ct-meta">{esc(str(t.get("pct","")))}% &middot; {esc(pts)}</div>'
            f'</div>'
        )

    rv_rows = ""
    for r in rivalries:
        rv_rows += (
            f'<div class="rv-row">'
            f'<span class="rv-a">{esc(r.get("leader",""))}</span>'
            f'<span class="rv-gap">+{esc(str(r.get("gap","")))} pts</span>'
            f'<span class="rv-b">{esc(r.get("chaser",""))}</span>'
            f'</div>'
        )

    return f"""
<section class="intel-section">
  {_divider("LEAGUE INTEL")}
  <div class="intel-grid">
    <div class="intel-panel">
      <div class="intel-head">POWER RANKINGS <span class="intel-note">form-weighted</span></div>
      <table class="intel-table">
        <thead><tr><th>#</th><th>Manager</th><th>Score</th><th></th></tr></thead>
        <tbody>{pw_rows}</tbody>
      </table>
    </div>
    <div class="intel-panel">
      <div class="intel-head">CAPTAINCY TRENDS</div>
      <div class="ct-list">{cap_rows}</div>
    </div>
    <div class="intel-panel">
      <div class="intel-head">CLOSEST RIVALRIES</div>
      <div class="rv-list">{rv_rows}</div>
    </div>
  </div>
</section>"""


def _talking_points(payload: dict, managers: List[dict]) -> str:
    """Newspaper-style callout boxes for the most interesting GW stories."""
    highlights = payload.get("highlights") or {}
    league = payload.get("league") or {}
    meta = payload.get("meta") or {}
    gw = meta.get("gameweek", "?")
    items = []

    # GW winner / top scorer
    if managers:
        top = managers[0]
        items.append(("&#127942;", f"GW{gw} WINNER",
            f"<b>{esc(top.get('name',''))}</b> scored <b>{fnum(top.get('gw_points'))}</b> pts — "
            + (f"Bench Boost chip used" if top.get('chip') == 'Bench Boost' else
               f"captained {esc(top.get('captain','?'))} for {fnum(top.get('captain_points'))} pts")))

    # Biggest climber
    cb = highlights.get("comeback")
    if cb:
        items.append(("&#128200;", "BIGGEST CLIMBER",
            f"<b>{esc(cb['manager'])}</b> rocketed <b>+{cb['change']}</b> places "
            f"(#{cb['prev_rank']} → #{cb['current_rank']})"))

    # Biggest faller
    ch = highlights.get("choke")
    if ch:
        items.append(("&#128201;", "BIGGEST FALLER",
            f"<b>{esc(ch['manager'])}</b> dropped <b>{abs(ch['change'])}</b> places "
            f"(#{ch['prev_rank']} → #{ch['current_rank']})"))

    # Captain disaster
    cf = highlights.get("captain_fail")
    if cf and (cf.get("points") or 0) == 0:
        items.append(("&#128128;", "CAPTAIN FAIL",
            f"<b>{esc(cf['manager'])}</b> captained <b>{esc(cf['captain'])}</b> — "
            f"who blanked with <b>{fnum(cf.get('points',0))} pts</b>. Ouch."))
    elif cf:
        items.append(("&#128128;", "CAPTAIN MISS",
            f"<b>{esc(cf['manager'])}</b> chose <b>{esc(cf['captain'])}</b> for just "
            f"<b>{fnum(cf.get('points',0))} pts</b>"))

    # Bench hero
    bh = highlights.get("bench_hero")
    if bh and (bh.get("points") or 0) >= 8:
        items.append(("&#129335;", "BENCH CRIME",
            f"<b>{esc(bh['manager'])}</b> left <b>{esc(bh['player'])}</b> on the bench — "
            f"who scored <b>{fnum(bh.get('points'))} pts</b>. That one hurts."))

    # Differential hero
    dh = highlights.get("differential_hero")
    if dh and (dh.get("points") or 0) >= 10:
        own_pct = dh.get("ownership_pct") or 0
        items.append(("&#128161;", "DIFFERENTIAL KING",
            f"<b>{esc(dh['manager'])}</b> played <b>{esc(dh['player'])}</b> "
            f"({own_pct:.0f}% owned) for <b>{fnum(dh.get('points'))} pts</b>"))

    # Bench leaderboard top entry
    bench_lb = league.get("bench_leaderboard") or []
    if bench_lb:
        b = bench_lb[0]
        items.append(("&#128256;", "SEASON BENCH KING",
            f"<b>{esc(b['name'])}</b> has wasted <b>{fnum(b.get('season_bench'))} pts</b> on the bench this season"))

    if not items:
        return ""

    cards = []
    for icon, label, body in items:
        cards.append(f"""
<div class="tp-card">
  <div class="tp-icon">{icon}</div>
  <div class="tp-body">
    <div class="tp-label">{label}</div>
    <div class="tp-text">{body}</div>
  </div>
</div>""")

    return f"""
<section class="talking-points">
  {_divider("TALKING POINTS")}
  <div class="tp-grid">{''.join(cards)}</div>
</section>"""


def _footer(meta: dict) -> str:
    gw = meta.get("gameweek", "")
    league = esc(meta.get("league_name", ""))
    season = esc(meta.get("season_label") or "2026/27")
    generated = meta.get("generated_at", "")
    return f"""
<footer class="np-footer">
  <div class="footer-thick"></div>
  <div class="footer-inner">
    <span>{league} &middot; The Gazette &middot; Vol. {esc(str(gw))}, No. 1</span>
    <span class="footer-center">&#10022; FPL SPY AUTOMATED REPORT &#10022;</span>
    <span class="footer-right">Season {season} &middot; Generated {esc(generated)}</span>
  </div>
</footer>"""


# Known FB display-name → real name aliases
_PHOTO_ALIASES: dict[str, str] = {
    "white fang": "Sahil Rauniyar",
    "ashish shrestha": "Aasis Shrestha",  # same person, FPL vs FB spelling
}


def _resolve_photos(manager_photos: dict, managers: list) -> dict:
    """Return a photo lookup keyed by each manager's actual name.

    Handles: case-insensitive matching, partial-name matching (first + last),
    and the FB display-name aliases above.
    """
    # Build a case-insensitive index of the raw mapping
    lower_map: dict[str, str] = {k.lower(): v for k, v in manager_photos.items()}
    # Also index by alias
    for alias_lower, real in _PHOTO_ALIASES.items():
        if real in manager_photos:
            lower_map[alias_lower] = manager_photos[real]

    resolved: dict[str, str] = {}
    for m in managers:
        name = m.get("name", "")
        if not name:
            continue
        # Exact (case-insensitive)
        key = name.lower()
        if key in lower_map:
            resolved[name] = lower_map[key]
            continue
        # Alias lookup
        if key in _PHOTO_ALIASES:
            real = _PHOTO_ALIASES[key]
            if real in manager_photos:
                resolved[name] = manager_photos[real]
                continue
        # First + last name fuzzy: e.g. "brilendra panta" matches "Brilendra Murti Panta"
        parts = name.lower().split()
        if len(parts) >= 2:
            first, last = parts[0], parts[-1]
            for photo_name_lower, path in lower_map.items():
                pn_parts = photo_name_lower.split()
                if pn_parts and pn_parts[0] == first and pn_parts[-1] == last:
                    resolved[name] = path
                    break

    return resolved


# ── Master entry point ────────────────────────────────────────────────────── #
def render_report_html(payload: dict) -> str:
    meta = payload.get("meta") or {}
    managers = payload.get("managers") or []
    league = payload.get("league") or {}
    narrative = payload.get("narrative") or ""
    raw_photos = payload.get("manager_photos") or {}

    # Resolve photos against actual managers only (drops FB-group extras)
    manager_photos = _resolve_photos(raw_photos, managers)

    body = "\n".join([
        _edition_bar(meta),
        _masthead(meta),
        _section_nav(meta),
        f"""
<div class="main-area">
  <div class="lead-col">
    {_lead_article(narrative, managers, manager_photos)}
    {_hero(payload, managers, manager_photos)}
    {_talking_points(payload, managers)}
  </div>
  {_sidebar(managers, manager_photos, league)}
</div>""",
        _stats_strip(managers, league),
        _manager_dossiers(managers, manager_photos),
        _race_section(managers),
        _intel(league),
        _footer(meta),
    ])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=1200">
<title>FPL Gazette &mdash; GW{esc(str(meta.get('gameweek','')))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<div class="page">{body}</div>
</body>
</html>"""


# ── CSS ───────────────────────────────────────────────────────────────────── #
CSS = f"""
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ background: #f2efe8; color: {INK}; }}
body {{
  width: 1200px; margin: 0 auto;
  font-family: 'Source Serif 4', Georgia, 'Times New Roman', serif;
  font-size: 15px; line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}}
.page {{ padding: 0 32px 32px; background: {BG}; box-shadow: 0 0 40px rgba(0,0,0,0.10); }}

/* ── Edition bar ── */
.edition-bar {{
  font-size: 10px; letter-spacing: 0.9px; color: {MUTED};
  text-align: center; padding: 5px 0 4px;
  border-bottom: 1px solid {RULE}; text-transform: uppercase;
  font-family: 'Source Serif 4', Georgia, serif;
}}

/* ── Masthead ── */
.masthead {{ margin-bottom: 0; }}
.mast-rule-thick {{ height: 4px; background: {INK}; margin: 6px 0; }}
.mast-rule-thin {{ height: 1px; background: {RULE}; margin: 2px 0 0; }}
.mast-inner {{
  display: grid; grid-template-columns: 200px 1fr 200px;
  align-items: center; padding: 10px 0 7px;
}}
.mast-side {{
  font-size: 9.5px; letter-spacing: 0.9px; text-transform: uppercase;
  color: {MUTED}; line-height: 1.75;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.mast-right {{ text-align: right; }}
.mast-season {{ color: {INK2}; font-weight: 600; }}
.mast-status {{ color: {HEADLINE}; font-weight: 700; }}
.mast-center {{ text-align: center; }}
.mast-league {{
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 52px; font-weight: 900; letter-spacing: -1.5px;
  line-height: 1; color: {INK}; text-transform: uppercase;
}}
.mast-gazette {{
  font-size: 11px; letter-spacing: 6px; color: {MUTED}; margin-top: 4px;
  text-transform: uppercase; font-family: 'Source Serif 4', Georgia, serif;
}}

/* ── Section nav ── */
.section-nav {{
  display: flex; align-items: center; gap: 10px;
  font-size: 10px; letter-spacing: 0.8px; text-transform: uppercase;
  color: {MUTED}; padding: 5px 0;
  border-top: 2px solid {INK}; border-bottom: 1px solid {RULE};
  margin-bottom: 14px;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.section-pill {{
  background: {HEADLINE}; color: {WHITE}; padding: 2px 8px;
  font-size: 9px; letter-spacing: 1.5px; font-weight: 700;
}}
.nav-sep {{ color: {RULE}; }}
.nav-item {{ color: {INK2}; }}
.nav-final {{ color: {HEADLINE}; font-weight: 700; }}
.nav-live {{ color: #1a6b1a; font-weight: 700; }}

/* ── Main two-column ── */
.main-area {{
  display: grid; grid-template-columns: 1fr 285px;
  gap: 0; margin-bottom: 16px; align-items: start;
  position: relative;
}}
.main-area::after {{
  content: ''; position: absolute;
  top: 0; bottom: 0; left: calc(100% - 285px - 0px);
  width: 1px; background: {RULE};
  pointer-events: none;
}}
.lead-col {{ padding-right: 24px; }}
.sidebar {{ padding-left: 18px; }}

/* ── Lead article ── */
.section-flag {{
  display: inline-block; font-size: 9px; letter-spacing: 1.5px;
  text-transform: uppercase; font-weight: 700; color: {BG};
  background: {HEADLINE}; padding: 2px 8px; margin-bottom: 10px;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.headline {{
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 46px; font-weight: 900; line-height: 1.06;
  color: {HEADLINE}; margin-bottom: 10px;
}}
.deck {{
  font-size: 17px; font-style: italic; color: {INK2};
  line-height: 1.45; margin-bottom: 10px;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.byline {{
  font-size: 10.5px; font-variant: small-caps; letter-spacing: 0.7px;
  color: {MUTED}; margin-bottom: 6px;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.byline-sep {{ margin: 0 6px; color: {RULE}; }}
.byline-rule {{ height: 1px; background: {RULE}; margin-bottom: 8px; }}
.article-body {{
  column-count: 2; column-gap: 18px;
  column-rule: 1px solid {RULE};
}}
.article-para {{
  font-size: 14.5px; line-height: 1.68; color: {INK};
  text-align: justify; hyphens: auto; margin-bottom: 12px;
  break-inside: avoid;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.first-para {{ margin-top: 0; }}
.dateline {{
  font-size: 11px; font-variant: small-caps; letter-spacing: 0.5px;
  font-weight: 600; color: {INK};
  font-family: 'Source Serif 4', Georgia, serif;
}}
.drop {{
  float: left;
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 70px; font-weight: 900; line-height: 0.78;
  color: {HEADLINE}; margin: 4px 6px 0 0; padding-top: 4px;
}}
.continued {{
  font-size: 11px; font-style: italic; color: {MUTED};
  text-align: right; margin-top: 8px; break-inside: avoid;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.pull-quote {{
  border-top: 2px solid {ACCENT}; border-bottom: 2px solid {ACCENT};
  padding: 8px 6px; margin: 10px 0;
  text-align: center; break-inside: avoid;
  column-span: all; background: {PAPER};
}}
.pq-open, .pq-close {{
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 34px; line-height: 0.7; color: {HEADLINE};
  display: block;
}}
.pq-close {{ text-align: right; }}
.pq-text {{
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 16px; font-style: italic; color: {INK};
  line-height: 1.42; margin: 4px 0;
}}

/* ── Talking points ── */
.talking-points {{ margin: 10px 0 4px; }}
.tp-grid {{
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 6px; margin-top: 6px;
}}
.tp-card {{
  background: {PAPER}; border: 1px solid {RULE};
  border-top: 3px solid {HEADLINE};
  padding: 7px 9px; display: flex; gap: 8px; align-items: flex-start;
}}
.tp-icon {{ font-size: 18px; line-height: 1; flex-shrink: 0; margin-top: 1px; }}
.tp-label {{
  font-size: 8.5px; font-weight: 800; letter-spacing: 1.2px;
  text-transform: uppercase; color: {HEADLINE};
  margin-bottom: 3px;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.tp-text {{
  font-size: 12px; line-height: 1.45; color: {INK};
  font-family: 'Source Serif 4', Georgia, serif;
}}
.tp-text b {{ color: {HEADLINE}; }}

/* ── Manager verdicts ── */
.verdicts-section {{
  margin: 14px 0 6px; border-top: 2px solid {HEADLINE};
  padding-top: 8px;
}}
.verdicts-label {{
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 10px; font-weight: 700; letter-spacing: 1.2px;
  color: {HEADLINE}; text-transform: uppercase; margin-bottom: 7px;
}}
.verdicts-grid {{
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 5px 14px;
}}
.verdict-item {{
  font-size: 12.5px; line-height: 1.45; color: {INK};
  font-family: 'Source Serif 4', Georgia, serif;
  border-left: 2px solid {RULE}; padding-left: 6px;
  display: flex; align-items: flex-start; gap: 6px;
}}
.vd-av-wrap {{ flex-shrink: 0; margin-top: 1px; }}
.vd-avatar {{
  width: 20px; height: 20px; border-radius: 50%;
  object-fit: cover; border: 1px solid {RULE}; display: block;
}}
.vd-initials {{
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: 50%;
  background: {RULE}; color: {MUTED};
  font-size: 7px; font-weight: 700;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.verdict-name {{
  font-weight: 700; color: {HEADLINE}; margin-right: 4px;
}}
.verdict-text {{ color: {INK}; }}
.article-teaser {{
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 13px; font-style: italic; color: {MUTED};
  border-top: 1px solid {RULE}; padding-top: 7px; margin-top: 8px;
  text-align: center;
}}

/* ── Hero ── */
.hero-img-wrap {{ margin: 14px 0 4px; border: 1px solid {RULE}; }}
.hero-img {{ display: block; width: 100%; max-height: 250px; object-fit: cover; }}
.hero-placeholder {{
  background: {BG}; border: 1px solid {RULE};
  border-left: 4px solid {HEADLINE};
  padding: 14px 18px; margin: 10px 0 4px;
  display: flex; align-items: center; gap: 18px;
}}
.hp-week {{
  font-size: 9px; letter-spacing: 2px; text-transform: uppercase;
  color: {HEADLINE}; margin-bottom: 3px;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.hp-name {{
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 24px; font-weight: 900; color: {INK}; line-height: 1.1;
}}
.hp-pts {{
  font-size: 13px; color: {MUTED}; font-style: italic; margin-top: 2px;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.hp-score {{
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 48px; font-weight: 900; color: {HEADLINE};
  line-height: 1; flex-shrink: 0;
}}
.hp-photo {{
  width: 64px; height: 64px; border-radius: 50%;
  object-fit: cover; border: 2px solid {HEADLINE}; flex-shrink: 0;
}}
.hp-initials {{
  width: 64px; height: 64px; border-radius: 50%;
  background: {HEADLINE}; color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 22px; font-weight: 700; flex-shrink: 0;
}}
.img-caption {{
  font-size: 11px; font-style: italic; color: {MUTED};
  padding: 4px 0 8px; border-bottom: 1px solid {RULE}; margin-bottom: 8px;
  font-family: 'Source Serif 4', Georgia, serif;
}}

/* ── Sidebar ── */
.sb-section {{ margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid {RULE}; }}
.sb-section:last-child {{ border-bottom: none; }}
.sb-head {{
  font-size: 10px; letter-spacing: 2px; text-transform: uppercase;
  font-weight: 700; color: {MUTED};
  border-left: 3px solid {HEADLINE}; padding-left: 6px;
  margin-bottom: 8px;
  font-family: 'Source Serif 4', Georgia, serif;
}}

/* ── League table ── */
.lt {{ width: 100%; border-collapse: collapse; font-size: 12.5px; font-family: 'Source Serif 4', Georgia, serif; }}
.lt thead tr {{ border-bottom: 1px solid {RULE}; }}
.lt th {{
  font-size: 9px; letter-spacing: 0.8px; color: {MUTED};
  text-transform: uppercase; font-weight: 700; padding: 3px 4px;
  text-align: right;
}}
.lt th:nth-child(3) {{ text-align: left; }}
.lt td {{ padding: 5px 4px; vertical-align: middle; border-bottom: 1px solid {RULE}; }}
.lt tbody tr:last-child td {{ border-bottom: none; }}
.lt-alt td {{ background: {TALT}; }}
.lt-leader td {{ background: #fffbea; font-weight: 700; }}
.lt-rk {{ font-size: 13px; font-weight: 800; text-align: center; color: {INK}; min-width: 22px; }}
.lt-mv {{ text-align: center; }}
.lt-nm {{ font-size: 12px; font-weight: 600; color: {INK}; text-align: left; vertical-align: middle; }}
.lt-av-wrap {{ display: inline-block; margin-right: 5px; vertical-align: middle; }}
.lt-avatar {{
  width: 22px; height: 22px; border-radius: 50%;
  object-fit: cover; vertical-align: middle;
  border: 1px solid {RULE};
}}
.lt-initials {{
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 50%;
  background: {RULE}; color: {MUTED};
  font-size: 8px; font-weight: 700; vertical-align: middle;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.lt-num {{ text-align: right; font-weight: 800; font-size: 13px; font-family: 'Courier New', monospace; }}
.lt-gw {{ text-align: right; font-weight: 700; color: {HEADLINE}; font-family: 'Courier New', monospace; }}
.mv-up {{ color: {UP}; font-weight: 800; font-size: 10px; }}
.mv-dn {{ color: {DOWN}; font-weight: 800; font-size: 10px; }}
.mv-flat {{ color: {MUTED}; font-size: 10px; }}
.chip-tag {{
  font-size: 8px; font-weight: 800; background: #e8e0ff; color: #4a00a0;
  border-radius: 2px; padding: 1px 3px; margin-left: 2px; vertical-align: middle;
}}
.hit-tag {{
  font-size: 8px; font-weight: 800; background: #ffe0e0; color: {HEADLINE};
  border-radius: 2px; padding: 1px 3px; margin-left: 2px; vertical-align: middle;
}}

/* ── Captain picks ── */
.cap-list {{ display: flex; flex-direction: column; gap: 0; }}
.cap-row {{
  display: flex; align-items: center; gap: 8px;
  padding: 4px 0; border-bottom: 1px solid {RULE};
}}
.cap-row:last-child {{ border-bottom: none; }}
.mgr-avatar, .mgr-initial {{
  width: 26px; height: 26px; border-radius: 50%;
  object-fit: cover; flex-shrink: 0;
}}
.mgr-initial {{
  background: {INK2}; color: {BG}; display: flex; align-items: center;
  justify-content: center; font-size: 11px; font-weight: 800;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.cap-info {{ flex: 1; min-width: 0; }}
.cap-mgr {{ font-size: 11.5px; font-weight: 700; color: {INK}; font-family: 'Source Serif 4', Georgia, serif; }}
.cap-player {{ font-size: 10.5px; color: {MUTED}; font-style: italic; font-family: 'Source Serif 4', Georgia, serif; }}
.cap-pts {{
  font-size: 12px; font-weight: 800; text-align: right; min-width: 38px;
  font-family: 'Courier New', monospace;
}}
.cap-good {{ color: {UP}; }}
.cap-meh {{ color: {INK2}; }}
.cap-bad {{ color: {DOWN}; }}

/* ── Section dividers ── */
.section-divider {{
  display: flex; align-items: center; gap: 14px; margin: 14px 0 10px;
}}
.div-rule {{ flex: 1; height: 2px; background: {RULE}; }}
.div-label {{
  font-size: 11px; font-weight: 700; letter-spacing: 2.5px;
  text-transform: uppercase; color: {HEADLINE}; white-space: nowrap;
  font-family: 'Source Serif 4', Georgia, serif;
}}
.section-divider-plain {{ height: 3px; background: {INK}; margin: 24px 0 20px; }}

/* ── Stats strip ── */
.stats-section {{ margin-bottom: 16px; }}
.stats-grid {{
  display: grid; grid-template-columns: repeat(4, 1fr);
  border: 1px solid {RULE}; border-top: 3px solid {HEADLINE};
  background: {PAPER};
}}
.stat-box {{ padding: 12px 14px; border-right: 1px solid {RULE}; text-align: center; }}
.stat-box:last-child {{ border-right: none; }}
.stat-emoji {{ font-size: 18px; margin-bottom: 3px; }}
.stat-kicker {{
  font-size: 9px; letter-spacing: 1.5px; color: {MUTED}; text-transform: uppercase;
  font-weight: 700; margin-bottom: 5px; font-family: 'Source Serif 4', Georgia, serif;
}}
.stat-name {{ font-size: 13px; font-weight: 700; color: {INK}; margin-bottom: 3px; font-family: 'Source Serif 4', Georgia, serif; }}
.stat-value {{
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 21px; font-weight: 900; color: {HEADLINE}; margin-bottom: 2px;
}}
.stat-sub {{ font-size: 10px; color: {MUTED}; font-style: italic; font-family: 'Source Serif 4', Georgia, serif; }}

/* ── Manager dossiers ── */
.dossier-section {{ margin-bottom: 20px; }}
.mc-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; }}
.mc {{
  background: {BG}; border: 1px solid {RULE};
  padding: 9px 8px 8px; font-family: 'Source Serif 4', Georgia, serif;
}}
.mc-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }}
.mc-avatar, .mc-initial {{
  width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0; object-fit: cover;
}}
.mc-initial {{
  display: flex; align-items: center; justify-content: center;
  color: {WHITE}; font-size: 13px; font-weight: 800;
}}
.mc-id {{ flex: 1; min-width: 0; }}
.mc-rank {{ font-size: 17px; font-weight: 900; line-height: 1; margin-bottom: 1px; font-family: 'Playfair Display', Georgia, serif; }}
.mc-name {{ font-size: 12px; font-weight: 700; color: {INK}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.mc-team {{ font-size: 9.5px; color: {MUTED}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-style: italic; }}
.mc-gwv {{ font-family: 'Playfair Display', Georgia, serif; font-size: 22px; font-weight: 900; flex-shrink: 0; }}
.mc-arch {{ font-size: 9px; letter-spacing: 0.8px; color: {ACCENT}; text-transform: uppercase; font-weight: 700; margin-bottom: 4px; font-style: italic; }}
.mc-tags {{ display: flex; gap: 4px; flex-wrap: wrap; font-size: 9.5px; margin-bottom: 4px; min-height: 14px; }}
.mc-spark {{ margin: 4px 0 2px; overflow: hidden; }}
.spark-cap {{ font-size: 9px; color: {MUTED}; font-style: italic; margin-top: 1px; }}
.mc-stats {{ width: 100%; border-collapse: collapse; margin-top: 6px; border-top: 1px solid {RULE}; font-size: 10.5px; }}
.mc-stats tr {{ border-bottom: 1px solid {RULE}; }}
.mc-stats tr:last-child {{ border-bottom: none; }}
.mc-alt {{ background: {TALT}; }}
.mcs-k {{ color: {MUTED}; padding: 3px 4px; font-size: 9.5px; width: 45%; }}
.mcs-v {{ font-weight: 700; padding: 3px 4px; text-align: right; font-family: 'Courier New', monospace; font-size: 10px; }}

/* ── Race chart ── */
.race-section {{ margin-bottom: 20px; }}
.chart-wrap {{ border: 1px solid {RULE}; overflow-x: auto; background: {BG}; }}

/* ── Intel ── */
.intel-section {{ margin-bottom: 20px; }}
.intel-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid {RULE}; }}
.intel-panel {{ padding: 12px 12px; border-right: 1px solid {RULE}; font-family: 'Source Serif 4', Georgia, serif; }}
.intel-panel:first-child {{ background: {TALT}; }}
.intel-panel:last-child {{ border-right: none; }}
.intel-head {{
  font-size: 10px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase;
  color: {INK2}; border-bottom: 2px solid {INK}; padding-bottom: 6px; margin-bottom: 10px;
}}
.intel-note {{ font-weight: 500; color: {MUTED}; letter-spacing: 0; text-transform: none; }}
.intel-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
.intel-table thead tr {{ border-bottom: 1px solid {RULE}; }}
.intel-table th {{
  font-size: 9px; letter-spacing: 0.7px; color: {MUTED}; text-transform: uppercase;
  font-weight: 700; padding: 2px 4px; text-align: left;
}}
.intel-table td {{ padding: 5px 4px; border-bottom: 1px solid {RULE}; }}
.intel-table tbody tr:last-child td {{ border-bottom: none; }}
.intel-rank {{ color: {MUTED}; font-weight: 800; font-size: 11px; white-space: nowrap; }}
.intel-name {{ font-weight: 600; }}
.intel-score {{ font-family: 'Courier New', monospace; font-weight: 700; color: {HEADLINE}; text-align: right; }}
.ct-list {{ display: flex; flex-direction: column; gap: 8px; }}
.ct-row {{ display: flex; align-items: center; gap: 8px; font-size: 11.5px; }}
.ct-name {{ font-weight: 600; min-width: 75px; font-size: 11px; }}
.ct-bar-wrap {{ flex: 1; background: {RULE}; border-radius: 2px; height: 7px; overflow: hidden; }}
.ct-bar {{ height: 100%; background: {HEADLINE}; border-radius: 2px; }}
.ct-meta {{ font-size: 10px; color: {MUTED}; white-space: nowrap; min-width: 65px; text-align: right; font-family: 'Courier New', monospace; }}
.rv-list {{ display: flex; flex-direction: column; gap: 0; }}
.rv-row {{
  display: flex; align-items: center; gap: 8px;
  padding: 6px 0; border-bottom: 1px solid {RULE}; font-size: 12px;
}}
.rv-row:last-child {{ border-bottom: none; }}
.rv-a {{ font-weight: 700; flex: 1; font-size: 11.5px; }}
.rv-gap {{
  font-size: 10px; font-weight: 800; background: #fffbea; border: 1px solid {ACCENT};
  border-radius: 2px; padding: 1px 5px; white-space: nowrap; color: {ACCENT};
  font-family: 'Courier New', monospace;
}}
.rv-b {{ font-size: 10.5px; color: {MUTED}; flex: 1; text-align: right; font-style: italic; }}

/* ── Footer ── */
.np-footer {{ margin-top: 24px; font-family: 'Source Serif 4', Georgia, serif; }}
.footer-thick {{ height: 5px; background: {INK}; margin-bottom: 2px; }}
.footer-inner {{
  display: flex; justify-content: space-between; align-items: center;
  font-size: 10px; color: {MUTED}; padding: 5px 0;
  letter-spacing: 0.5px; text-transform: uppercase;
}}
.footer-center {{ font-size: 12px; color: {INK2}; letter-spacing: 3px; }}
.footer-right {{ text-align: right; }}
"""
