"""Render the animated SVG cards for the profile README.

Reads profile.json, data/github.json and data/portrait.txt, writes cards/*.svg
and refreshes the card block in README.md (between the cards:start/end
markers; everything outside the markers is left alone).

    python scripts/render_cards.py            # normal run (used by the Action)
    STATIC=1 python scripts/render_cards.py   # final frame only, for screenshots
    python scripts/render_cards.py --sample --out /tmp/preview
                                              # made-up data, for local previews

The cards are shown through <img>, so they only use what works there: an
inline <style> with CSS keyframes and fonts embedded as base64 data URIs.
Every element's resting state is its final state and the animations play
*into* it, so turning animations off (prefers-reduced-motion or STATIC=1)
simply shows the finished card.
"""

import base64
import json
import os
import random
import sys
from collections import defaultdict
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
STATIC = os.environ.get("STATIC") == "1"

# ---------------------------------------------------------------- palette

# Neutral graphite, like a dark editor/chat UI, with one warm accent used
# sparingly (cursor, prompt, live dots, keywords).
BG = "#191919"
PANEL = "#222222"
BORDER = "#303030"
INK = "#EFEFEF"
SOFT = "#C4C4C4"
MUTED = "#9A9A9A"
DIM = "#626262"
ACCENT = "#D97757"
GRAPH_LEVELS = ["#262626", "#474747", "#767676", "#ADADAD", "#EFEFEF"]
BAR = "#333333"
STAT_BAR = "#4A4A4A"

MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
WEEKDAYS = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"]

# Timeline: the cards load together, so offsets make the page play top to bottom.
T_HERO, T_GRAPH, T_TILES, T_ACTIVITY, T_STACK, T_REPOS = 0.0, 1.0, 1.8, 2.4, 2.9, 3.2

# ---------------------------------------------------------------- fonts

FONTS = {
    "sg500": ("Space Grotesk", 500, "space-grotesk-500.woff2"),
    "sg700": ("Space Grotesk", 700, "space-grotesk-700.woff2"),
    "mono400": ("JetBrains Mono", 400, "jetbrains-mono-400.woff2"),
    "mono700": ("JetBrains Mono", 700, "jetbrains-mono-700.woff2"),
}
SANS = "'Space Grotesk',system-ui,sans-serif"
MONO = "'JetBrains Mono',ui-monospace,monospace"


def font_face(key: str) -> str:
    family, weight, file = FONTS[key]
    b64 = base64.b64encode((ROOT / "fonts" / file).read_bytes()).decode()
    return (
        f"@font-face{{font-family:'{family}';font-weight:{weight};"
        f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}"
    )


@lru_cache(maxsize=None)
def _metrics(key: str):
    font = TTFont(ROOT / "fonts" / FONTS[key][2])
    return font.getBestCmap(), font["hmtx"].metrics, font["head"].unitsPerEm


def text_width(text: str, key: str, size: float) -> float:
    cmap, hmtx, upm = _metrics(key)
    units = 0
    for ch in text:
        glyph = cmap.get(ord(ch))
        units += hmtx[glyph][0] if glyph else upm * 0.55
    return units * size / upm


def wrap(text: str, key: str, size: float, max_width: float) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and text_width(trial, key, size) > max_width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


# ---------------------------------------------------------------- svg helpers

BASE_CSS = """
.fu{animation:fu .7s cubic-bezier(.2,.8,.2,1) both}
@keyframes fu{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
.fi{animation:fi .5s ease both}
@keyframes fi{from{opacity:0}to{opacity:1}}
.pop{transform-box:fill-box;transform-origin:center;animation:pop .45s cubic-bezier(.3,1.6,.5,1) both}
@keyframes pop{from{opacity:0;transform:scale(.2)}to{opacity:1;transform:scale(1)}}
.grow{transform-box:fill-box;transform-origin:50% 100%;animation:grow .9s cubic-bezier(.2,.8,.2,1) both}
@keyframes grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}
.pulse{opacity:0;transform-box:fill-box;transform-origin:center;animation:pulse 2.2s ease-out infinite}
@keyframes pulse{0%{opacity:.7;transform:scale(1)}100%{opacity:0;transform:scale(2.4)}}
.nudge{animation:nudge 2.6s ease-in-out infinite}
@keyframes nudge{0%,55%,100%{transform:none}72%{transform:translate(3px,-3px)}}
.blink{animation:blink 1.05s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
.flash{opacity:0;animation:flash 1s linear none}
@keyframes flash{from,to{opacity:1}}
.appear{animation:appear 1ms linear both}
@keyframes appear{from{opacity:0}to{opacity:1}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
"""
STATIC_CSS = "*{animation:none!important}"


