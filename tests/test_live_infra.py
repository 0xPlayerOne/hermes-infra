import json
import os
import subprocess
import time
import urllib.request

import pytest

pytestmark = pytest.mark.live


def launchd_details(label):
    return subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def pid_for(label):
    for line in launchd_details(label).splitlines():
        if line.strip().startswith("pid = "):
            return int(line.split("=", 1)[1].strip())
    return None


@pytest.fixture(autouse=True)
def require_live_services():
    if os.environ.get("HERMES_LIVE_TESTS") != "1":
        pytest.skip("set HERMES_LIVE_TESTS=1 to test local launchd services")


def test_tei_is_local_and_serves_embeddings():
    details = launchd_details("com.hermes.tei")
    assert "state = running" in details
    assert "target/release/hermes-infra" in details
    with urllib.request.urlopen("http://127.0.0.1:6999/health", timeout=10) as response:
        assert response.status == 200
    request = urllib.request.Request(
        "http://127.0.0.1:6999/v1/embeddings",
        data=json.dumps({"model": "Qwen/Qwen3-Embedding-0.6B", "input": ["live test"]}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read())
    assert len(data["data"][0]["embedding"]) == 1024


def test_index_watcher_stays_alive():
    details = launchd_details("com.hermes.code-index-watcher")
    assert "state = running" in details
    assert "target/release/hermes-infra" in details
    first = pid_for("com.hermes.code-index-watcher")
    time.sleep(10)
    assert pid_for("com.hermes.code-index-watcher") == first


def test_indexer_status_uses_repo_environment():
    root = os.environ.get("HERMES_INFRA_DIR", os.getcwd())
    venv = os.environ.get("HERMES_INFRA_VENV", os.path.join(root, ".venv"))
    result = subprocess.run(
        [os.path.join(venv, "bin/python"), os.path.join(root, "code-index/indexer.py"), "--status"],
        env={**os.environ, "HERMES_INFRA_DIR": root},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Model: Qwen/Qwen3-Embedding-0.6B" in result.stdout
    assert "Total chunks in store:" in result.stdout
