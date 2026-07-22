#!/usr/bin/env python3
"""Render and reconcile repository-owned launchd jobs."""

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "launchd"
DEFAULT_JOBS = sorted(TEMPLATE_DIR.glob("*.plist.example"))


def load_env(path):
    values = dict(os.environ)
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = os.path.expanduser(os.path.expandvars(
                value.strip().strip('"').strip("'")))
    return values


def render(template, values):
    text = template.read_text(encoding="utf-8")
    replacements = {
        "/path/to/hermes-infra": str(ROOT),
        "/path/to/.hermes": os.path.expanduser(values.get("HERMES_HOME", "~/.hermes")),
        "/path/to/.cargo": os.path.expanduser("~/.cargo"),
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    document = plistlib.loads(text.encode())
    return plistlib.dumps(document, fmt=plistlib.FMT_XML, sort_keys=False)


def active_path(template, values):
    launch_agents = Path(os.path.expanduser(os.path.expandvars(
        values.get("HERMES_LAUNCH_AGENTS_DIR", "~/Library/LaunchAgents"))))
    return launch_agents / template.name.removesuffix(".example")


def job_label(document):
    return document["Label"]


def check(jobs, values):
    drift = []
    for template in jobs:
        expected = render(template, values)
        destination = active_path(template, values)
        if not destination.exists():
            drift.append(f"missing: {destination}")
            continue
        try:
            actual = plistlib.loads(destination.read_bytes())
            expected_document = plistlib.loads(expected)
        except (OSError, plistlib.InvalidFileException) as error:
            drift.append(f"invalid: {destination}: {error}")
            continue
        if actual != expected_document:
            drift.append(f"drift: {destination}")
    if drift:
        for item in drift:
            print(item)
        return 1
    print(f"launchd check passed: {len(jobs)} jobs")
    return 0


def install(jobs, values):
    uid = str(os.getuid())
    for template in jobs:
        destination = active_path(template, values)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(render(template, values))
        document = plistlib.loads(destination.read_bytes())
        label = job_label(document)
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}/{label}"],
            capture_output=True, check=False)
        result = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(destination)],
            capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(f"bootstrap failed for {label}: {result.stderr.strip()}")
        print(f"installed: {label}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report drift without changing launchd")
    parser.add_argument("--install", action="store_true", help="render and bootstrap launchd jobs")
    parser.add_argument("--job", action="append", help="limit to a plist filename or label")
    args = parser.parse_args(argv)
    if args.check == args.install:
        parser.error("choose exactly one of --check or --install")

    values = load_env(ROOT / ".env")
    jobs = DEFAULT_JOBS
    if args.job:
        selected = set(args.job)
        jobs = [job for job in jobs if job.name in selected or job.name.removesuffix(".plist.example") in selected]
        if not jobs:
            parser.error("no matching launchd jobs")
    return check(jobs, values) if args.check else install(jobs, values)


if __name__ == "__main__":
    sys.exit(main())
