import datetime
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Collection:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def upsert(self, **kwargs):
        if self.fail:
            raise RuntimeError("broken")
        self.calls.append(kwargs)


def module(load_script):
    return load_script("second-brain/scripts/google_sync.py")


def test_routes_special_work_and_personal(load_script):
    gs = module(load_script)
    assert gs.is_special("special cards")
    assert gs.is_work("work report", "")
    assert gs.route_text("special work") == "special"
    assert gs.route_text("business report") == "work"
    assert gs.route_text("ordinary") == "personal"


def test_null_collection(load_script):
    null = module(load_script)._NullCollection()
    assert null.upsert() is None
    assert null.delete() is None
    assert null.count() == 0
    assert null.get() == {}


def test_get_col_success_and_failure(load_script, monkeypatch):
    gs = module(load_script)
    collection = object()
    client = SimpleNamespace(get_or_create_collection=lambda name: collection)
    monkeypatch.setattr(gs.chromadb, "PersistentClient", lambda **kwargs: client)
    assert gs.get_col() is collection
    monkeypatch.setattr(gs.chromadb, "PersistentClient", lambda **kwargs: (_ for _ in ()).throw(RuntimeError()))
    assert isinstance(gs.get_col(), gs._NullCollection)


def test_embed_success_and_failure(load_script, monkeypatch):
    gs = module(load_script)
    payload = json.dumps({"data": [{"embedding": [1, 2]}, {"embedding": [3, 4]}]}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(payload))
    assert gs.embed(["a", "b"]) == [[1, 2], [3, 4]]
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert gs.embed(["a", "b"]) == [None, None]


def test_gapi_get_paths(load_script, monkeypatch):
    gs = module(load_script)
    assert gs.gapi_get("url", {}, "account") is None
    success = SimpleNamespace(returncode=0, stdout=b'{"ok": true}')
    monkeypatch.setattr(gs.subprocess, "run", lambda *a, **k: success)
    assert gs.gapi_get("url", {"token": "token"}, "account") == {"ok": True}
    success.stdout = b"raw"
    assert gs.gapi_get("url", {"token": "token"}, "account", raw=True) == b"raw"
    success.returncode = 1
    assert gs.gapi_get("url", {"token": "token"}, "account") is None


def test_gapi_get_retries_exceptions(load_script, monkeypatch):
    gs = module(load_script)
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise subprocess.TimeoutExpired("curl", 1)

    monkeypatch.setattr(gs.subprocess, "run", fail)
    monkeypatch.setattr(gs.time, "sleep", lambda _: None)
    assert gs.gapi_get("url", {"token": "token"}, "account") is None
    assert len(calls) == 3


def test_credentials_round_trip_and_refresh(load_script, tmp_path, monkeypatch):
    gs = module(load_script)
    gs.TOKEN_DIR = tmp_path / "tokens"
    gs.CREDS_FILE = tmp_path / "keys.json"
    assert gs.load_creds("missing") is None
    gs.save_creds("work", {"token": "old"})
    assert gs.load_creds("work") == {"token": "old"}
    creds = {"token": "old", "refresh_token": "refresh", "client_id": "id", "client_secret": "secret"}
    response = SimpleNamespace(stdout=json.dumps({"access_token": "new", "expires_in": 60}))
    monkeypatch.setattr(gs.subprocess, "run", lambda *a, **k: response)
    assert gs.refresh_token("work", creds)["token"] == "new"
    assert gs.load_creds("work")["token"] == "new"


def test_get_creds_refreshes_aware_and_naive_expiry(load_script, monkeypatch):
    gs = module(load_script)
    expired = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    monkeypatch.setattr(gs, "load_creds", lambda account: {"expiry": expired.isoformat()})
    monkeypatch.setattr(gs, "refresh_token", lambda account, creds: {"refreshed": True})
    assert gs.get_creds("work") == {"refreshed": True}
    monkeypatch.setattr(gs, "load_creds", lambda account: {"expiry": expired.replace(tzinfo=None).isoformat()})
    assert gs.get_creds("work") == {"refreshed": True}


def test_store_writes_chunks_skips_and_survives_chroma_failure(load_script, tmp_path, monkeypatch):
    gs = module(load_script)
    monkeypatch.setattr(gs, "embed", lambda chunks: [[1.0]] * len(chunks))
    col = Collection()
    body = "x" * 2600
    gs.store(col, "work", "Title", body, "doc", vault_dir=tmp_path)
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    assert len(col.calls[0]["ids"]) == 3
    gs.store(col, "work", "Title", body, "doc", vault_dir=tmp_path)
    assert len(col.calls) == 1
    gs.store(Collection(fail=True), "work", "Other", "body", "doc2", vault_dir=tmp_path)
    assert (tmp_path / "work-Other.md").exists()


