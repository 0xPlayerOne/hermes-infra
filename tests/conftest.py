import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(relative_path, name=None):
    path = ROOT / relative_path
    module_name = name or f"test_{path.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


@pytest.fixture
def load_script(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_INFRA_DIR", str(ROOT))
    monkeypatch.setenv("DEV_ROOT", str(tmp_path / "code"))
    monkeypatch.setenv("SECOND_BRAIN_DIR", str(tmp_path / "brain"))
    monkeypatch.setenv("DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("WORK_SECTION", "Work")
    monkeypatch.setenv("PERSONAL_SECTION", "Personal")
    monkeypatch.setenv("SPECIAL_SECTION", "Special")
    monkeypatch.setenv("GOOGLE_WORK_ACCOUNT", "work-account")
    monkeypatch.setenv("GOOGLE_PERSONAL_ACCOUNT", "personal-account")
    monkeypatch.setenv("GOOGLE_SPECIAL_ACCOUNT", "special-account")
    monkeypatch.setenv("WORK_ROUTE_KEYWORDS", "work,business")
    monkeypatch.setenv("SPECIAL_ROUTE_KEYWORDS", "special,cards")

    def loader(path, name=None):
        return load_module(path, name)

    return loader
