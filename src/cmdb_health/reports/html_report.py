"""Self-contained HTML report (inline CSS/JS, no external assets)."""

from __future__ import annotations

from html import escape
from pathlib import Path

from cmdb_health.engine import HealthReport

_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2330;--muted:#5d6675;--line:#dde1e7;
--good:#1f7a4d;--warn:#a86400;--bad:#b42318;--track:#e7eaee;--accent:#2b5fab}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d2128;--ink:#e6e8eb;
--muted:#9aa3ae;--line:#2e343d;--good:#4fbf86;--warn:#e0a03a;--bad:#f07167;--track:#2a3038;--accent:#7aa7e8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:32px 0 12px}
.meta{color:var(--muted);font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.card .label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.card .score{font-size:32px;font-weight:650;font-variant-numeric:tabular-nums}
.track{height:8px;border-radius:4px;background:var(--track);overflow:hidden;margin-top:8px}
.fill{height:100%;border-radius:4px}
.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}
.bg-good{background:var(--good)}.bg-warn{background:var(--warn)}.bg-bad{background:var(--bad)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.sev{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid currentColor}
.table-wrap{overflow-x:auto}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
select,input{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px 8px;font:inherit}
code{font-size:12px;color:var(--muted)}
footer{margin-top:32px;color:var(--muted);font-size:12px}
"""

_JS = """
(function(){var s=document.getElementById('f-sev'),c=document.getElementById('f-check'),
q=document.getElementById('f-q'),rows=[].slice.call(document.querySelectorAll('#findings tbody tr')),
n=document.getElementById('f-count');function apply(){var v=0;rows.forEach(function(r){
var ok=(!s.value||r.dataset.sev===s.value)&&(!c.value||r.dataset.check===c.value)&&
(!q.value||r.textContent.toLowerCase().indexOf(q.value.toLowerCase())>-1);
r.style.display=ok?'':'none';if(ok)v++;});n.textContent=v+' shown';}
[s,c,q].forEach(function(e){e.addEventListener('input',apply);});apply();})();
"""


def _tone(score: float) -> str:
    if score >= 90:
        return "good"
    if score >= 75:
        return "warn"
    return "bad"


def _card(label: str, score: float) -> str:
    tone = _tone(score)
    return (
        f'<div class="card"><div class="label">{escape(label)}</div>'
        f'<div class="score {tone}">{score:.1f}</div>'
        f'<div class="track"><div class="fill bg-{tone}" style="width:{score:.1f}%"></div></div></div>'
    )


def render_html(report: HealthReport, title: str = "CMDB Health Report") -> str:
    sev_class = {"high": "bad", "medium": "warn", "low": "good"}
    cards = [_card("Overall", report.overall_score)]
    cards += [_card(dim.title(), score) for dim, score in report.dimension_scores.items()]

    check_rows = "".join(
        f"<tr><td><strong>{escape(r.title)}</strong><br><code>{escape(r.check_id)}</code></td>"
        f"<td>{escape(r.dimension.value.title())}</td><td class='num'>{r.evaluated}</td>"
        f"<td class='num'>{r.failing_cis}</td><td class='num {_tone(r.score)}'>{r.score:.1f}</td></tr>"
        for r in report.results
    )
    finding_rows = "".join(
        f"<tr data-sev='{f.severity.value}' data-check='{escape(f.check_id)}'>"
        f"<td><span class='sev {sev_class[f.severity.value]}'>{f.severity.value}</span></td>"
        f"<td><code>{escape(f.check_id)}</code></td>"
        f"<td>{escape(f.ci_name or '-')}<br><code>{escape(f.ci_sys_id)}</code></td>"
        f"<td>{escape(f.ci_class)}</td><td>{escape(f.message)}</td></tr>"
        for f in report.findings
    )
    check_options = "".join(
        f"<option value='{escape(r.check_id)}'>{escape(r.check_id)}</option>" for r in report.results
    )
    counts = report.severity_counts()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title><style>{_CSS}</style></head>
<body><main>
<h1>{escape(title)}</h1>
<div class="meta">Source: {escape(report.source)} &middot; As of {report.as_of:%Y-%m-%d %H:%M} UTC &middot;
{report.total_cis} CIs ({report.in_scope_cis} in scope) &middot; {report.total_relationships} relationships</div>
<section class="cards">{"".join(cards)}</section>
<h2>Checks</h2>
<div class="table-wrap"><table><thead><tr><th>Check</th><th>Dimension</th><th>Evaluated</th>
<th>Failing CIs</th><th>Score</th></tr></thead><tbody>{check_rows}</tbody></table></div>
<h2>Findings ({sum(counts.values())}: {counts["high"]} high, {counts["medium"]} medium, {counts["low"]} low)</h2>
<div class="filters">
<select id="f-sev" aria-label="Severity"><option value="">All severities</option>
<option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
<select id="f-check" aria-label="Check"><option value="">All checks</option>{check_options}</select>
<input id="f-q" type="search" placeholder="Search name, class, message" aria-label="Search">
<span id="f-count" class="meta"></span></div>
<div class="table-wrap"><table id="findings"><thead><tr><th>Severity</th><th>Check</th><th>CI</th>
<th>Class</th><th>Message</th></tr></thead><tbody>{finding_rows}</tbody></table></div>
<footer>Generated by cmdb-health. Scores are the share of evaluated CIs with no finding;
dimension scores average their checks.</footer>
</main><script>{_JS}</script></body></html>
"""


def write_html(report: HealthReport, path: str | Path, title: str = "CMDB Health Report") -> Path:
    path = Path(path)
    path.write_text(render_html(report, title), encoding="utf-8")
    return path