def test_extract_doc_text(load_script):
    gs = module(load_script)
    doc = {"body": {"content": [
        {"paragraph": {"elements": [{"textRun": {"content": "hello "}}]}},
        {"table": {"tableRows": [{"tableCells": [{"content": [
            {"paragraph": {"elements": [{"textRun": {"content": "table"}}]}}
        ]}]}]}},
    ]}}
    assert gs.extract_doc_text(doc) == "hello table"
    assert gs.extract_doc_text({}) == ""


def test_meeting_and_safe_drive_helpers(load_script):
    gs = module(load_script)
    assert gs.is_meeting_doc("Team meeting transcript")
    assert not gs.is_meeting_doc("Quarterly budget")
    assert gs._safe_drive_part("a/b") == "a／b"
    assert gs._safe_drive_part("..") == "_"
    assert gs._safe_drive_part("") == "_"


def test_resolve_and_target_drive_paths(load_script, tmp_path):
    gs = module(load_script)
    gs.VAULT_SPECIAL_DRIVE = tmp_path / "special"
    assert gs._resolve_vault_dir(tmp_path, [], "cards") == tmp_path / "special"
    assert gs._resolve_vault_dir(tmp_path, [], "ordinary") == tmp_path
    assert gs._drive_target_dir(tmp_path, ["one", "a/b"], "ordinary") == tmp_path / "one" / "a／b"


def test_drive_list_paginates(load_script, monkeypatch):
    gs = module(load_script)
    responses = [
        {"files": [{"id": "1"}], "nextPageToken": "next"},
        {"files": [{"id": "2"}]},
    ]
    urls = []

    def get(url, *args, **kwargs):
        urls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(gs, "gapi_get", get)
    assert [item["id"] for item in gs._drive_list({}, "work")] == ["1", "2"]
    assert "pageToken=next" in urls[1]


def test_folder_all_images(load_script, monkeypatch):
    gs = module(load_script)
    monkeypatch.setattr(gs, "_drive_list", lambda *a, **k: [
        {"mimeType": "image/png"}, {"mimeType": "image/jpeg"}
    ])
    assert gs._folder_all_images({}, "work", "root")
    monkeypatch.setattr(gs, "_drive_list", lambda *a, **k: [{"mimeType": "text/plain"}])
    assert not gs._folder_all_images({}, "work", "root")


def test_sync_calendar_and_gmail(load_script, monkeypatch):
    gs = module(load_script)
    monkeypatch.setattr(gs, "get_creds", lambda account: {"token": "token"})
    monkeypatch.setattr(gs, "get_col", lambda: object())
    stored = []
    monkeypatch.setattr(gs, "store", lambda *args, **kwargs: stored.append((args, kwargs)))

    def api(url, *args, **kwargs):
        if "calendar" in url:
            return {"items": [{"id": "event", "summary": "Standup",
                                "start": {"dateTime": "today"}, "description": "desc"}]}
        if "messages?" in url:
            return {"messages": [{"id": "mail"}]}
        return {"snippet": "hello", "payload": {"headers": [
            {"name": "From", "value": "sender"}, {"name": "Subject", "value": "subject"}
        ]}}

    monkeypatch.setattr(gs, "gapi_get", api)
    gs.sync_calendar("work")
    gs.sync_gmail("work")
    assert len(stored) == 2
    monkeypatch.setattr(gs, "get_creds", lambda account: None)
    gs.sync_calendar("work")
    gs.sync_gmail("work")
    assert len(stored) == 2


def test_drive_file_and_sheet_fetch(load_script, monkeypatch, tmp_path):
    gs = module(load_script)
    stored = []
    monkeypatch.setattr(gs, "store", lambda *args, **kwargs: stored.append((args, kwargs)))
    monkeypatch.setattr(gs, "gapi_get", lambda *a, **k: b"plain text" if k.get("raw") else {"values": [["a", "b"], [1, 2]]})
    gs._drive_fetch_file({}, "work", object(), "id", "image", "image/png", tmp_path)
    assert not stored
    gs._drive_fetch_file({}, "work", object(), "id", "text", "text/plain", tmp_path)
    gs._fetch_sheet({}, "work", object(), "sheet", "Sheet", tmp_path, "folder")
    assert len(stored) == 2
    assert "a\tb" in stored[1][0][3]