def d(seconds: float) -> str:
    return f"animation-delay:{seconds:.3f}s"


def svg(w: int, h: int, title: str, body: str, css: str = "", fonts=(), frame: bool = True) -> str:
    style = "".join(font_face(f) for f in fonts) + BASE_CSS + css
    if STATIC:
        style += STATIC_CSS
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">'
        f"<title>{escape(title)}</title><style>{style}</style>"
        + (
            f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="16" '
            f'fill="{BG}" stroke="{BORDER}"/>'
            if frame
            else ""
        )
        + f"{body}</svg>\n"
    )


def t(x, y, text, size, color=INK, font=SANS, weight=400, anchor="start", extra=""):
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font}" font-size="{size}" '
        f'font-weight="{weight}" fill="{color}" text-anchor="{anchor}" {extra}>'
        f"{escape(str(text))}</text>"
    )


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


# ---------------------------------------------------------------- stats


def compute_stats(data: dict) -> dict:
    days = sorted(
        ((date.fromisoformat(x["date"]), x["count"]) for x in data["days"]),
        key=lambda x: x[0],
    )
    counts = [c for _, c in days]

    # Current streak: today may still be empty, so start from yesterday then.
    i = len(days) - 1
    if i >= 0 and counts[i] == 0:
        i -= 1
    current = 0
    while i >= 0 and counts[i] > 0:
        current += 1
        i -= 1

    longest = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)

    best_day = max(days, key=lambda x: x[1]) if days else (date.today(), 0)

    by_month = defaultdict(int)
    for dt, c in days:
        by_month[(dt.year, dt.month)] += c
    last = days[-1][0] if days else date.today()
    months = []
    y, m = last.year, last.month
    for _ in range(12):
        months.append(((y, m), by_month.get((y, m), 0)))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()

    weekday = defaultdict(int)
    for dt, c in days:
        weekday[(dt.weekday() + 1) % 7] += c  # 0 = domingo
    fav_weekday = max(range(7), key=lambda k: weekday[k]) if days else 0

    nonzero = sorted(c for c in counts if c > 0)
    if nonzero:
        q = [nonzero[min(len(nonzero) - 1, int(len(nonzero) * p))] for p in (0.25, 0.5, 0.75)]
    else:
        q = [1, 2, 3]

    return {
        "days": days,
        "total": data["total_contributions"],
        "public_repos": data["public_repos"],
        "current_streak": current,
        "longest_streak": longest,
        "active_days": len(nonzero),
        "best_day": best_day,
        "months": months,
        "fav_weekday": fav_weekday,
        "quartiles": q,
    }


def level(count: int, q: list[int]) -> int:
    if count <= 0:
        return 0
    if count <= q[0]:
        return 1
    if count <= q[1]:
        return 2
    if count <= q[2]:
        return 3
    return 4


# ---------------------------------------------------------------- cards


