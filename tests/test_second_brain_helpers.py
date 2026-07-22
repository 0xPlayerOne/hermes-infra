import io
import json
import sqlite3
from pathlib import Path


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_export_memory_facts_and_bad_json(load_script, tmp_path, monkeypatch):
    module = load_script("second-brain/scripts/export_memories.py")
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "facts.json").write_text(
        json.dumps([{"content": "first", "target": "memory"}, {"memory": "second"}]),
        encoding="utf-8",
    )
    (memory / "bad.json").write_text("{bad", encoding="utf-8")
    module.MEM_FACTS_DIR = str(tmp_path / "out")
    original = module.os.path.expanduser
    monkeypatch.setattr(
        module.os.path,
        "expanduser",
        lambda path: str(memory) if path == "~/.hermes/memory" else original(path),
    )
    assert module.export_memory_facts() == 2
    assert len(list((tmp_path / "out").glob("*.md"))) == 2


def test_export_hindsight_success_and_failure(load_script, tmp_path, monkeypatch):
    module = load_script("second-brain/scripts/export_memories.py")
    module.HINDSIGHT_DIR = str(tmp_path / "hindsight")
    payload = json.dumps(
        {
            "memories": [
                {"id": "one", "content": "observation"},
                {"oid": "two", "text": "another"},
                {"id": "empty", "content": ""},
            ]
        }
    ).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(payload))
    assert module.export_hindsight() == 2
    assert len(list((tmp_path / "hindsight").glob("*.md"))) == 2
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down"))
    )
    assert module.export_hindsight() == 0
    assert "skipped" in (tmp_path / "hindsight" / "_STATUS.md").read_text(encoding="utf-8")


def test_write_vault_file_and_dashboard(load_script, tmp_path):
    module = load_script("second-brain/scripts/export_memories.py")
    path = tmp_path / "nested" / "file.md"
    module.write_vault_file(str(path), "content")
    assert path.read_text(encoding="utf-8") == "content"
    module.VAULT = str(tmp_path / "brain")
    source_dir = tmp_path / "brain" / "Work" / "Calendar"
    source_dir.mkdir(parents=True)
    (source_dir / "event.md").write_text("event", encoding="utf-8")
    module.write_dashboard(3, 4)
    dashboard = (tmp_path / "brain" / "DASHBOARD.md").read_text(encoding="utf-8")
    assert "memory-tool facts: **3**" in dashboard
    assert "Hindsight observations: **4**" in dashboard


def test_synthesis_clean_extract_and_deduplicate(load_script):
    module = load_script("second-brain/scripts/synthesize.py")
    clean = module.clean_message("real line\n[IMPORTANT hidden]")
    assert clean == "real line"
    messages = ["I prefer Rust for infrastructure.\nI prefer Rust for infrastructure."]
    facts = module.extract_candidates(messages)
    assert len(facts) == 1
    assert facts[0][0].startswith("PREFERENCE:")
    assert module.is_new(facts[0][0], set())
    assert not module.is_new(facts[0][0], {facts[0][0].lower()})


def test_synthesis_files_and_existing_facts(load_script, tmp_path):
    module = load_script("second-brain/scripts/synthesize.py")
    module.MEMORY_MD = str(tmp_path / "MEMORY.md")
    module.USER_MD = str(tmp_path / "USER.md")
    module.MEM_FACTS_DIR = str(tmp_path / "facts")
    Path(module.MEMORY_MD).write_text("Existing fact", encoding="utf-8")
    Path(module.USER_MD).write_text("User fact\n", encoding="utf-8")
    Path(module.MEM_FACTS_DIR).mkdir()
    (Path(module.MEM_FACTS_DIR) / "one.md").write_text(
        "---\ntype: fact\n---\nFile fact", encoding="utf-8"
    )
    existing = module.load_existing_facts()
    assert {"existing fact", "user fact", "file fact"} <= existing
    module.append_fact(module.MEMORY_MD, "New fact")
    assert "§\nNew fact" in Path(module.MEMORY_MD).read_text(encoding="utf-8")
    module.write_memory_fact_file("A durable synthesized fact")
    module.write_memory_fact_file("A durable synthesized fact")
    assert len(list(Path(module.MEM_FACTS_DIR).glob("*.md"))) == 3


