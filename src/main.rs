use fs2::FileExt;
use serde_json::{Map, Value};
use std::collections::HashMap;
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitCode, Stdio};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::Duration;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn main() -> ExitCode {
    let result = match env::args().nth(1).as_deref() {
        Some("tei") => run_tei(),
        Some("code-index-watch") => run_code_index_watch(),
        Some("hindsight") => run_hindsight(),
        Some("mtplx-context-sync") => run_mtplx_context_sync(),
        _ => Err("usage: hermes-infra <tei|code-index-watch|hindsight|mtplx-context-sync>".into()),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("hermes-infra: {error}");
            ExitCode::FAILURE
        }
    }
}

fn home() -> PathBuf {
    PathBuf::from(env::var("HOME").unwrap_or_else(|_| ".".into()))
}

fn repo_root() -> Result<PathBuf> {
    if let Ok(path) = env::var("HERMES_INFRA_DIR") {
        return Ok(expand_path(&path, &HashMap::new()));
    }
    Ok(env::current_exe()?
        .parent()
        .and_then(Path::parent)
        .and_then(Path::parent)
        .ok_or("cannot infer repository root")?
        .to_path_buf())
}

fn expand_path(value: &str, values: &HashMap<String, String>) -> PathBuf {
    let mut expanded = value.to_string();
    if expanded == "$HOME" || expanded.starts_with("$HOME/") {
        expanded = expanded.replacen("$HOME", &home().to_string_lossy(), 1);
    } else if expanded == "~" || expanded.starts_with("~/") {
        expanded = expanded.replacen('~', &home().to_string_lossy(), 1);
    }
    for (key, replacement) in values {
        expanded = expanded.replace(&format!("${key}"), replacement);
        expanded = expanded.replace(&format!("${{{key}}}"), replacement);
    }
    PathBuf::from(expanded)
}

fn load_env_file(path: &Path, values: &mut HashMap<String, String>) -> Result<()> {
    if !path.exists() {
        return Ok(());
    }
    let mut entries = Vec::new();
    for raw in fs::read_to_string(path)?.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((key, raw_value)) = line.split_once('=') else {
            continue;
        };
        let key = key.trim().to_string();
        let value = raw_value.trim().trim_matches(['"', '\'']).to_string();
        values.insert(key.clone(), value.clone());
        entries.push((key, value));
    }
    for _ in 0..3 {
        let current = values.clone();
        for (key, raw_value) in &entries {
            let expanded = expand_path(raw_value, &current)
                .to_string_lossy()
                .into_owned();
            values.insert(key.clone(), expanded);
        }
    }
    Ok(())
}

fn config() -> Result<HashMap<String, String>> {
    let root = repo_root()?;
    let mut values = HashMap::new();
    load_env_file(&root.join(".env"), &mut values)?;
    for (key, value) in env::vars() {
        values.insert(key, value);
    }
    Ok(values)
}

fn hindsight_config() -> Result<HashMap<String, String>> {
    let root = repo_root()?;
    let mut values = HashMap::new();
    load_env_file(&root.join(".env"), &mut values)?;
    let hermes_home = env::var("HERMES_HOME")
        .ok()
        .or_else(|| values.get("HERMES_HOME").cloned())
        .unwrap_or_else(|| "~/.hermes".into());
    let hermes_home = expand_path(&hermes_home, &values);
    load_env_file(&hermes_home.join(".env"), &mut values)?;
    let secret_file = values
        .get("HINDSIGHT_SECRET_ENV_FILE")
        .map(|path| expand_path(path, &values))
        .unwrap_or_else(|| hermes_home.join("hindsight.env"));
    load_env_file(&secret_file, &mut values)?;
    for (key, value) in env::vars() {
        values.insert(key, value);
    }
    Ok(values)
}

fn value(values: &HashMap<String, String>, key: &str, default: &str) -> String {
    values
        .get(key)
        .cloned()
        .unwrap_or_else(|| default.to_string())
}

fn find_executable(values: &HashMap<String, String>, key: &str, name: &str) -> Result<PathBuf> {
    if let Some(path) = values
        .get(key)
        .map(PathBuf::from)
        .filter(|path| path.is_file())
    {
        return Ok(path);
    }
    let mut candidates = vec![
        PathBuf::from("/opt/homebrew/bin").join(name),
        PathBuf::from("/usr/local/bin").join(name),
    ];
    if let Some(path) = values.get("PATH") {
        candidates.extend(env::split_paths(path).map(|dir| dir.join(name)));
    }
    candidates
        .into_iter()
        .find(|path| path.is_file())
        .ok_or_else(|| format!("{name} not found").into())
}

