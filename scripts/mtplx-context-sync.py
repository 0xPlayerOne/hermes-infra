#!/usr/bin/env python3
"""Keep MTPLX context window at per-family defaults when switching models.

The MTPLX app stores one context_window + context_window_model_family pair.
Switching between Qwen and Gemma drops the saved override and falls back to
262144. This script restores the per-family value from context-windows-by-family.json.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
from pathlib import Path

SETTINGS_PATH = Path(os.environ.get(
    "MTPLX_SETTINGS_PATH",
    Path.home() / "Library/Application Support/MTPLX/settings.json",
))
LOCK_PATH = Path(os.environ.get(
    "MTPLX_CONTEXT_SYNC_LOCK",
    Path.home() / "Library/Application Support/MTPLX/.context-sync.lock",
))
PREFS_PATH = Path(os.environ.get(
    "MTPLX_CONTEXT_PREFS_PATH",
    Path.home() / ".mtplx/context-windows-by-family.json",
))
DEFAULT_CONTEXT = 131072
MODEL_MAX_RESET = 262144


def infer_family(model_path: str, live_family: str | None) -> str | None:
    if live_family in {"qwen3_6", "qwen3_5", "gemma4"}:
        return live_family
    lowered = model_path.lower()
    if "gemma" in lowered:
        return "gemma4"
    if "qwen" in lowered:
        return "qwen3_6"
    return live_family


def load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def save_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")
    tmp.replace(path)


def load_family_prefs() -> dict[str, int]:
    raw = load_json(PREFS_PATH)
    prefs: dict[str, int] = {}
    for family in ("qwen3_6", "qwen3_5", "gemma4"):
        value = raw.get(family)
        if isinstance(value, int) and value > 0:
            prefs[family] = value
    if "qwen3_6" not in prefs:
        prefs["qwen3_6"] = DEFAULT_CONTEXT
    if "gemma4" not in prefs:
        prefs["gemma4"] = DEFAULT_CONTEXT
    return prefs


def remember_custom_context(
    prefs: dict[str, int],
    *,
    family: str | None,
    stored_family: str | None,
    context_window: int | None,
) -> bool:
    if family is None or stored_family != family:
        return False
    if context_window is None or context_window <= 0:
        return False
    if context_window == MODEL_MAX_RESET:
        return False
    if prefs.get(family) == context_window:
        return False
    prefs[family] = context_window
    return True


def sync_settings() -> int:
    if not SETTINGS_PATH.exists():
        return 0

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)

        settings = load_json(SETTINGS_PATH)
        prefs = load_family_prefs()

        model = str(settings.get("model") or "")
        live_family = settings.get("live_settings_model_family")
        live_family_str = str(live_family) if isinstance(live_family, str) else None
        family = infer_family(model, live_family_str)

        stored_family = settings.get("context_window_model_family")
        stored_family_str = (
            str(stored_family) if isinstance(stored_family, str) else None
        )
        context_raw = settings.get("context_window")
        context_window = int(context_raw) if isinstance(context_raw, int) else None

        prefs_changed = remember_custom_context(
            prefs,
            family=family,
            stored_family=stored_family_str,
            context_window=context_window,
        )
        if prefs_changed:
            save_json(PREFS_PATH, prefs)

        if family is None:
            return 0

        target = prefs.get(family, DEFAULT_CONTEXT)
        needs_update = (
            context_window != target or stored_family_str != family
        )
        if not needs_update:
            return 0

        settings["context_window"] = target
        settings["context_window_model_family"] = family
        save_json(SETTINGS_PATH, settings)
        return 1


def main() -> int:
    try:
        changed = sync_settings()
    except Exception as exc:  # noqa: BLE001 - launchd should log failures
        print(f"sync-context-window: {exc}", file=sys.stderr)
        return 1
    if changed:
        print("sync-context-window: restored per-family context window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
