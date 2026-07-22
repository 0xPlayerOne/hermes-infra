use fs2::FileExt;
use serde_json::{Map, Value};
use std::collections::HashMap;
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::net::TcpStream;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitCode};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant};

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
    if expanded == "$HOME"
        || expanded.starts_with("$HOME/")
        || expanded == "${HOME}"
        || expanded.starts_with("${HOME}/")
    {
        let marker = if expanded.starts_with("${HOME}") {
            "${HOME}"
        } else {
            "$HOME"
        };
        expanded = expanded.replacen(marker, &home().to_string_lossy(), 1);
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
    config_from(&repo_root()?, env::vars())
}

fn config_from<I>(root: &Path, process_vars: I) -> Result<HashMap<String, String>>
where
    I: IntoIterator<Item = (String, String)>,
{
    let mut values = HashMap::new();
    load_env_file(&root.join(".env"), &mut values)?;
    for (key, value) in process_vars {
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
    load_hindsight_json_config(&hermes_home.join("hindsight/config.json"), &mut values)?;
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

fn load_hindsight_json_config(path: &Path, values: &mut HashMap<String, String>) -> Result<()> {
    if !path.exists() {
        return Ok(());
    }
    let object: Value = serde_json::from_str(&fs::read_to_string(path)?)?;
    let Some(object) = object.as_object() else {
        return Ok(());
    };
    for (source, target) in [
        ("llm_provider", "HINDSIGHT_API_LLM_PROVIDER"),
        ("llm_base_url", "HINDSIGHT_API_LLM_BASE_URL"),
        ("llm_model", "HINDSIGHT_API_LLM_MODEL"),
    ] {
        if let Some(value) = object.get(source).and_then(Value::as_str) {
            values.entry(target.into()).or_insert_with(|| value.into());
        }
    }
    Ok(())
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
    eprintln!("hermes-infra tei: starting {model} on 127.0.0.1:{port}");
    let stopping = Arc::new(AtomicBool::new(false));
    let signal = Arc::clone(&stopping);
    ctrlc::set_handler(move || signal.store(true, Ordering::SeqCst))?;

    let mut child = Command::new(binary)
        .args([
            "--model-id",
            &model,
            "--dtype",
            "float16",
            "--hostname",
            "127.0.0.1",
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
    eprintln!("hermes-infra tei: healthy on 127.0.0.1:{port}");

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
            eprintln!("hermes-infra tei: RSS exceeded {memory_limit_kb} KiB");
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

    watchman_json(&watchman, &["watch-project", &watch_root.to_string_lossy()])?;
    let mut clock = watchman_clock(&watchman, &watch_root)?;
    let poll_seconds: u64 = value(&values, "WATCH_POLL_SECONDS", "5").parse()?;
    let debounce_seconds: u64 = value(&values, "WATCH_DEBOUNCE_SECONDS", "60").parse()?;
    eprintln!(
        "hermes-infra code-index-watch: watching {}",
        watch_root.display()
    );
    let busy = PathBuf::from(value(&values, "TMPDIR", "/tmp")).join("hermes-code-index-busy");
    let mut pending_since = None;
    loop {
        thread::sleep(Duration::from_secs(poll_seconds));
        match watchman_json(&watchman, &["since", &watch_root.to_string_lossy(), &clock]) {
            Ok(response) => {
                if let Some(next_clock) = response.get("clock").and_then(Value::as_str) {
                    clock = next_clock.to_string();
                }
                if watchman_change_count(&response) > 0 {
                    pending_since = Some(Instant::now());
                }
            }
            Err(error) => {
                eprintln!("watchman query failed: {error}");
                continue;
            }
        }
        if !pending_since
            .is_some_and(|started| started.elapsed() >= Duration::from_secs(debounce_seconds))
        {
            continue;
        }
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
        match status {
            Ok(status) if !status.success() => eprintln!("indexer exited: {status}"),
            Err(error) => eprintln!("indexer failed: {error}"),
            Ok(status) => eprintln!("indexer completed: {status}"),
        }
        pending_since = None;
    }
}

fn watchman_json(watchman: &Path, args: &[&str]) -> Result<Value> {
    let output = Command::new(watchman).args(args).output()?;
    if !output.status.success() {
        return Err(format!(
            "watchman {} failed: {}",
            args.first().copied().unwrap_or("command"),
            String::from_utf8_lossy(&output.stderr).trim()
        )
        .into());
    }
    Ok(serde_json::from_slice(&output.stdout)?)
}

fn watchman_clock(watchman: &Path, watch_root: &Path) -> Result<String> {
    let response = watchman_json(watchman, &["clock", &watch_root.to_string_lossy()])?;
    response
        .get("clock")
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| "watchman clock response is missing clock".into())
}

fn watchman_change_count(response: &Value) -> usize {
    response
        .get("files")
        .and_then(Value::as_array)
        .map_or(0, Vec::len)
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

    let llm_provider = value(&values, "HINDSIGHT_API_LLM_PROVIDER", "openai");
    let llm_base_url = values
        .get("HINDSIGHT_API_LLM_BASE_URL")
        .filter(|value| !value.is_empty())
        .ok_or("HINDSIGHT_API_LLM_BASE_URL is not configured")?
        .clone();
    let llm_model = values
        .get("HINDSIGHT_API_LLM_MODEL")
        .filter(|value| !value.is_empty())
        .ok_or("HINDSIGHT_API_LLM_MODEL is not configured")?
        .clone();
    values.insert("HINDSIGHT_API_LLM_PROVIDER".into(), llm_provider);
    values.insert("HINDSIGHT_API_LLM_API_KEY".into(), key);
    values.insert("HINDSIGHT_API_LLM_BASE_URL".into(), llm_base_url);
    values.insert("HINDSIGHT_API_LLM_MODEL".into(), llm_model);
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

fn reconcile_mtplx_settings(
    settings: &mut Map<String, Value>,
    prefs: &mut Map<String, Value>,
) -> (bool, bool) {
    let before_prefs = prefs.clone();
    prefs.entry("qwen3_6").or_insert(Value::from(131072));
    prefs.entry("gemma4").or_insert(Value::from(131072));
    let model = settings.get("model").and_then(Value::as_str).unwrap_or("");
    let live = settings
        .get("live_settings_model_family")
        .and_then(Value::as_str);
    let Some(family) = model_family(model, live) else {
        return (false, *prefs != before_prefs);
    };
    let stored_family = settings
        .get("context_window_model_family")
        .and_then(Value::as_str);
    let context = settings.get("context_window").and_then(Value::as_i64);
    if stored_family == Some(family) && context.is_some_and(|number| number > 0 && number != 262144)
    {
        prefs.insert(family.into(), Value::from(context.unwrap()));
    }
    let target = prefs.get(family).and_then(Value::as_i64).unwrap_or(131072);
    let settings_changed = context != Some(target) || stored_family != Some(family);
    if settings_changed {
        settings.insert("context_window".into(), Value::from(target));
        settings.insert("context_window_model_family".into(), Value::from(family));
    }
    (settings_changed, *prefs != before_prefs)
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
    let (settings_changed, prefs_changed) = reconcile_mtplx_settings(&mut settings, &mut prefs);
    if prefs_changed {
        write_json(&prefs_path, &prefs)?;
    }
    if settings_changed {
        write_json(&settings_path, &settings)?;
        println!("mtplx-context-sync: restored per-family context window");
    }
    FileExt::unlock(&lock)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_ID: AtomicU64 = AtomicU64::new(1);

    fn temp_path(name: &str) -> PathBuf {
        let id = NEXT_ID.fetch_add(1, Ordering::Relaxed);
        env::temp_dir().join(format!("hermes-infra-{name}-{}-{id}", std::process::id()))
    }

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
        let path = temp_path("env");
        fs::write(&path, "ALIAS=$VALUE\nVALUE=resolved\n").unwrap();
        let mut values = HashMap::new();
        load_env_file(&path, &mut values).unwrap();
        fs::remove_file(path).unwrap();
        assert_eq!(values.get("ALIAS").map(String::as_str), Some("resolved"));
    }

    #[test]
    fn loads_dotenv_comments_quotes_overrides_and_missing_files() {
        let path = temp_path("dotenv-cases");
        fs::write(
            &path,
            "# comment\n\nA=first\nB='quoted'\nMALFORMED\nA=second\nC=${B}/child\n",
        )
        .unwrap();
        let mut values = HashMap::new();
        load_env_file(&path, &mut values).unwrap();
        assert_eq!(values.get("A").map(String::as_str), Some("second"));
        assert_eq!(values.get("B").map(String::as_str), Some("quoted"));
        assert_eq!(values.get("C").map(String::as_str), Some("quoted/child"));
        fs::remove_file(path).unwrap();
        load_env_file(&temp_path("missing"), &mut values).unwrap();
    }

    #[test]
    fn expands_home_braces_unknowns_and_empty_paths() {
        let values = HashMap::from([("ROOT".to_string(), "/tmp/root".to_string())]);
        assert_eq!(
            expand_path("${ROOT}/data", &values),
            PathBuf::from("/tmp/root/data")
        );
        assert_eq!(
            expand_path("$UNKNOWN/data", &values),
            PathBuf::from("$UNKNOWN/data")
        );
        assert_eq!(expand_path("", &values), PathBuf::from(""));
        assert!(expand_path("~/data", &values).is_absolute());
        assert!(expand_path("$HOME/data", &values).is_absolute());
    }

    #[test]
    fn value_uses_configured_or_default_value() {
        let values = HashMap::from([("KEY".to_string(), "configured".to_string())]);
        assert_eq!(value(&values, "KEY", "default"), "configured");
        assert_eq!(value(&values, "MISSING", "default"), "default");
    }

    #[test]
    fn config_from_loads_file_and_process_overrides() {
        let dir = temp_path("config");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join(".env"), "FROM_FILE=yes\nOVERRIDE=file\n").unwrap();
        let values = config_from(
            &dir,
            [
                ("OVERRIDE".to_string(), "process".to_string()),
                ("PROCESS_ONLY".to_string(), "yes".to_string()),
            ],
        )
        .unwrap();
        assert_eq!(values.get("FROM_FILE").map(String::as_str), Some("yes"));
        assert_eq!(values.get("OVERRIDE").map(String::as_str), Some("process"));
        assert_eq!(values.get("PROCESS_ONLY").map(String::as_str), Some("yes"));
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn loads_hindsight_provider_settings_without_overriding_environment() {
        let path = temp_path("hindsight-config");
        fs::write(
            &path,
            r#"{
                "llm_provider": "openai",
                "llm_base_url": "https://provider.example/v1",
                "llm_model": "structured-chat"
            }"#,
        )
        .unwrap();
        let mut values = HashMap::from([(
            "HINDSIGHT_API_LLM_MODEL".to_string(),
            "environment-model".to_string(),
        )]);
        load_hindsight_json_config(&path, &mut values).unwrap();
        assert_eq!(
            values.get("HINDSIGHT_API_LLM_BASE_URL").map(String::as_str),
            Some("https://provider.example/v1")
        );
        assert_eq!(
            values.get("HINDSIGHT_API_LLM_MODEL").map(String::as_str),
            Some("environment-model")
        );
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn finds_explicit_and_path_executables() {
        let dir = temp_path("executables");
        fs::create_dir_all(&dir).unwrap();
        let executable = dir.join("tool");
        fs::write(&executable, "#!/bin/sh\nexit 0\n").unwrap();
        let mut permissions = fs::metadata(&executable).unwrap().permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&executable, permissions).unwrap();
        let explicit =
            HashMap::from([("TOOL_BIN".to_string(), executable.to_string_lossy().into())]);
        assert_eq!(
            find_executable(&explicit, "TOOL_BIN", "tool").unwrap(),
            executable
        );
        let path = HashMap::from([("PATH".to_string(), dir.to_string_lossy().into())]);
        assert_eq!(
            find_executable(&path, "MISSING", "tool").unwrap(),
            executable
        );
        assert!(find_executable(&HashMap::new(), "MISSING", "definitely-not-a-command").is_err());
        fs::remove_dir_all(dir).unwrap();
    }

    fn health_server(status: &'static str) -> (u16, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0; 256];
            let _ = stream.read(&mut request);
            write!(stream, "HTTP/1.1 {status}\r\nContent-Length: 0\r\n\r\n").unwrap();
        });
        (port, handle)
    }

    #[test]
    fn health_accepts_200_and_rejects_other_statuses() {
        let (port, handle) = health_server("200 OK");
        assert!(health(port));
        handle.join().unwrap();
        let (port, handle) = health_server("503 Unavailable");
        assert!(!health(port));
        handle.join().unwrap();
    }

    #[test]
    fn health_rejects_closed_port() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        drop(listener);
        assert!(!health(port));
    }

    #[test]
    fn reports_live_child_rss() {
        let mut child = Command::new("sleep").arg("1").spawn().unwrap();
        assert!(child_rss_kb(&child).is_some());
        child.kill().unwrap();
        child.wait().unwrap();
    }

    #[test]
    fn json_helpers_cover_missing_invalid_non_object_and_round_trip() {
        let dir = temp_path("json");
        let path = dir.join("nested/data.json");
        assert!(read_json(&path).unwrap().is_empty());
        let mut data = Map::new();
        data.insert("answer".into(), Value::from(42));
        write_json(&path, &data).unwrap();
        assert_eq!(
            read_json(&path)
                .unwrap()
                .get("answer")
                .and_then(Value::as_i64),
            Some(42)
        );
        fs::write(&path, "[1, 2]").unwrap();
        assert!(read_json(&path).unwrap().is_empty());
        fs::write(&path, "{bad").unwrap();
        assert!(read_json(&path).is_err());
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn watchman_helpers_parse_success_and_errors() {
        let dir = temp_path("watchman");
        fs::create_dir_all(&dir).unwrap();
        let script = dir.join("watchman");
        fs::write(
            &script,
            "#!/bin/sh\nif [ \"$1\" = fail ]; then echo broken >&2; exit 1; fi\necho '{\"clock\":\"c:1\",\"files\":[\"a\",\"b\"]}'\n",
        )
        .unwrap();
        let mut permissions = fs::metadata(&script).unwrap().permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&script, permissions).unwrap();
        let response = watchman_json(&script, &["since"]).unwrap();
        assert_eq!(watchman_change_count(&response), 2);
        assert_eq!(watchman_clock(&script, Path::new("/tmp")).unwrap(), "c:1");
        assert!(watchman_json(&script, &["fail"]).is_err());
        assert_eq!(watchman_change_count(&Value::Null), 0);
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn reconciles_mtplx_family_defaults_and_changes() {
        let mut settings = Map::from_iter([
            ("model".into(), Value::from("Qwen3.6")),
            ("context_window".into(), Value::from(65536)),
            ("context_window_model_family".into(), Value::from("qwen3_6")),
        ]);
        let mut prefs = Map::new();
        let (settings_changed, prefs_changed) = reconcile_mtplx_settings(&mut settings, &mut prefs);
        assert!(!settings_changed);
        assert!(prefs_changed);
        assert_eq!(prefs.get("qwen3_6").and_then(Value::as_i64), Some(65536));
    }

    #[test]
    fn reconciles_mtplx_model_switch_and_ignores_unknown_model() {
        let mut settings = Map::from_iter([
            ("model".into(), Value::from("Gemma4")),
            ("context_window".into(), Value::from(32768)),
            ("context_window_model_family".into(), Value::from("qwen3_6")),
        ]);
        let mut prefs = Map::from_iter([("gemma4".into(), Value::from(98304))]);
        let (settings_changed, _) = reconcile_mtplx_settings(&mut settings, &mut prefs);
        assert!(settings_changed);
        assert_eq!(
            settings.get("context_window").and_then(Value::as_i64),
            Some(98304)
        );
        assert_eq!(
            settings
                .get("context_window_model_family")
                .and_then(Value::as_str),
            Some("gemma4")
        );

        let mut unknown = Map::from_iter([("model".into(), Value::from("unknown"))]);
        let mut empty = Map::new();
        let (changed, prefs_changed) = reconcile_mtplx_settings(&mut unknown, &mut empty);
        assert!(!changed);
        assert!(prefs_changed);
    }

    #[test]
    fn model_family_is_case_insensitive_and_live_setting_wins() {
        assert_eq!(model_family("GEMMA", None), Some("gemma4"));
        assert_eq!(model_family("qwen", Some("gemma4")), Some("gemma4"));
        assert_eq!(model_family("qwen", Some("unknown")), Some("qwen3_6"));
    }
}
