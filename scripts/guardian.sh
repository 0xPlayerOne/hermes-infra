#!/bin/bash
# ============================================================================
# guardian.sh — Command gatekeeper for autonomous agents
# ----------------------------------------------------------------------------
# Routes agent shell commands through safety checks BEFORE execution.
# Blocks unrecoverable operations, protects critical paths, requires
# confirmation for risky-but-allowed ops, and auto-snapshots before deletes.
#
# Usage (agents call THIS instead of raw terminal):
#   guardian.sh "<command>"
#   guardian.sh --confirm "<command>"   # bypass interactive prompt (cron mode)
#
# Exit codes:
#   0 = executed
#   1 = blocked (forbidden pattern)
#   2 = blocked (protected path)
#   3 = blocked (empty variable trap)
#   4 = needs confirmation (not provided)
#   5 = snapshot failed (aborted for safety)
# ============================================================================

set -u

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SCRIPT_SOURCE" ]; do
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
  SCRIPT_SOURCE="$(readlink "$SCRIPT_SOURCE")"
  [[ "$SCRIPT_SOURCE" != /* ]] && SCRIPT_SOURCE="$SCRIPT_DIR/$SCRIPT_SOURCE"
done
REPO_ROOT="$(cd "$(dirname "$SCRIPT_SOURCE")/.." && pwd)"
ENV_FILE="${HERMES_INFRA_ENV_FILE:-$REPO_ROOT/.env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

resolve_path() {
  local value="$1"
  value="${value//\$\{HOME\}/$HOME}"
  value="${value//\$HOME/$HOME}"
  case "$value" in
    "~/"*) value="$HOME/${value#~/}" ;;
    "~") value="$HOME" ;;
  esac
  printf '%s' "$value"
}

HERMES_HOME="$(resolve_path "${HERMES_HOME:-$HOME/.hermes}")"
DEV_ROOT="$(resolve_path "${DEV_ROOT:-$HOME/code}")"

# ---------------------------------------------------------------------------
# 0. FLAG PARSING
# ---------------------------------------------------------------------------
CONFIRM=0
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --confirm) CONFIRM=1; shift;;
    --) shift; break;;
    *)
      echo "guardian: unsupported option: '$1'" >&2
      exit 1
      ;;
  esac
done

CMD="${1:-}"
if [ -z "$CMD" ]; then
  echo "guardian: no command provided" >&2
  exit 1
fi

LOG="$HERMES_HOME/guardian.log"
mkdir -p "$(dirname "$LOG")"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) REQ: $CMD" >> "$LOG"

# ---------------------------------------------------------------------------
# 1. FORBIDDEN PATTERNS — never allowed, under any circumstance
# ---------------------------------------------------------------------------
# These patterns use exact/prefix matching to avoid over-blocking subpaths.
# e.g. "rm -rf /" matches ONLY "rm -rf /" (root), not "rm -rf /Users/..."
FORBIDDEN_EXACT=(
  "rm -rf /" "rm -rf ~"
  "rm -fr /" "rm --recursive --force /"
  "mkfs" "dd if=" "diskutil eraseDisk" "diskutil partitionDisk"
  "format" "fdisk" "(){:|:&};:" "chmod -R 000 /" "chown -R"
  "> /dev/sd" "> /dev/disk" "shutdown" "halt" "reboot"
  "sudo rm -rf /" "sudo rm -rf ~" "git push --force" "git push -f"
  "force-push" "brew uninstall --force" "npm cache clean --force"
)

# Check FORBIDDEN patterns with precise matching (not substring)
# "rm -rf /" must be the full target or followed by whitespace/end
for pat in "${FORBIDDEN_EXACT[@]}"; do
  # Special handling for "rm -rf /" and similar root patterns
  if [[ "$pat" == "rm -rf /" || "$pat" == "rm -fr /" || "$pat" == "rm --recursive --force /" || "$pat" == "sudo rm -rf /" ]]; then
    # Match only if path is exactly "/" or "/ " (root)
    if [[ "$CMD" =~ (^|[[:space:]])${pat}([[:space:]]|$) ]] || [[ "$CMD" == "$pat" ]]; then
      echo "guardian: BLOCKED — forbidden pattern: '$pat'" | tee -a "$LOG" >&2
      exit 1
    fi
  elif [[ "$pat" == "rm -rf ~" || "$pat" == "sudo rm -rf ~" ]]; then
    # Match only if target is exactly ~ or ~/
    if [[ "$CMD" =~ (^|[[:space:]])${pat}(/|[[:space:]]|$) ]] || [[ "$CMD" == "$pat" ]]; then
      echo "guardian: BLOCKED — forbidden pattern: '$pat'" | tee -a "$LOG" >&2
      exit 1
    fi
  elif [[ "$pat" == "git push --force" || "$pat" == "git push -f" ]]; then
    # Block only a BARE force push (--force / -f). The safe rebase protocol
    # `git push --force-with-lease` must pass: it is not a substring match.
    if [[ "$CMD" =~ (^|[^a-zA-Z])git[[:space:]]+push[[:space:]]+--force([^a-zA-Z-]|$) ]] \
      || [[ "$CMD" =~ (^|[^a-zA-Z])git[[:space:]]+push[[:space:]]+-f([^a-zA-Z-]|$) ]]; then
      echo "guardian: BLOCKED — forbidden pattern: '$pat'" | tee -a "$LOG" >&2
      exit 1
    fi
  else
    # Other patterns: substring is fine (mkfs, fdisk, etc.)
    if [[ "$CMD" == *"$pat"* ]]; then
      echo "guardian: BLOCKED — forbidden pattern: '$pat'" | tee -a "$LOG" >&2
      exit 1
    fi
  fi
done

# Package-manager policy: raw `pip`/`pip3`/`python -m pip` INSTALL/UNINSTALL
# are FORBIDDEN. The sanctioned install path is `uv` (uv pip install / uv tool
# install) — those are ALLOWED without any sentinel. Even `uv` requires the
# explicit '--allow-pip' sentinel ONLY if someone tries raw pip; uv passes free.
# This prevents silent pollution of the system Python or the gateway venv
# (venv drift there breaks the bot per TRAP 2 in hermes-config-editing).
# Read-only pip commands (list/show/freeze/download/check) pass regardless.
PIP_RAW_RE='(^|[^a-zA-Z0-9_.+-])(pip3?|python3?\ -m\ pip)[[:space:]]+(install|uninstall)'
# Sanctioned path: `uv pip install` / `uv pip3 install` / `uv tool install` is allowed.
if [[ "$CMD" == *"uv pip"* || "$CMD" == *"uv pip3"* || "$CMD" == *"uv tool"* ]]; then
  : # explicitly permitted — fall through
elif [[ "$CMD" =~ $PIP_RAW_RE ]]; then
  if [[ "$CMD" != *"--allow-pip"* ]]; then
    echo "guardian: BLOCKED — raw pip is forbidden; use 'uv pip install' instead (--allow-pip only if user explicitly asked for pip)" | tee -a "$LOG" >&2
    exit 1
  fi
  # strip the sentinel before executing (pip doesn't know it)
  CMD="${CMD/--allow-pip/}"
fi
# `uv pip install` / `uv pip3 install` / `uv tool install` are the sanctioned
# path and are explicitly permitted (no sentinel needed).

# ---------------------------------------------------------------------------
# 2. PROTECTED PATHS — cannot be deleted/moved/formatted
#    Agents may READ these but not DESTROY them.
# ---------------------------------------------------------------------------
PROTECTED=(
  "$HOME" "$HOME/" "/Users" "/usr" "/bin" "/sbin" "/opt/homebrew"
  "$HERMES_HOME" "$HERMES_HOME/" "$HOME/.ssh" "$HOME/.config"
  "$DEV_ROOT" "$DEV_ROOT/"
  "$HERMES_HOME/skills"
)

# Detect destructive verbs targeting protected paths
# Use word boundaries so 'rm' matches the command, not the 'rm' in 'hermes'
if [[ "$CMD" =~ (^|[^a-zA-Z])(rm|rmdir|mv|del|format|erase|wipe|purge|trash)([^a-zA-Z]|$) ]]; then
  for prot in "${PROTECTED[@]}"; do
    # expand ~ in protected path
    prot_exp="${prot/#\\~/$HOME}"
    # exact match or path-prefix match (with trailing /), NOT substring
    if [[ "$CMD" == "$prot_exp" || "$CMD" == "$prot_exp/"* || "$CMD" == *" $prot_exp" || "$CMD" == *" $prot_exp "* || "$CMD" == *" $prot_exp/"* ]]; then
      echo "guardian: BLOCKED — protected path in destructive command: '$prot'" | tee -a "$LOG" >&2
      exit 2
    fi
  done
fi

# ---------------------------------------------------------------------------
# 3. EMPTY VARIABLE TRAP — rm -rf $VAR/ where VAR is unset = deletes cwd
# ---------------------------------------------------------------------------
if [[ "$CMD" =~ rm[[:space:]]+-[a-zA-Z]*[rf][a-zA-Z]*[[:space:]]+\\\$?[A-Za-z_]+ ]]; then
  # extract variable names and check if set
  for var in $(echo "$CMD" | grep -oE '\$[A-Za-z_][A-Za-z0-9_]*' | tr -d '$'); do
    if [ -z "${!var:-}" ]; then
      echo "guardian: BLOCKED — rm with unset variable '\$$var' (empty-var trap)" | tee -a "$LOG" >&2
      exit 3
    fi
  done
fi

# ---------------------------------------------------------------------------
# 4. DESTRUCTIve-BUT-ALLOWED — snapshot first, then confirm
# ---------------------------------------------------------------------------
DESTRUCTIVE=0
if [[ "$CMD" =~ (^|[^a-zA-Z])(rm|rmdir|mv|trash|del|purge)([^a-zA-Z]|$) ]]; then
  DESTRUCTIVE=1
fi

if [ "$DESTRUCTIVE" -eq 1 ]; then
  SNAP_NAME="guardian-$(date +%Y%m%d-%H%M%S)"
  if tmutil snapshot 2>/dev/null; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) SNAP: $SNAP_NAME" >> "$LOG"
  else
    echo "guardian: ABORTED — snapshot failed (cannot guarantee recoverability)" | tee -a "$LOG" >&2
    exit 5
  fi

  if [ "$CONFIRM" -eq 0 ]; then
    echo "guardian: DESTRUCTIVE command requires confirmation. Re-run with --confirm or approve." | tee -a "$LOG" >&2
    exit 4
  fi
fi

# ---------------------------------------------------------------------------
# 5. MODEL DOWNLOADS — never pull/create/copy Ollama models unless the user
#    explicitly requested it. Allowed only when the command carries the
#    explicit token '--allow-model-download' (which the agent must only add
#    when the user literally asked for a model).
# ---------------------------------------------------------------------------
if [[ "$CMD" =~ (ollama[[:space:]]+pull|ollama[[:space:]]+create|ollama[[:space:]]+cp|ollama[[:space:]]+pull[[:space:]]) ]]; then
  if [[ "$CMD" != *"--allow-model-download"* ]]; then
    echo "guardian: BLOCKED — model download/create without explicit user request (add --allow-model-download only if user asked)" | tee -a "$LOG" >&2
    exit 7
  fi
  # strip the sentinel token before executing (ollama doesn't know it)
  CMD="${CMD/--allow-model-download/}"
fi

# ---------------------------------------------------------------------------
# 6. EXECUTE (with logging)
# ---------------------------------------------------------------------------
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) EXEC: $CMD" >> "$LOG"
eval "$CMD"
RC=$?
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) DONE: rc=$RC" >> "$LOG"
exit $RC