def hero(profile: dict, portrait: list[str]) -> str:
    W, H = 840, 320
    parts = []

    # Terminal window with the ASCII portrait printing in row by row.
    px, py, pw, ph = 24, 24, 280, 272
    parts.append(
        f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="12" fill="{PANEL}" stroke="{BORDER}"/>'
        f'<path d="M{px} {py + 28}h{pw}" stroke="{BORDER}"/>'
    )
    for i, c in enumerate(("#3A3A3A", "#3A3A3A", "#3A3A3A")):
        parts.append(f'<circle cx="{px + 18 + i * 16}" cy="{py + 14}" r="5" fill="{c}"/>')
    parts.append(t(px + pw - 14, py + 18, "~/retrato", 11, DIM, MONO, anchor="end"))

    if portrait:
        cols = max(len(r) for r in portrait)
        size = min((pw - 28) / (cols * 0.6), (ph - 48) / (len(portrait) * 1.08))
        lh = size * 1.08
        ox = px + (pw - cols * size * 0.6) / 2
        oy = py + 28 + (ph - 28 - len(portrait) * lh) / 2 + size * 0.8
        parts.append(
            f'<linearGradient id="pg" gradientUnits="userSpaceOnUse" x1="0" y1="{py + 30}" x2="0" y2="{py + ph}">'
            f'<stop offset="0" stop-color="{INK}"/><stop offset=".6" stop-color="{SOFT}"/>'
            f'<stop offset="1" stop-color="{DIM}"/></linearGradient>'
        )
        rows = []
        for i, row in enumerate(portrait):
            rows.append(
                f'<text class="fi" style="{d(T_HERO + 0.25 + i * 0.03)}" x="{ox:.1f}" '
                f'y="{oy + i * lh:.1f}" xml:space="preserve">{escape(row)}</text>'
            )
        parts.append(
            f'<g font-family="{MONO}" font-size="{size:.2f}" fill="url(#pg)">{"".join(rows)}</g>'
        )

    # Right column.
    x = 340
    parts.append(
        f'<g class="fu" style="{d(T_HERO + 0.1)}">'
        + t(x, 74, "> whoami", 13, ACCENT, MONO)
        + "</g>"
    )
    parts.append(
        f'<g class="fu" style="{d(T_HERO + 0.25)}">'
        + t(x, 108, profile["greeting"], 22, MUTED, SANS, 500)
        + "</g>"
    )

    name = profile["name"]
    name_size = 52
    while text_width(name, "sg700", name_size) > W - x - 30 and name_size > 30:
        name_size -= 2
    nw = text_width(name, "sg700", name_size)
    parts.append(
        f'<clipPath id="nameclip">{t(x, 164, name, name_size, INK, SANS, 700)}</clipPath>'
        f'<linearGradient id="shine" x1="0" x2="1" y1="0" y2="0">'
        f'<stop offset="0" stop-color="{ACCENT}" stop-opacity="0"/>'
        f'<stop offset=".5" stop-color="{ACCENT}" stop-opacity=".9"/>'
        f'<stop offset="1" stop-color="{ACCENT}" stop-opacity="0"/></linearGradient>'
        f'<g class="fu" style="{d(T_HERO + 0.4)}">'
        + t(x, 164, name, name_size, INK, SANS, 700)
        + f'<g clip-path="url(#nameclip)"><rect class="shine" x="{x}" y="100" width="110" '
        f'height="80" fill="url(#shine)"/></g></g>'
    )

    # Role with a pulsing dot.
    parts.append(
        f'<g class="fu" style="{d(T_HERO + 0.55)}">'
        f'<circle cx="{x + 6}" cy="{198}" r="5" fill="{ACCENT}"/>'
        f'<circle class="pulse" cx="{x + 6}" cy="{198}" r="5" fill="none" stroke="{ACCENT}" stroke-width="1.5"/>'
        + t(x + 24, 204, profile["role"], 18, INK, SANS, 500)
        + "</g>"
    )
    tag_lines = wrap(profile["tagline"], "sg500", 15, W - x - 30)[:2]
    for i, line in enumerate(tag_lines):
        parts.append(
            f'<g class="fu" style="{d(T_HERO + 0.65 + i * 0.08)}">'
            + t(x, 232 + i * 21, line, 15, MUTED, SANS, 500)
            + "</g>"
        )

    # Code line that types itself.
    code = profile["code_line"]
    cs = 12.5
    cw = text_width(code, "mono400", cs)
    while cw > W - x - 52 and cs > 9:
        cs -= 0.5
        cw = text_width(code, "mono400", cs)
    by = 268
    box_w = min(W - x - 24, cw + 28)
    parts.append(
        f'<g class="fu" style="{d(T_HERO + 0.8)}">'
        f'<rect x="{x}" y="{by}" width="{box_w:.1f}" height="30" rx="8" fill="{PANEL}" stroke="{BORDER}"/>'
        f'<text x="{x + 14}" y="{by + 19.5}" font-family="{MONO}" font-size="{cs}" '
        f'xml:space="preserve">{highlight(code)}</text>'
        f"</g>"
    )
    chars = len(code)
    type_dur = chars * 0.045
    type_start = T_HERO + 1.2
    parts.append(
        f'<clipPath id="codeclip"><rect x="{x + 1}" y="{by + 1}" width="{box_w - 2:.1f}" height="28" rx="7"/></clipPath>'
        f'<g clip-path="url(#codeclip)"><g class="typer">'
        f'<rect x="{x + 12}" y="{by + 3}" width="{cw + 4:.1f}" height="24" fill="{PANEL}"/>'
        f'<rect class="blink" x="{x + 13}" y="{by + 8}" width="2" height="15" fill="{ACCENT}"/>'
        f"</g></g>"
    )
    css = (
        f".typer{{transform:translateX({cw:.1f}px);animation:type {type_dur:.2f}s steps({chars}) "
        f"{type_start:.2f}s both}}"
        f"@keyframes type{{from{{transform:translateX(0)}}to{{transform:translateX({cw:.1f}px)}}}}"
        f".shine{{transform:translateX(-140px);animation:shine 5.5s ease-in-out {T_HERO + 1.6:.1f}s infinite}}"
        f"@keyframes shine{{0%{{transform:translateX(-140px)}}35%,100%{{transform:translateX({nw + 40:.0f}px)}}}}"
    )
    return svg(W, H, f"{name} — {profile['role']}", "".join(parts), css, ("sg500", "sg700", "mono400"))


