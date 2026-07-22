#!/usr/bin/env python3
"""Daily intelligence briefing delivered by Hermes cron."""
import os, subprocess, json, urllib.request, datetime, re, sys

USER = os.environ.get("GITHUB_USER", "")
REPOS = [repo for repo in os.environ.get("INTEL_REPOS", "").split(",") if repo]
ARXIV_CATS = os.environ.get("ARXIV_CATEGORIES", "cat:cs.AI+OR+cat:cs.CL+OR+cat:cs.CR+OR+cat:cs.SE")

def run(cmd, timeout=25):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception as e:
        return f"(err: {e})"

lines = [f"🔥 DAILY INTEL — {datetime.date.today().strftime('%B %d, %Y')}\n"]

# 1. GitHub issues + PRs across repos
lines.append("📦 GITHUB")
found = False
for r in REPOS if USER else []:
    spec = f"--repo {USER}/{r}"
    issues = run(f"gh issue list {spec} --assignee @me --state open --json title,url --limit 5")
    prs = run(f"gh pr list {spec} --assignee @me --state open --json title,url --limit 5")
    for raw in (issues, prs):
        if raw and raw.startswith("["):
            try:
                for it in json.loads(raw):
                    lines.append(f"  • [{r}] {it['title']}\n    {it['url']}")
                    found = True
            except: pass
if not found:
    lines.append("  no open issues/PRs assigned across tracked repos")

# 2. Apple Reminders (today)
lines.append("\n⏰ REMINDERS (today)")
rem = run("remindctl today 2>/dev/null")
lines.append(f"  {rem if rem else '(gate closed — run: remindctl authorize)'}")

# 3. arXiv fresh papers
lines.append("\n📚 ARXIV (fresh)")
url = f"http://export.arxiv.org/api/query?search_query={ARXIV_CATS}&sortBy=submittedDate&max_results=6&sortOrder=descending"
try:
    raw = urllib.request.urlopen(url, timeout=15).read().decode()
    titles = re.findall(r"<title>(.*?)</title>", raw)[1:]
    for t in titles[:6]:
        lines.append(f"  • {t.strip()}")
except Exception as e:
    lines.append(f"  (arxiv fetch failed: {e})")

print("\n".join(lines))
