import os
import subprocess
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


@pytest.fixture(autouse=True)
def require_live_services():
    if os.environ.get("HERMES_LIVE_TESTS") != "1":
        pytest.skip("set HERMES_LIVE_TESTS=1 to test local launchd services")


def test_cortana_server_is_supervised_and_ready():
    details = launchd_details("ai.cortana.server")
    assert "state = running" in details
    with urllib.request.urlopen("http://127.0.0.1:7331/readyz", timeout=10) as response:
        assert response.status == 200


def test_cortana_owns_the_embedding_service():
    details = launchd_details("ai.cortana.embedding")
    assert "state = running" in details
    with urllib.request.urlopen("http://127.0.0.1:6999/health", timeout=10) as response:
        assert response.status == 200