def highlight(code: str) -> str:
    """Tiny JS-ish highlighter: keywords, strings, booleans, identifiers."""
    import re

    out = []
    for tok in re.findall(r"'[^']*'|\"[^\"]*\"|\w+|\s+|.", code):
        if tok in ("const", "let", "var", "function", "return", "new"):
            c = ACCENT
        elif tok[:1] in "'\"":
            c = SOFT
        elif tok in ("true", "false", "null") or tok.isdigit():
            c = ACCENT
        elif re.fullmatch(r"\w+", tok):
            c = INK
        else:
            c = DIM
        out.append(f'<tspan fill="{c}">{escape(tok)}</tspan>')
    return "".join(out)


def graph(stats: dict) -> str:
    W, H = 840, 236
    days = stats["days"]
    q = stats["quartiles"]
    cell, gap = 11, 3
    step = cell + gap
    ox, oy = 62, 98
    parts = [
        f'<g class="fu" style="{d(T_GRAPH)}">'
        + t(28, 42, "Contribuições", 20, INK, SANS, 700)
        + t(28, 62, "no último ano", 13, MUTED, SANS, 500)
        + "</g>",
        f'<g class="fu" style="{d(T_GRAPH + 0.1)}">'
        + t(W - 28, 50, fmt(stats["total"]), 34, INK, SANS, 700, "end")
        + "</g>",
    ]
    if days:
        first = days[0][0]
        start = first - timedelta(days=(first.weekday() + 1) % 7)  # previous Sunday
        cols = 0
        rects = []
        seen_months = set()
        labels = []
        for dt, c in days:
            col = (dt - start).days // 7
            row = (dt.weekday() + 1) % 7
            cols = max(cols, col + 1)
            rects.append(
                f'<rect class="pop c{col}" x="{ox + col * step}" y="{oy + row * step}" '
                f'width="{cell}" height="{cell}" rx="2.5" fill="{GRAPH_LEVELS[level(c, q)]}"/>'
            )
            if dt.day <= 7 and (dt.year, dt.month) not in seen_months and col > 0:
                seen_months.add((dt.year, dt.month))
                labels.append(t(ox + col * step, oy - 8, MONTHS[dt.month - 1], 10, DIM, MONO))
        parts.append(f'<g class="fi" style="{d(T_GRAPH + 0.1)}">{"".join(labels)}</g>')
        for row, name in ((1, "seg"), (3, "qua"), (5, "sex")):
            parts.append(t(ox - 10, oy + row * step + 9, name, 10, DIM, MONO, anchor="end"))
        parts.append("".join(rects))
        sweep = "".join(
            f".c{i}{{animation-delay:{T_GRAPH + 0.3 + i * 0.022:.3f}s}}" for i in range(cols)
        )
    else:
        sweep = ""

    # Legend
    lx = W - 28 - 5 * step - 70
    ly = H - 28
    legend = t(lx, ly + 9, "menos", 10, DIM, MONO, anchor="end")
    for i, col in enumerate(GRAPH_LEVELS):
        legend += f'<rect x="{lx + 8 + i * step}" y="{ly}" width="{cell}" height="{cell}" rx="2.5" fill="{col}"/>'
    legend += t(lx + 8 + 5 * step + 4, ly + 9, "mais", 10, DIM, MONO)
    parts.append(f'<g class="fi" style="{d(T_GRAPH + 1.4)}">{legend}</g>')
    return svg(W, H, f"{stats['total']} contribuições no último ano", "".join(parts), sweep, ("sg500", "sg700", "mono400"))