def test_synthesis_recent_messages(load_script, tmp_path):
    module = load_script("second-brain/scripts/synthesize.py")
    module.STATE_DB = str(tmp_path / "state.db")
    con = sqlite3.connect(module.STATE_DB)
    con.execute("CREATE TABLE messages (role TEXT, timestamp REAL, content TEXT)")
    con.execute(
        "INSERT INTO messages VALUES ('user', ?, ?)",
        (9999999999, "A sufficiently long user message"),
    )
    con.execute(
        "INSERT INTO messages VALUES ('assistant', ?, ?)", (9999999999, "ignored assistant message")
    )
    con.commit()
    con.close()
    assert module.get_recent_user_messages() == ["A sufficiently long user message"]


def test_queue_hindsight_paths(load_script, monkeypatch):
    module = load_script("second-brain/scripts/synthesize.py")
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: Response(b""))
    assert module.queue_hindsight("fact")
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError())
    )
    assert not module.queue_hindsight("fact")


def test_synthesis_main_and_missing_db(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("second-brain/scripts/synthesize.py")
    module.STATE_DB = str(tmp_path / "missing.db")
    assert module.get_recent_user_messages() == []
    memory = tmp_path / "MEMORY.md"
    user = tmp_path / "USER.md"
    memory.write_text("memory", encoding="utf-8")
    user.write_text("user", encoding="utf-8")
    module.MEMORY_MD = str(memory)
    module.USER_MD = str(user)
    module.MEM_FACTS_DIR = str(tmp_path / "facts")
    module.PATTERNS = [
        (pattern, formatter, str(user)) for pattern, formatter, target in module.PATTERNS
    ]
    monkeypatch.setattr(
        module, "get_recent_user_messages", lambda: ["I prefer Rust for local infrastructure."]
    )
    monkeypatch.setattr(module, "queue_hindsight", lambda fact: True)
    module.main()
    assert "NEW durable facts synthesized: 1" in capsys.readouterr().out
    assert "PREFERENCE:" in user.read_text(encoding="utf-8")


def test_rebuild_frontmatter_and_chunks(load_script):
    module = load_script("second-brain/scripts/rebuild_chroma.py")
    assert module.parse_frontmatter(
        "---\ntitle: Example\nurl: https://example.test/a:b\n---\nbody"
    ) == {"title": "Example", "url": "https://example.test/a:b"}
    assert module.parse_frontmatter("body") == {}
    assert len(module.chunks("x" * 3000)) == 3
    assert module.chunks("") == []


def test_rebuild_main(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("second-brain/scripts/rebuild_chroma.py")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text(
        "---\ntitle: Note\nsource: test\n---\n\n" + "body " * 400, encoding="utf-8"
    )
    hidden = vault / ".obsidian"
    hidden.mkdir()
    (hidden / "skip.md").write_text("skip", encoding="utf-8")
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    (chroma_dir / "old").write_text("old", encoding="utf-8")
    module.source.VAULT = str(vault)
    module.source.CHROMA_DIR = str(chroma_dir)
    module.source.embed = lambda pieces: [[1.0]] * len(pieces)

    class Collection:
        calls = []

        def upsert(self, **kwargs):
            self.calls.append(kwargs)

    collection = Collection()
    client = type("Client", (), {"get_or_create_collection": lambda self, name: collection})()
    monkeypatch.setattr(module.chromadb, "PersistentClient", lambda **kwargs: client)
    module.main()
    assert collection.calls
    assert "1 files" in capsys.readouterr().out