fn health(port: u16) -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(
        &format!("127.0.0.1:{port}").parse().unwrap(),
        Duration::from_secs(2),
    ) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    if stream
        .write_all(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = String::new();
    stream.read_to_string(&mut response).is_ok() && response.contains(" 200 ")
}

fn child_rss_kb(child: &Child) -> Option<u64> {
    let output = Command::new("ps")
        .args(["-p", &child.id().to_string(), "-o", "rss="])
        .output()
        .ok()?;
    String::from_utf8_lossy(&output.stdout).trim().parse().ok()
}

fn run_tei() -> Result<()> {
    let values = config()?;
    let binary = find_executable(&values, "TEI_BIN", "text-embeddings-router")?;
    let port: u16 = value(&values, "TEI_PORT", "6999").parse()?;
    let model = value(&values, "EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B");
    let memory_limit_kb: u64 =
        value(&values, "TEI_MEMORY_LIMIT_BYTES", "2147483648").parse::<u64>()? / 1024;
    let stopping = Arc::new(AtomicBool::new(false));
    let signal = Arc::clone(&stopping);
    ctrlc::set_handler(move || signal.store(true, Ordering::SeqCst))?;

    let mut child = Command::new(binary)
        .args([
            "--model-id",
            &model,
            "--dtype",
            "float16",
            "--port",
            &port.to_string(),
            "--max-batch-tokens",
            "512",
            "--max-batch-requests",
            "16",
            "--max-concurrent-requests",
            "16",
        ])
        .envs(&values)
        .spawn()?;

    for _ in 0..120 {
        if health(port) {
            break;
        }
        if let Some(status) = child.try_wait()? {
            return Err(format!("TEI exited before becoming healthy: {status}").into());
        }
        thread::sleep(Duration::from_secs(1));
    }
    if !health(port) {
        let _ = child.kill();
        return Err("TEI did not become healthy within 120 seconds".into());
    }

    loop {
        if stopping.load(Ordering::SeqCst) {
            let _ = child.kill();
            let _ = child.wait();
            return Ok(());
        }
        if let Some(status) = child.try_wait()? {
            return Err(format!("TEI exited: {status}").into());
        }
        if child_rss_kb(&child).is_some_and(|rss| rss > memory_limit_kb) {
            let _ = child.kill();
            let _ = child.wait();
            return Err("TEI exceeded its memory limit".into());
        }
        thread::sleep(Duration::from_secs(10));
    }
}

fn run_code_index_watch() -> Result<()> {
    let values = config()?;
    let root = repo_root()?;
    let watch_root = expand_path(&value(&values, "DEV_ROOT", "~/code"), &values);
    let watchman = find_executable(&values, "WATCHMAN_BIN", "watchman")?;
    let python = expand_path(
        &value(
            &values,
            "HERMES_INFRA_VENV",
            &root.join(".venv").to_string_lossy(),
        ),
        &values,
    )
    .join("bin/python");
    let indexer = root.join("code-index/indexer.py");
    let port: u16 = value(&values, "TEI_PORT", "6999").parse()?;
    if !health(port) {
        let plist_dir = expand_path(
            &value(
                &values,
                "HERMES_LAUNCH_AGENTS_DIR",
                "~/Library/LaunchAgents",
            ),
            &values,
        );
        let plist_name = value(&values, "TEI_PLIST_NAME", "com.hermes.tei.plist");
        let status = Command::new("launchctl")
            .args(["load", &plist_dir.join(plist_name).to_string_lossy()])
            .status();
        match status {
            Ok(status) if !status.success() => {
                eprintln!("failed to load TEI launchd service: {status}");
            }
            Err(error) => eprintln!("failed to invoke launchctl for TEI: {error}"),
            _ => {}
        }
        for _ in 0..120 {
            if health(port) {
                break;
            }
            thread::sleep(Duration::from_secs(1));
        }
    }
    if !health(port) {
        return Err("TEI is unavailable".into());
    }

    let status = Command::new(&watchman)
        .args(["watch", &watch_root.to_string_lossy()])
        .status()?;
    if !status.success() {
        return Err("watchman watch failed".into());
    }
    let mut child = Command::new(&watchman)
        .args([
            "subscribe",
            &watch_root.to_string_lossy(),
            "hermes-code-index",
            r#"{"fields":["name","size","mtime_ms"]}"#,
        ])
        .stdout(Stdio::piped())
        .spawn()?;
    let stdout = child.stdout.take().ok_or("watchman stdout unavailable")?;
    let busy = PathBuf::from(value(&values, "TMPDIR", "/tmp")).join("hermes-code-index-busy");
    for line in BufReader::new(stdout).lines() {
        let line = line?;
        if !line.contains("\"subscription\"") && !line.contains("\"subscribe\"") {
            continue;
        }
        thread::sleep(Duration::from_secs(60));
        let Ok(lock) = OpenOptions::new().write(true).create_new(true).open(&busy) else {
            continue;
        };
        let status = Command::new(&python)
            .arg(&indexer)
            .arg("--index")
            .envs(&values)
            .status();
        drop(lock);
        let _ = fs::remove_file(&busy);
        if let Err(error) = status {
            eprintln!("indexer failed: {error}");
        }
    }
    let status = child.wait()?;
    Err(format!("watchman subscription exited: {status}").into())
}