def test_refresh_missing_fields_and_get_creds_missing(load_script, tmp_path):
    gs = module(load_script)
    gs.CREDS_FILE = tmp_path / "missing.json"
    creds = {"token": "token"}
    assert gs.refresh_token("work", creds) is creds
    gs.TOKEN_DIR = tmp_path / "tokens"
    assert gs.get_creds("missing") is None


def test_drive_walk_dispatches_all_file_types(load_script, monkeypatch, tmp_path):
    gs = module(load_script)
    files = [
        {"id": "folder", "name": "Folder", "mimeType": "application/vnd.google-apps.folder"},
        {"id": "doc", "name": "Doc", "mimeType": "application/vnd.google-apps.document"},
        {"id": "sheet", "name": "Sheet", "mimeType": "application/vnd.google-apps.spreadsheet"},
        {"id": "text", "name": "Text", "mimeType": "text/plain"},
    ]
    lists = iter([files, []])
    monkeypatch.setattr(gs, "_drive_list", lambda *a, **k: next(lists))
    monkeypatch.setattr(gs, "_folder_all_images", lambda *a, **k: False)
    monkeypatch.setattr(gs, "gapi_get", lambda *a, **k: {
        "body": {"content": [{"paragraph": {"elements": [
            {"textRun": {"content": "doc text"}}
        ]}}]}})
    calls = []
    monkeypatch.setattr(gs, "store", lambda *a, **k: calls.append("doc"))
    monkeypatch.setattr(gs, "_fetch_sheet", lambda *a, **k: calls.append("sheet"))
    monkeypatch.setattr(gs, "_drive_fetch_file", lambda *a, **k: calls.append("file"))
    gs._drive_walk({}, "work", object(), "root", [], tmp_path, "drive")
    assert calls == ["doc", "sheet", "file"]


def test_sync_selects_account_root_and_handles_failure(load_script, monkeypatch, tmp_path):
    gs = module(load_script)
    monkeypatch.setattr(gs, "get_creds", lambda account: {"token": "token"})
    monkeypatch.setattr(gs, "get_col", lambda: object())
    calls = []
    monkeypatch.setattr(gs, "_drive_walk", lambda *a, **k: calls.append((a, k)))
    gs.sync(gs.WORK_ACCOUNT)
    gs.sync(gs.SPECIAL_ACCOUNT)
    gs.sync(gs.PERSONAL_ACCOUNT, drive_vault_dir=tmp_path)
    assert len(calls) == 3
    monkeypatch.setattr(gs, "get_creds", lambda account: None)
    gs.sync("missing")
    assert len(calls) == 3


def test_oauth_auth_paths(load_script, tmp_path, monkeypatch):
    gs = module(load_script)
    gs.CREDS_FILE = tmp_path / "keys.json"
    gs.TOKEN_DIR = tmp_path / "tokens"
    gs.oauth_auth("work")
    gs.CREDS_FILE.write_text(json.dumps({"installed": {
        "client_id": "id", "client_secret": "secret"}}), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    gs.oauth_auth("work")
    monkeypatch.setattr("builtins.input", lambda prompt: "code")
    response = SimpleNamespace(stdout=json.dumps({
        "access_token": "token", "refresh_token": "refresh", "expires_in": 60}))
    monkeypatch.setattr(gs.subprocess, "run", lambda *a, **k: response)
    gs.oauth_auth("work")
    assert gs.load_creds("work")["token"] == "token"


def test_main_auth_and_all_accounts(load_script, monkeypatch):
    gs = module(load_script)
    calls = []
    monkeypatch.setattr(gs, "oauth_auth", lambda account: calls.append(("auth", account)))
    monkeypatch.setattr(gs, "get_creds", lambda account: {"token": "token"})
    monkeypatch.setattr(gs, "sync", lambda account, **kwargs: calls.append(("sync", account, kwargs)))
    monkeypatch.setattr(gs, "sync_calendar", lambda account, **kwargs: calls.append(("calendar", account)))
    monkeypatch.setattr(gs, "sync_gmail", lambda account, **kwargs: calls.append(("gmail", account)))
    monkeypatch.setattr(gs, "gapi_get", lambda *a, **k: {"drives": [{"id": "shared"}]})
    monkeypatch.setattr(__import__("sys"), "argv", ["google", "--auth", gs.WORK_ACCOUNT])
    gs.main()
    assert calls == [("auth", gs.WORK_ACCOUNT)]
    calls.clear()
    monkeypatch.setattr(__import__("sys"), "argv", ["google"])
    gs.main()
    assert sum(call[0] == "calendar" for call in calls) == 3
    assert sum(call[0] == "gmail" for call in calls) == 3
