"""Write the night's report as one self-contained HTML page: occupancy timeline, the presences nobody walked to, the
story and its fact check.

usage: python report.py EVENTS_JSON STORY_JSON OUT_HTML
"""
import html
import json
import sys

ROOMS = [("bedroom", "Bedroom"), ("hallway", "Hallway"), ("kitchen", "Kitchen"), ("living_room", "Living room")]


def minute_of(clock):
    h, m = map(int, clock.split(":"))
    return (h - 22) * 60 + m if h >= 22 else (h + 2) * 60 + m


def timeline_svg(report):
    left, top, row_h, gap, scale = 112, 28, 34, 10, 1.6
    width = left + int(540 * scale) + 16
    height = top + len(ROOMS) * (row_h + gap) + 26
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="tl-title tl-desc" class="timeline">',
             '<title id="tl-title">Occupancy by room, 22:00 to 07:00</title>',
             '<desc id="tl-desc">Each strip shows how likely TabPFN thinks the room was occupied, minute by minute. '
             'Outlined blocks mark presences nobody walked to.</desc>']
    for hour in range(10):
        x = left + hour * 60 * scale
        label = f"{(22 + hour) % 24:02d}:00"
        parts.append(f'<line x1="{x:.1f}" y1="{top - 6}" x2="{x:.1f}" y2="{height - 22}" class="grid"/>')
        parts.append(f'<text x="{x:.1f}" y="{top - 12}" class="tick">{label}</text>')
    for i, (key, name) in enumerate(ROOMS):
        y = top + i * (row_h + gap)
        parts.append(f'<text x="{left - 12}" y="{y + row_h / 2 + 5:.1f}" class="room">{name}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{540 * scale:.1f}" height="{row_h}" class="lane"/>')
        series = report["timeline"][key]
        band = [min(4, int(p * 5)) if p >= 0.05 else -1 for p in series]  # five opacity bands, -1 = nothing drawn
        start = 0
        for minute in range(1, len(band) + 1):
            if minute == len(band) or band[minute] != band[start]:
                if band[start] >= 0:
                    parts.append(f'<rect x="{left + start * scale:.1f}" y="{y}" width="{(minute - start) * scale:.1f}" '
                                 f'height="{row_h}" class="occ" fill-opacity="{(band[start] + 1) / 5:.2f}"/>')
                start = minute
    for e in report["events"]:
        if e["kind"] != "unexplained":
            continue
        i = [k for k, _ in ROOMS].index(e["room"])
        y = top + i * (row_h + gap)
        x0 = left + minute_of(e["start"]) * scale
        w = max(4.0, e.get("minutes", 1) * scale)
        parts.append(f'<rect x="{x0 - 2:.1f}" y="{y - 3}" width="{w + 4:.1f}" height="{row_h + 6}" class="ghost"/>')
        parts.append(f'<text x="{x0 + w / 2:.1f}" y="{y + row_h + 16}" class="ghost-label">{e["start"]}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    events_path, story_path, out = sys.argv[1:4]
    report = json.load(open(events_path))
    story = json.load(open(story_path))
    esc = html.escape
    ghosts = [e for e in report["events"] if e["kind"] == "unexplained"]
    rows = []
    for e in ghosts:
        readings = []
        if "co2_change_ppm" in e:
            readings = [f"CO₂ +{e['co2_change_ppm']:g} ppm", f"light ≤ {e['light_max_lux']:g} lux",
                        f"sound ≤ {e['sound_max_dba']:g} dBA", f"{e['motion_triggers']} motion triggers"]
        rows.append(f"<tr><td data-label=\"Time\">{esc(e['start'])}{'–' + esc(e['end']) if e['end'] != e['start'] else ''}</td>"
                    f"<td data-label=\"Room\">{esc(e['room'].replace('_', ' '))}</td><td data-label=\"Why it is strange\">{esc(e['why'])}</td>"
                    f"<td data-label=\"Readings\">{esc(', '.join(readings)) or '—'}</td></tr>")
    paragraphs = [p.strip() for p in story["story"].split("\n") if p.strip()]
    boring = [p for p in paragraphs if p.startswith("The boring explanation:")]
    tale = [p for p in paragraphs if not p.startswith("The boring explanation:")]
    c = story["check"]
    check_line = (f"Fact check passed: {c['times_quoted']} clock times and {c['readings_quoted']} readings in the story all appear "
                  f"in the evidence (attempt {len(story.get('attempts', [1]))})." if c["ok"] else
                  f"Fact check failed: times {c['times_not_in_evidence']}, readings {c['readings_not_in_evidence']}.")
    chk = report["check"]
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>What the House Heard: {esc(report['night'])}</title>
<style>
:root {{ --bg: #101114; --panel: #17191e; --ink: #ecebe6; --muted: #a3a29c; --line: #2b2e36; --occ: #8fb3d9;
        --ghost: #f2994a; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.55 ui-sans-serif, system-ui, -apple-system,
       "Segoe UI", sans-serif; }}
main {{ max-width: 1000px; margin: 0 auto; padding: 40px 20px 56px; }}
h1 {{ font: 600 2rem/1.15 ui-serif, Georgia, serif; margin: 0 0 6px; letter-spacing: 0.01em; }}
.sub {{ color: var(--muted); margin: 0 0 28px; }}
section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 20px 22px; margin: 0 0 18px; }}
h2 {{ font-size: 0.85rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin: 0 0 12px; font-weight: 600; }}
.timeline-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
.timeline {{ width: 100%; min-width: 720px; height: auto; display: block; }}
.timeline .grid {{ stroke: var(--line); stroke-width: 1; }}
.timeline .tick {{ fill: var(--muted); font-size: 11px; text-anchor: middle; }}
.timeline .room {{ fill: var(--ink); font-size: 13px; text-anchor: end; }}
.timeline .lane {{ fill: #1d2027; }}
.timeline .occ {{ fill: var(--occ); }}
.timeline .ghost {{ fill: none; stroke: var(--ghost); stroke-width: 2.5; rx: 3; }}
.timeline .ghost-label {{ fill: var(--ghost); font-size: 11px; text-anchor: middle; font-weight: 600; }}
.legend {{ color: var(--muted); font-size: 0.9rem; margin: 10px 0 0; }}
.swatch {{ display: inline-block; width: 12px; height: 12px; vertical-align: -1px; margin: 0 6px 0 0; border-radius: 2px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
th, td {{ text-align: left; padding: 9px 10px 9px 0; border-bottom: 1px solid var(--line); vertical-align: top; }}
th {{ color: var(--muted); font-weight: 600; font-size: 0.85rem; }}
td:first-child {{ white-space: nowrap; color: var(--ghost); font-variant-numeric: tabular-nums; }}
.story p {{ font: 1.08rem/1.7 ui-serif, Georgia, serif; margin: 0 0 14px; max-width: 70ch; }}
.boring {{ color: var(--muted); font-style: italic; }}
.check {{ font-size: 0.9rem; color: #9fd39f; margin: 6px 0 0; }}
.check.fail {{ color: #f08b8b; }}
footer {{ color: var(--muted); font-size: 0.85rem; margin-top: 22px; }}
footer strong {{ color: var(--ink); font-weight: 600; }}
@media (max-width: 640px) {{
  h1 {{ font-size: 1.6rem; }} section {{ padding: 16px; }}
  table, tbody, tr, td {{ display: block; }} thead {{ display: none; }}
  tr {{ padding: 10px 0; border-bottom: 1px solid var(--line); }}
  td {{ border: 0; padding: 2px 0; }}
  td::before {{ content: attr(data-label); display: block; color: var(--muted); font-size: 0.78rem; letter-spacing: 0.04em; }}
}}
</style>
</head>
<body>
<main>
<h1>What the House Heard</h1>
<p class="sub">Night of {esc(report['night'])}, 22:00 to 07:00. {len(ghosts)} unexplained events.</p>

<section aria-labelledby="h-timeline">
<h2 id="h-timeline">Who was where, minute by minute</h2>
<div class="timeline-wrap">{timeline_svg(report)}</div>
<p class="legend"><span class="swatch" style="background:var(--occ)"></span>TabPFN's occupancy probability (brighter means more likely)
&nbsp;&nbsp;<span class="swatch" style="border:2px solid var(--ghost)"></span>a presence nobody walked to</p>
</section>

<section aria-labelledby="h-events">
<h2 id="h-events">The evidence</h2>
<table>
<thead><tr><th>Time</th><th>Room</th><th>Why it is strange</th><th>Readings</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</section>

<section class="story" aria-labelledby="h-story">
<h2 id="h-story">What the house heard (told by Gemma 4, offline)</h2>
{''.join(f'<p>{esc(p)}</p>' for p in tale)}
{''.join(f'<p class="boring">{esc(p)}</p>' for p in boring)}
<p class="check{'' if c['ok'] else ' fail'}">{esc(check_line)}</p>
</section>

<footer>
<p><strong>Built with PriorLabs-TabPFN.</strong> Given six labelled nights in context, TabPFN v2 labelled the room-minutes
of a seventh, held-out night with {chk['balanced_accuracy']:.0%} balanced accuracy (synthetic data); the night above was
scored with all seven. The story was written by Gemma 4 12B (QAT, Q4_0) through llama.cpp on the same machine; no data
left it.</p>
<p>All sensor data on this page is synthetic, produced by <code>simulate.py</code>.</p>
</footer>
</main>
</body>
</html>
"""
    open(out, "w").write(page)
    print("wrote", out)


if __name__ == "__main__":
    main()