fn run_hindsight() -> Result<()> {
    let mut values = hindsight_config()?;
    let binary = expand_path(
        &value(
            &values,
            "HINDSIGHT_BIN",
            &expand_path(
                &value(
                    &values,
                    "HINDSIGHT_VENV",
                    &repo_root()?.join(".hindsight-venv").to_string_lossy(),
                ),
                &values,
            )
            .join("bin/hindsight-api")
            .to_string_lossy(),
        ),
        &values,
    );
    if !binary.is_file() {
        return Err(format!("Hindsight binary not found: {}", binary.display()).into());
    }
    let key = values
        .get("HINDSIGHT_LLM_API_KEY")
        .filter(|key| !key.is_empty())
        .cloned()
        .ok_or("HINDSIGHT_LLM_API_KEY is not configured")?;
    let tei_url = value(
        &values,
        "TEI_EMBED_URL",
        "http://127.0.0.1:6999/v1/embeddings",
    );
    let embedding_base = tei_url.trim_end_matches("/embeddings").to_string();
    let host = value(&values, "HINDSIGHT_API_HOST", "127.0.0.1");
    let port = value(&values, "HINDSIGHT_API_PORT", "9177");
    let log_level = value(&values, "HINDSIGHT_API_LOG_LEVEL", "info");

    values.insert(
        "HINDSIGHT_API_LLM_PROVIDER".into(),
        value(&values, "HINDSIGHT_API_LLM_PROVIDER", "openai"),
    );
    values.insert("HINDSIGHT_API_LLM_API_KEY".into(), key);
    values.insert(
        "HINDSIGHT_API_LLM_BASE_URL".into(),
        value(
            &values,
            "HINDSIGHT_API_LLM_BASE_URL",
            "https://openrouter.ai/api/v1",
        ),
    );
    values.insert(
        "HINDSIGHT_API_LLM_MODEL".into(),
        value(&values, "HINDSIGHT_API_LLM_MODEL", "openrouter/free"),
    );
    values.insert(
        "HINDSIGHT_API_LLM_STRICT_SCHEMA".into(),
        value(&values, "HINDSIGHT_API_LLM_STRICT_SCHEMA", "false"),
    );
    values.insert(
        "HINDSIGHT_API_EMBEDDINGS_PROVIDER".into(),
        value(&values, "HINDSIGHT_API_EMBEDDINGS_PROVIDER", "openai"),
    );
    values.insert(
        "HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY".into(),
        value(&values, "HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY", "tei"),
    );
    values.insert(
        "HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL".into(),
        value(
            &values,
            "HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL",
            &embedding_base,
        ),
    );
    values.insert(
        "HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL".into(),
        value(
            &values,
            "HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL",
            "Qwen/Qwen3-Embedding-0.6B",
        ),
    );
    values.insert(
        "HINDSIGHT_API_EMBEDDINGS_DIM".into(),
        value(&values, "HINDSIGHT_API_EMBEDDINGS_DIM", "1024"),
    );
    values.insert(
        "HINDSIGHT_API_RERANKER_PROVIDER".into(),
        value(&values, "HINDSIGHT_API_RERANKER_PROVIDER", "rrf"),
    );
    values.insert(
        "HINDSIGHT_PROFILE".into(),
        value(&values, "HINDSIGHT_PROFILE", "hermes"),
    );

    let error = Command::new(binary)
        .args(["--host", &host, "--port", &port, "--log-level", &log_level])
        .envs(values)
        .exec();
    Err(error.into())
}