def tile(label: str, value: int, caption: str, color: str, delay: float) -> str:
    W, H = 270, 150
    frames = 18
    frame_dur = 0.055
    count_start = delay + 0.55
    nums = []
    for i in range(frames):
        p = (i + 1) / (frames + 1)
        v = round(value * (1 - (1 - p) ** 3))
        nums.append(
            f'<text class="flash" style="animation-delay:{count_start + i * frame_dur:.3f}s;'
            f'animation-duration:{frame_dur:.3f}s" x="24" y="98" font-family="{SANS}" '
            f'font-size="46" font-weight="700" fill="{INK}">{fmt(v)}</text>'
        )
    nums.append(
        f'<text class="appear" style="{d(count_start + frames * frame_dur)}" x="24" y="98" '
        f'font-family="{SANS}" font-size="46" font-weight="700" fill="{INK}">{fmt(value)}</text>'
    )
    body = (
        f'<clipPath id="tc"><rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="15"/></clipPath>'
        f'<linearGradient id="ts" x1="0" x2="1" y1="0" y2="0">'
        f'<stop offset="0" stop-color="#fff" stop-opacity="0"/>'
        f'<stop offset=".5" stop-color="#fff" stop-opacity=".09"/>'
        f'<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
        f'<g class="swing" style="{d(delay)}">'
        f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="15" fill="{PANEL}" stroke="{BORDER}"/>'
        f'<circle cx="{W - 26}" cy="31" r="4.5" fill="{color}"/>'
        f'<circle class="pulse" style="{d(delay + 0.9)}" cx="{W - 26}" cy="31" r="4.5" fill="none" stroke="{color}" stroke-width="1.5"/>'
        + t(24, 36, label, 12, MUTED, MONO, 700, extra='letter-spacing="1.5"')
        + "".join(nums)
        + t(24, 126, caption, 13, MUTED, SANS, 500)
        + f'<g class="nudge" style="{d(delay + 1.6)}">'
        + t(W - 24, 126, "↗", 16, MUTED, SANS, 700, "end")
        + "</g>"
        + f'<g clip-path="url(#tc)"><rect class="tshine" style="{d(delay + 2.2)}" x="0" y="0" '
        f'width="90" height="{H}" fill="url(#ts)" transform-origin="0 0"/></g>'
        + "</g>"
    )
    css = (
        ".swing{transform-box:fill-box;transform-origin:50% 100%;"
        "animation:swing .9s cubic-bezier(.2,.9,.3,1.2) both}"
        "@keyframes swing{0%{opacity:0;transform:translateY(60px) rotate(-7deg)}"
        "60%{opacity:1;transform:translateY(-6px) rotate(1.5deg)}100%{opacity:1;transform:none}}"
        ".tshine{transform:translateX(-120px) skewX(-20deg);animation:tshine 6s ease-in-out infinite}"
        "@keyframes tshine{0%{transform:translateX(-120px) skewX(-20deg)}"
        "25%,100%{transform:translateX(380px) skewX(-20deg)}}"
    )
    return svg(W, H, f"{label}: {value} {caption}", body, css, ("sg500", "sg700", "mono700"), frame=False)


