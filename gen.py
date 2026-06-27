#!/usr/bin/env python3
import os, sys, json, html, time, argparse, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
import hashlib

API = "https://api.github.com"
CACHE_DIR = ".cache"


def req(path, token, params=None):
    if path.startswith("http"):
        url = path
    else:
        url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    print(url)
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cache_path = os.path.join(CACHE_DIR, cache_key + ".json")

    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                # Corrupt cache entry; fall through and refresh from network.
                pass

    r = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            **(
                {
                    "Authorization": f"Bearer {token}",
                }
                if token
                else {}
            ),
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-stats-svg",
        },
    )
    with urllib.request.urlopen(r) as resp:
        data = json.loads(resp.read())

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    return data


def search_count(q, token):
    return req("/search/issues", token, {"q": q, "per_page": 1})["total_count"]


def window_counts(kind, user, token):
    # kind: "issue" or "pr"
    base = f"author:{user} type:{kind}"
    if kind == "pr":
        qs = {
            "open": base + " is:open",
            "merged": base + " is:merged",
            "closed": base + " is:closed -is:merged",
            "draft": base + " is:draft",
        }
    else:
        qs = {
            "open": base + " is:open",
            "closed": base + " is:closed",
            "draft": base + " is:draft",
        }
    return {k: search_count(v, token) for k, v in qs.items()}


def all_repos(user, token):
    repos, page = [], 1
    while True:
        xs = req(
            f"/users/{user}/repos",
            token,
            {
                "type": "owner",
                "sort": "updated",
                "per_page": 100,
                "page": page,
            },
        )
        if not xs:
            break
        repos.extend(xs)
        page += 1
    return repos


def language_stats(user, token, ignores=frozenset(["HTML", "Component Pascal"])):
    totals = {}
    for repo in all_repos(user, token):
        if repo.get("fork"):
            continue
        langs = req(f"/repos/{user}/{repo['name']}/languages", token)
        for lang, n in langs.items():
            if lang in ignores:
                continue
            totals[lang] = totals.get(lang, 0) + n
    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))


# def recent_activity(user, token, limit=5):
#     evs = req(f"/users/{user}/events/public", token, {"per_page": min(limit, 30)})
#     out = []
#     for e in evs[:limit]:
#         typ = e["type"].replace("Event", "")
#         repo = e["repo"]["name"]
#         created = e["created_at"][:10]
#         out.append(f"{created} · {typ} · {repo}")
#     return out


def bar(x, y, w, h, parts):
    total = sum(v for _, v, _ in parts) or 1
    cur, s = x, ""
    for label, val, color in parts:
        ww = w * val / total
        s += f'<rect x="{cur:.1f}" y="{y}" width="{ww:.1f}" height="{h}" rx="4" fill="{color}"/>'
        cur += ww
    return s


def text(
    x,
    y,
    s,
    size=16,
    fill="#0969da",
    weight="400",
    anchor="start",
    italic=False,
    raw=False,
):
    if not raw:
        s = html.escape(str(s))
    st = f"font-size:{size}px;font-weight:{weight};fill:{fill}"
    if italic:
        st += ";font-style:italic"
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}" style="{st}">{s}</text>'