fn read_json(path: &Path) -> Result<Map<String, Value>> {
    if !path.exists() {
        return Ok(Map::new());
    }
    Ok(serde_json::from_str::<Value>(&fs::read_to_string(path)?)?
        .as_object()
        .cloned()
        .unwrap_or_default())
}

fn write_json(path: &Path, value: &Map<String, Value>) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let temporary = path.with_extension("json.tmp");
    fs::write(
        &temporary,
        format!("{}\n", serde_json::to_string_pretty(value)?),
    )?;
    fs::rename(temporary, path)?;
    Ok(())
}

fn model_family(model: &str, live: Option<&str>) -> Option<&'static str> {
    match live {
        Some("qwen3_6") => return Some("qwen3_6"),
        Some("qwen3_5") => return Some("qwen3_5"),
        Some("gemma4") => return Some("gemma4"),
        _ => {}
    }
    let lowered = model.to_lowercase();
    if lowered.contains("gemma") {
        Some("gemma4")
    } else if lowered.contains("qwen") {
        Some("qwen3_6")
    } else {
        None
    }
}

fn run_mtplx_context_sync() -> Result<()> {
    let values = config()?;
    let settings_path = expand_path(
        &value(
            &values,
            "MTPLX_SETTINGS_PATH",
            "~/Library/Application Support/MTPLX/settings.json",
        ),
        &values,
    );
    let lock_path = expand_path(
        &value(
            &values,
            "MTPLX_CONTEXT_SYNC_LOCK",
            "~/Library/Application Support/MTPLX/.context-sync.lock",
        ),
        &values,
    );
    let prefs_path = expand_path(
        &value(
            &values,
            "MTPLX_CONTEXT_PREFS_PATH",
            "~/.mtplx/context-windows-by-family.json",
        ),
        &values,
    );
    if !settings_path.exists() {
        return Ok(());
    }
    if let Some(parent) = lock_path.parent() {
        fs::create_dir_all(parent)?;
    }
    let lock = File::create(lock_path)?;
    lock.lock_exclusive()?;
    let mut settings = read_json(&settings_path)?;
    let mut prefs = read_json(&prefs_path)?;
    prefs.entry("qwen3_6").or_insert(Value::from(131072));
    prefs.entry("gemma4").or_insert(Value::from(131072));
    let model = settings.get("model").and_then(Value::as_str).unwrap_or("");
    let live = settings
        .get("live_settings_model_family")
        .and_then(Value::as_str);
    let Some(family) = model_family(model, live) else {
        return Ok(());
    };
    let stored_family = settings
        .get("context_window_model_family")
        .and_then(Value::as_str);
    let context = settings.get("context_window").and_then(Value::as_i64);
    if stored_family == Some(family) && context.is_some_and(|number| number > 0 && number != 262144)
    {
        prefs.insert(family.into(), Value::from(context.unwrap()));
        write_json(&prefs_path, &prefs)?;
    }
    let target = prefs.get(family).and_then(Value::as_i64).unwrap_or(131072);
    if context != Some(target) || stored_family != Some(family) {
        settings.insert("context_window".into(), Value::from(target));
        settings.insert("context_window_model_family".into(), Value::from(family));
        write_json(&settings_path, &settings)?;
        println!("mtplx-context-sync: restored per-family context window");
    }
    FileExt::unlock(&lock)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn infers_supported_model_families() {
        assert_eq!(model_family("Qwen3.6-27B", None), Some("qwen3_6"));
        assert_eq!(model_family("Gemma4", None), Some("gemma4"));
        assert_eq!(model_family("unknown", Some("qwen3_5")), Some("qwen3_5"));
        assert_eq!(model_family("unknown", None), None);
    }

    #[test]
    fn expands_known_environment_references() {
        let values = HashMap::from([("ROOT".to_string(), "/tmp/root".to_string())]);
        assert_eq!(
            expand_path("$ROOT/data", &values),
            PathBuf::from("/tmp/root/data")
        );
    }

    #[test]
    fn expands_forward_dotenv_references() {
        let path = env::temp_dir().join(format!("hermes-infra-env-{}", std::process::id()));
        fs::write(&path, "ALIAS=$VALUE\nVALUE=resolved\n").unwrap();
        let mut values = HashMap::new();
        load_env_file(&path, &mut values).unwrap();
        fs::remove_file(path).unwrap();
        assert_eq!(values.get("ALIAS").map(String::as_str), Some("resolved"));
    }
}