def activity(stats: dict) -> str:
    W, H = 840, 270
    months = stats["months"]
    best = max(range(len(months)), key=lambda i: months[i][1]) if months else -1
    top = max((v for _, v in months), default=0) or 1
    parts = [
        f'<g class="fu" style="{d(T_ACTIVITY)}">'
        + t(28, 42, "Atividade por mês", 20, INK, SANS, 700)
        + t(28, 62, "contribuições nos últimos 12 meses", 13, MUTED, SANS, 500)
        + "</g>"
    ]
    chart_x, chart_w, base, chart_h = 28, 500, 226, 128
    slot = chart_w / max(1, len(months))
    bw = slot * 0.62
    parts.append(f'<path d="M{chart_x} {base + 0.5}h{chart_w}" stroke="{BORDER}"/>')
    for i, ((y, m), v) in enumerate(months):
        h = max(3, chart_h * v / top) if v else 3
        bx = chart_x + i * slot + (slot - bw) / 2
        color = INK if i == best else BAR
        parts.append(
            f'<rect class="grow" style="{d(T_ACTIVITY + 0.2 + i * 0.06)}" x="{bx:.1f}" '
            f'y="{base - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="4" fill="{color}"/>'
        )
        parts.append(
            t(bx + bw / 2, base + 18, MONTHS[m - 1], 10, INK if i == best else DIM, MONO, anchor="middle")
        )
        if i == best and v:
            parts.append(
                f'<g class="pop" style="{d(T_ACTIVITY + 1.2)}">'
                + t(bx + bw / 2, base - h - 8, fmt(v), 13, INK, SANS, 700, "middle")
                + "</g>"
            )

    bd, bc = stats["best_day"]
    rows = [
        ("Sequência atual", f"{stats['current_streak']} {'dia' if stats['current_streak'] == 1 else 'dias'}", ACCENT),
        ("Dias ativos", f"{stats['active_days']} de {len(stats['days'])}", STAT_BAR),
        ("Melhor dia", f"{bd.day} {MONTHS[bd.month - 1]} · {bc}", STAT_BAR),
        ("Dia favorito", WEEKDAYS[stats["fav_weekday"]], STAT_BAR),
    ]
    sx = 572
    for i, (label, value, color) in enumerate(rows):
        y = 96 + i * 42
        parts.append(
            f'<g class="fu" style="{d(T_ACTIVITY + 0.5 + i * 0.12)}">'
            f'<rect x="{sx}" y="{y - 14}" width="3" height="30" rx="1.5" fill="{color}"/>'
            + t(sx + 14, y - 1, label, 11, MUTED, MONO)
            + t(sx + 14, y + 16, value, 17, INK, SANS, 700)
            + "</g>"
        )
    return svg(W, H, "Atividade por mês", "".join(parts), "", ("sg500", "sg700", "mono400"))


