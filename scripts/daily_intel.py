#!/usr/bin/env python3
"""Daily intelligence briefing delivered by Hermes cron."""

import datetime
import json
import os
import re
import subprocess
import urllib.request

USER = os.environ.get("GITHUB_USER", "")
REPOS = [repo for repo in os.environ.get("INTEL_REPOS", "").split(",") if repo]
ARXIV_CATS = os.environ.get("ARXIV_CATEGORIES", "cat:cs.AI+OR+cat:cs.CL+OR+cat:cs.CR+OR+cat:cs.SE")


def run(cmd, timeout=25):
    try:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        ).stdout.strip()
    except Exception as e:
        return f"(err: {e})"


def build_briefing(
    user=USER,
    repos=REPOS,
    arxiv_categories=ARXIV_CATS,
    runner=run,
    opener=urllib.request.urlopen,
    today=None,
):
    today = today or datetime.date.today()
    lines = [f"🔥 DAILY INTEL — {today.strftime('%B %d, %Y')}\n", "📦 GITHUB"]
    found = False
    for repo in repos if user else []:
        spec = f"--repo {user}/{repo}"
        responses = (
            runner(f"gh issue list {spec} --assignee @me --state open --json title,url --limit 5"),
            runner(f"gh pr list {spec} --assignee @me --state open --json title,url --limit 5"),
        )
        for raw in responses:
            if not raw or not raw.startswith("["):
                continue
            try:
                items = json.loads(raw)
                for item in items:
                    lines.append(f"  • [{repo}] {item['title']}\n    {item['url']}")
                    found = True
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    if not found:
        lines.append("  no open issues/PRs assigned across tracked repos")

    lines.append("\n⏰ REMINDERS (today)")
    reminders = runner("remindctl today 2>/dev/null")
    lines.append(f"  {reminders if reminders else '(gate closed — run: remindctl authorize)'}")

    lines.append("\n📚 ARXIV (fresh)")
    url = (
        "http://export.arxiv.org/api/query?search_query="
        f"{arxiv_categories}&sortBy=submittedDate&max_results=6&sortOrder=descending"
    )
    try:
        raw = opener(url, timeout=15).read().decode()
        for title in re.findall(r"<title>(.*?)</title>", raw)[1:7]:
            lines.append(f"  • {title.strip()}")
    except Exception as error:
        lines.append(f"  (arxiv fetch failed: {error})")
    return "\n".join(lines)


def main():
    print(build_briefing())


if __name__ == "__main__":
    main()