def get_lang_colors():
    import yaml

    with open("languages.yml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


def make_svg(user, langs, issues, prs):
    W, H = 600, 390
    top_langs = list(langs.items())[:8]
    lang_total = sum(v for _, v in top_langs) or 1
    lang_colors_map = get_lang_colors()
    colors = [
        lang_colors_map.get(lang, {}).get("color", "#000000") for lang, _ in top_langs
    ]

    svg = [
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<style>
text {{ font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }}
.small {{ font-size:14px; fill:#57606a; }}
</style>
<rect width="100%" height="100%" fill="white"/>"""
    ]

    svg += [
        text(60, 40, f"Most Used Languages ({len(langs)} in Total)", 18),
    ]

    y = 75
    for i, (lang, n) in enumerate(top_langs):
        if i % 2 == 0:
            dx = dy = 0
        else:
            dx = 280
            dy = 24

        pct = n / lang_total * 100
        svg.append(
            f'<circle cx="{70+dx}" cy="{y-5}" r="6" fill="{colors[i % len(colors)]}"/>'
        )
        svg.append(text(85 + dx, y, f"{lang}", 14, "#24292f"))
        svg.append(text(250 + dx, y, f"{pct:.1f}%", 14, "#57606a"))
        y += dy

    svg += [
        text(60, 200, "Overall Issues and Pull Requests Status", 18),
        text(155, 240, "Issues", 15),
        bar(
            60,
            260,
            220,
            10,
            [
                ("open", issues.get("open", 0), "#1a7f37"),
                ("closed", issues.get("closed", 0), "#8250df"),
            ],
        ),
        text(60, 295, f"⬤ {issues.get('open',0)} open", 14, "#1a7f37"),
        text(180, 295, f"⬤ {issues.get('closed',0)} closed", 14, "#8250df"),
        text(60, 320, f"○ {issues.get('draft',0)} drafts", 14, "#57606a"),
        text(180, 320, f"○ {issues.get('skipped',0)} skipped", 14, "#57606a"),
        text(430, 240, "Pull requests", 15),
        bar(
            350,
            260,
            220,
            10,
            [
                ("open", prs.get("open", 0), "#1a7f37"),
                ("closed", prs.get("closed", 0), "#d1242f"),
                ("merged", prs.get("merged", 0), "#8250df"),
            ],
        ),
        text(350, 295, f"⬤ {prs.get('open',0)} open", 14, "#1a7f37"),
        text(470, 295, f"⬤ {prs.get('merged',0)} merged", 14, "#8250df"),
        text(350, 320, f"○ {prs.get('draft',0)} drafts", 14, "#57606a"),
        text(470, 320, f"⬤ {prs.get('closed',0)} closed", 14, "#d1242f"),
        # text(680, 235, "Recent activity", 18),
    ]

    # ay = 275
    # if activity:
    #     for a in activity:
    #         svg.append(text(680, ay, a, 13, "#57606a"))
    #         ay += 26
    # else:
    #     svg.append(text(680, ay, "No recent public activity found", 14, "#57606a"))

    svg.append("</svg>")
    return "\n".join(svg)


def get_issues_and_prs(user, token):
    data = req("/search/issues", token, {"q": f"author:{user}"})
    items = data.get("items", [])
    return items


ACTIVITY_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">
                        <path fill-rule="evenodd" d="M0 8a8 8 0 1116 0v5.25a.75.75 0 01-1.5 0V8a6.5 6.5 0 10-13 0v5.25a.75.75 0 01-1.5 0V8zm5.5 4.25a.75.75 0 01.75-.75h3.5a.75.75 0 010 1.5h-3.5a.75.75 0 01-.75-.75zM3 6.75C3 5.784 3.784 5 4.75 5h6.5c.966 0 1.75.784 1.75 1.75v1.5A1.75 1.75 0 0111.25 10h-6.5A1.75 1.75 0 013 8.25v-1.5zm1.47-.53a.75.75 0 011.06 0l.97.97.97-.97a.75.75 0 011.06 0l.97.97.97-.97a.75.75 0 111.06 1.06l-1.5 1.5a.75.75 0 01-1.06 0L8 7.81l-.97.97a.75.75 0 01-1.06 0l-1.5-1.5a.75.75 0 010-1.06z"/>
                    </svg>"""
PR_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">
                                        <path fill-rule="evenodd" d="M11.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 2.25 0 113 2.122V6A2.5 2.5 0 0110 8.5H6a1 1 0 00-1 1v1.128a2.251 2.251 0 11-1.5 0V5.372a2.25 2.25 0 111.5 0v1.836A2.492 2.492 0 016 7h4a1 1 0 001-1v-.628A2.25 2.25 0 019.5 3.25zM4.25 12a.75.75 0 100 1.5.75.75 0 000-1.5zM3.5 3.25a.75.75 0 111.5 0 .75.75 0 01-1.5 0z"/>
                                    </svg>"""
ISSUE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">
                                        <path fill-rule="evenodd" d="M7.177 3.073L9.573.677A.25.25 0 0110 .854v4.792a.25.25 0 01-.427.177L7.177 3.427a.25.25 0 010-.354zM3.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 2.25 0 113 2.122v5.256a2.251 2.251 0 11-1.5 0V5.372A2.25 2.25 0 011.5 3.25zM11 2.5h-1V4h1a1 1 0 011 1v5.628a2.251 2.251 0 101.5 0V5A2.5 2.5 0 0011 2.5zm1 10.25a.75.75 0 111.5 0 .75.75 0 01-1.5 0zM3.75 12a.75.75 0 100 1.5.75.75 0 000-1.5z"/>
                                    </svg>"""


def make_act_svg(activity):
    W, H = 600, 390
    svg = [
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<style>
text {{ font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }}
.small {{ font-size:14px; fill:#57606a; }}
.issue {{  font-size:14px; fill:#0969da; }}
</style>""",
        """<style>@keyframes animation-gauge{0%{stroke-dasharray:0 329}}@keyframes animation-rainbow{0%,to{color:#7f00ff;fill:#7f00ff}14%{color:#a933ff;fill:#a933ff}29%{color:#007fff;fill:#007fff}43%{color:#00ff7f;fill:#00ff7f}57%{color:#ff0;fill:#ff0}71%{color:#ff7f00;fill:#ff7f00}86%{color:red;fill:red}}svg{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif,Apple Color Emoji,Segoe UI Emoji;font-size:14px;color:#777}h2{margin:8px 0 2px;padding:0;color:#0366d6;font-weight:400;font-size:16px}h2 svg{fill:currentColor}section>.field{margin-left:5px;margin-right:5px}.field{display:flex;align-items:center;margin-bottom:2px;white-space:nowrap}.field svg{margin:0 8px;fill:#959da5;flex-shrink:0}.row{display:flex;flex-wrap:wrap}.row section{flex:1 1 0}#metrics-end,.fill-width{width:100%}.activity{margin-bottom:12px}.activity .field{width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:0}.activity .field .content{flex-grow:1;text-overflow:ellipsis;overflow:hidden}.activity .issue,.activity .repo{display:inline;color:#58a6ff}.activity .code,code,span.code{background-color:#7777771f;border-radius:6px;color:#777;padding:1px 5px;font-size:80%;font-family:SFMono-Regular,Consolas,Liberation Mono,Menlo,monospace}.activity .code,span.code{margin:0 4px -3px}.activity .details{padding-left:38px;display:flex;flex-direction:column;font-size:13px;color:#666}code{display:inline-block}:root{--color-calendar-graph-day-bg:#ebedf0;--color-calendar-graph-day-border:rgba(27,31,35,0.06);--color-calendar-graph-day-L1-bg:#9be9a8;--color-calendar-graph-day-L2-bg:#40c463;--color-calendar-graph-day-L3-bg:#30a14e;--color-calendar-graph-day-L4-bg:#216e39;--color-calendar-halloween-graph-day-L1-bg:#ffee4a;--color-calendar-halloween-graph-day-L2-bg:#ffc501;--color-calendar-halloween-graph-day-L3-bg:#fe9600;--color-calendar-halloween-graph-day-L4-bg:#03001c;--color-calendar-winter-graph-day-L1-bg:#0a3069;--color-calendar-winter-graph-day-L2-bg:#0969da;--color-calendar-winter-graph-day-L3-bg:#54aeff;--color-calendar-winter-graph-day-L4-bg:#b6e3ff;--color-calendar-graph-day-L4-border:rgba(27,31,35,0.06);--color-calendar-graph-day-L3-border:rgba(27,31,35,0.06);--color-calendar-graph-day-L2-border:rgba(27,31,35,0.06);--color-calendar-graph-day-L1-border:rgba(27,31,35,0.06)}</style>""",
        """
<rect width="100%" height="100%" fill="white"/>
<foreignObject x="0" y="0" width="100%" height="100%">
<div xmlns="http://www.w3.org/1999/xhtml" class="item-wrapper">
""",
        "<section>",
    ]
    svg += [
        f'<h2 class="field">{ACTIVITY_SVG}Recent Activity</h2>',
        '<div class="row">',
        "<section>",
    ]
    ay = 0
    for a in activity:
        svg += [
            '<div class="row fill-width">',
            '<section class="activity">',
            '<div class="field">',
        ]
        if "pull_request" in a:
            svg.append(PR_SVG)
        else:
            svg.append(ISSUE_SVG)
        t = f'<div class="content">Opened <span class="issue">#{a["number"]} {a["title"]}</span></div></div>'
        svg.append(t)
        svg.append(
            f'<div class="details"><div>in <span class="repo">{a["repository_url"].replace("https://api.github.com/repos/", "")}</span></div></div>'
        )
        svg += ["</section></div>"]
        ay += 26
    svg += ["</section>", "</div>", "</section>"]
    svg.append("</div></foreignObject></svg>")
    return "\n".join(svg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-u", "--user", default="hsfzxjy")
    ap.add_argument("-os", "--output-stats", default="github-stats.svg")
    ap.add_argument("-oa", "--output-activity", default="github-activity.svg")
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        with open(".token", "r", encoding="utf-8") as f:
            token = f.read().strip()
    if not token:
        sys.exit("Set GH_TOKEN or GITHUB_TOKEN")

    langs = language_stats(args.user, token)
    issues = window_counts("issue", args.user, token)
    prs = window_counts("pr", args.user, token)
    svg = make_svg(args.user, langs, issues, prs)
    with open(args.output_stats, "w", encoding="utf-8") as f:
        f.write(svg)
    act = get_issues_and_prs(args.user, "")
    svg = make_act_svg(act)
    with open(args.output_activity, "w", encoding="utf-8") as f:
        f.write(svg)


if __name__ == "__main__":
    main()
