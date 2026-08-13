import json
from pathlib import Path

from scripts import cron_io


def test_default_jobs_file_is_under_hermes_home():
    assert str(cron_io.DEFAULT_JOBS_FILE).startswith(str(Path.home()))


def test_load_jobs_handles_wrapped_dict(tmp_path):
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text(json.dumps({"jobs": [{"name": "a"}], "updated_at": "x"}))
    jobs, data = cron_io.load_jobs(jobs_file)
    assert jobs == [{"name": "a"}]
    assert data["updated_at"] == "x"


def test_load_jobs_handles_bare_list(tmp_path):
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text(json.dumps([{"name": "a"}, {"name": "b"}]))
    jobs, data = cron_io.load_jobs(jobs_file)
    assert jobs == [{"name": "a"}, {"name": "b"}]
    assert data == [{"name": "a"}, {"name": "b"}]


def test_save_jobs_preserves_original_wrapper(tmp_path):
    jobs_file = tmp_path / "jobs.json"
    original = {"jobs": [{"name": "a"}], "updated_at": "2024-01-01"}
    jobs_file.write_text(json.dumps(original))
    _, data = cron_io.load_jobs(jobs_file)
    data["updated_at"] = "2024-01-02"
    cron_io.save_jobs(jobs_file, data)
    reloaded = json.loads(jobs_file.read_text())
    assert reloaded["jobs"] == [{"name": "a"}]
    assert reloaded["updated_at"] == "2024-01-02"