def stack(profile: dict) -> str:
    items = profile.get("stack", [])
    W = 840
    chip_h, gap, pad = 34, 10, 16
    x, y = 28, 64
    chips = []
    for i, item in enumerate(items):
        w = text_width(item["name"], "sg500", 14) + pad * 2 + 16
        if x + w > W - 28:
            x, y = 28, y + chip_h + gap
        chips.append(
            f'<g class="pop" style="{d(T_STACK + 0.15 + i * 0.09)}">'
            f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{chip_h}" rx="17" fill="{PANEL}" stroke="{BORDER}"/>'
            f'<circle cx="{x + pad + 4:.1f}" cy="{y + chip_h / 2}" r="4.5" fill="{item.get("color") or MUTED}"/>'
            + t(x + pad + 16, y + 22, item["name"], 14, INK, SANS, 500)
            + "</g>"
        )
        x += w + gap
    H = y + chip_h + 24
    body = (
        f'<g class="fu" style="{d(T_STACK)}">'
        + t(28, 42, "Ferramentas & Tecnologias", 20, INK, SANS, 700)
        + "</g>"
        + "".join(chips)
    )
    return svg(W, int(H), "Ferramentas e tecnologias: " + ", ".join(i["name"] for i in items), body, "", ("sg500", "sg700"))


def repo_card(repo: dict, delay: float) -> str:
    W, H = 412, 156
    lang = repo.get("primaryLanguage") or {}
    desc = repo.get("description") or "Sem descrição."
    lines = wrap(desc, "sg500", 13, W - 48)
    if len(lines) > 2:
        lines = lines[:2]
        while text_width(lines[1] + "…", "sg500", 13) > W - 48 and " " in lines[1]:
            lines[1] = lines[1].rsplit(" ", 1)[0]
        lines[1] += "…"
    name = repo["name"]
    ns = 18
    while text_width(name, "sg700", ns) > W - 80 and ns > 12:
        ns -= 1
    pushed = date.fromisoformat(repo["pushedAt"][:10])
    parts = [
        f'<g class="fu" style="{d(delay)}">',
        f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="15" fill="{PANEL}" stroke="{BORDER}"/>',
        t(24, 26 + 14, "repo", 11, DIM, MONO),
        t(24, 64, name, ns, INK, SANS, 700),
        f'<g class="nudge" style="{d(delay + 1.2)}">' + t(W - 24, 40, "↗", 16, MUTED, SANS, 700, "end") + "</g>",
    ]
    for i, line in enumerate(lines):
        parts.append(t(24, 88 + i * 18, line, 13, MUTED, SANS, 500))
    fx = 24
    fy = H - 22
    if lang.get("name"):
        parts.append(f'<circle cx="{fx + 5}" cy="{fy - 4}" r="4.5" fill="{MUTED}"/>')
        parts.append(t(fx + 16, fy, lang["name"], 12, INK, MONO))
        fx += 16 + text_width(lang["name"], "mono400", 12) + 18
    parts.append(t(fx, fy, f"★ {repo.get('stargazerCount', 0)}", 12, MUTED, MONO))
    parts.append(
        t(W - 24, fy, f"atualizado {MONTHS[pushed.month - 1]} {pushed.year}", 11, DIM, MONO, anchor="end")
    )
    parts.append("</g>")
    return svg(W, H, f"{name}: {desc}", "".join(parts), "", ("sg500", "sg700", "mono400"))


# ---------------------------------------------------------------- readme

START, END = "<!-- cards:start -->", "<!-- cards:end -->"


def readme_block(profile: dict, data: dict) -> str:
    user = profile["username"]
    url = f"https://github.com/{user}"
    lines = [
        START,
        "<!-- Gerado por scripts/render_cards.py — edite o profile.json em vez deste bloco. -->",
        '<div align="center">',
        "",
        f'<img src="./cards/hero.svg" width="100%" alt="{escape(profile["name"])} — {escape(profile["role"])}" />',
        "",
        f'<img src="./cards/graph.svg" width="100%" alt="Gráfico de contribuições" />',
        "",
        f'<a href="{url}"><img src="./cards/tile-contributions.svg" width="32.5%" alt="Contribuições no último ano" /></a>',
        f'<a href="{url}?tab=repositories"><img src="./cards/tile-repos.svg" width="32.5%" alt="Repositórios públicos" /></a>',
        f'<a href="{url}"><img src="./cards/tile-streak.svg" width="32.5%" alt="Maior sequência" /></a>',
        "",
        '<img src="./cards/activity.svg" width="100%" alt="Atividade por mês" />',
        "",
        '<img src="./cards/stack.svg" width="100%" alt="Ferramentas e tecnologias" />',
        "",
    ]
    for i, repo in enumerate(data.get("featured", [])):
        lines.append(
            f'<a href="{repo["url"]}"><img src="./cards/repo-{i + 1}.svg" width="49.5%" alt="{escape(repo["name"])}" /></a>'
        )
    lines += ["", "</div>", END]
    return "\n".join(lines)


