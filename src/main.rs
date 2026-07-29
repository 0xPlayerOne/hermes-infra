use fs2::FileExt;
use serde_json::{Map, Value};
use std::collections::HashMap;
use std::env;
use std::fs::{self, File};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn main() -> ExitCode {
    let result = match env::args().nth(1).as_deref() {
        Some("mtplx-context-sync") => run_mtplx_context_sync(),
        _ => Err("usage: hermes-infra mtplx-context-sync".into()),
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

fn value(values: &HashMap<String, String>, key: &str, default: &str) -> String {
    values
        .get(key)
        .cloned()
        .unwrap_or_else(|| default.to_string())
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
        prefs.insert(
            family.into(),
            Value::from(context.expect("checked context")),
        );
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
    fn expands_environment_and_forward_dotenv_references() {
        let values = HashMap::from([("ROOT".to_string(), "/tmp/root".to_string())]);
        assert_eq!(
            expand_path("$ROOT/data", &values),
            PathBuf::from("/tmp/root/data")
        );
        assert_eq!(
            expand_path("${ROOT}/data", &values),
            PathBuf::from("/tmp/root/data")
        );
        assert!(expand_path("~/data", &values).is_absolute());

        let path = temp_path("env");
        fs::write(&path, "ALIAS=$VALUE\nVALUE=resolved\n").unwrap();
        let mut loaded = HashMap::new();
        load_env_file(&path, &mut loaded).unwrap();
        fs::remove_file(path).unwrap();
        assert_eq!(loaded.get("ALIAS").map(String::as_str), Some("resolved"));
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
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn json_helpers_cover_missing_non_object_and_round_trip() {
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
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn reconciles_mtplx_family_defaults_and_switches() {
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

        settings.insert("model".into(), Value::from("Gemma4"));
        prefs.insert("gemma4".into(), Value::from(98304));
        let (settings_changed, _) = reconcile_mtplx_settings(&mut settings, &mut prefs);
        assert!(settings_changed);
        assert_eq!(
            settings.get("context_window").and_then(Value::as_i64),
            Some(98304)
        );
    }

    #[test]
    fn ignores_unknown_mtplx_model() {
        let mut settings = Map::from_iter([("model".into(), Value::from("unknown"))]);
        let mut prefs = Map::new();
        let (changed, prefs_changed) = reconcile_mtplx_settings(&mut settings, &mut prefs);
        assert!(!changed);
        assert!(prefs_changed);
    }
}