def update_readme(path: Path, block: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if START in text and END in text:
        head, rest = text.split(START, 1)
        _, tail = rest.split(END, 1)
        text = head + block + tail
    else:
        text = block + "\n\n" + text
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- sample data


def sample_data(profile: dict) -> dict:
    rng = random.Random(7)
    today = date.today()
    first = today - timedelta(days=364)
    first -= timedelta(days=(first.weekday() + 1) % 7)
    days = []
    dt = first
    while dt <= today:
        busy = 0.35 + 0.3 * ((dt.month % 5) / 4)
        c = 0 if rng.random() > busy else rng.choice([1, 1, 2, 3, 4, 6, 9, 14])
        days.append({"date": dt.isoformat(), "count": c})
        dt += timedelta(days=1)
    featured = [
        {
            "name": n,
            "description": "Exemplo de descrição do repositório para a prévia local dos cartões.",
            "url": f"https://github.com/{profile['username']}/{n}",
            "stargazerCount": rng.randint(0, 9),
            "forkCount": 0,
            "pushedAt": (today - timedelta(days=rng.randint(5, 300))).isoformat() + "T00:00:00Z",
            "primaryLanguage": {"name": rng.choice(["JavaScript", "TypeScript", "Python", "C#"]), "color": "#F1E05A"},
        }
        for n in profile.get("featured_repos", [])
    ]
    return {
        "total_contributions": sum(x["count"] for x in days),
        "public_repos": 24,
        "days": days,
        "featured": featured,
    }


# ---------------------------------------------------------------- main


def main() -> None:
    args = sys.argv[1:]
    sample = "--sample" in args
    out = ROOT / "cards"
    if "--out" in args:
        out = Path(args[args.index("--out") + 1]).resolve()

    profile = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
    data_path = ROOT / "data" / "github.json"
    if sample:
        data = sample_data(profile)
    elif data_path.exists():
        data = json.loads(data_path.read_text(encoding="utf-8"))
    else:
        sys.exit("data/github.json not found: run scripts/fetch_data.py first (or use --sample)")

    portrait_path = ROOT / "data" / "portrait.txt"
    portrait = portrait_path.read_text(encoding="utf-8").rstrip("\n").split("\n") if portrait_path.exists() else []

    stats = compute_stats(data)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("repo-*.svg"):
        old.unlink()

    cards = {
        "hero.svg": hero(profile, portrait),
        "graph.svg": graph(stats),
        "tile-contributions.svg": tile("CONTRIBUIÇÕES", stats["total"], "no último ano", ACCENT, T_TILES),
        "tile-repos.svg": tile("REPOSITÓRIOS", stats["public_repos"], "públicos", ACCENT, T_TILES + 0.15),
        "tile-streak.svg": tile("MAIOR SEQUÊNCIA", stats["longest_streak"], "dias seguidos", ACCENT, T_TILES + 0.3),
        "activity.svg": activity(stats),
        "stack.svg": stack(profile),
    }
    for i, repo in enumerate(data.get("featured", [])):
        cards[f"repo-{i + 1}.svg"] = repo_card(repo, T_REPOS + i * 0.12)

    for name, content in cards.items():
        (out / name).write_text(content, encoding="utf-8")
    print(f"wrote {len(cards)} cards to {out}")

    if not sample and out == ROOT / "cards":
        update_readme(ROOT / "README.md", readme_block(profile, data))
        print("updated README.md")


if __name__ == "__main__":
    main()
