#!/usr/bin/env bash
#
# pc-smoothness.sh — hourly PC Smoothness automation for macOS (Apple Silicon).
# Written for stock macOS bash 3.2 (no associative arrays).
#
# 1. Terminates ORPHANED HEADLESS BROWSER TEST TREES while protecting:
#    active tests (playwright/puppeteer/cypress/...), Hermes, Pi, Codex,
#    VSCode, games, Blender, Docker/WSL, and interactive browsers.
# 2. Removes only STALE USER TEMP and CRASH files, plus stale service-temp
#    trees (git-worktree-aware: clean worktrees with merged/closed PRs and
#    plain scratch dirs over a week old — never dirty or live-referenced).
# 3. Audits CPU, memory, GPU temp/util, disk space, heavy processes.
# 4. REPORTS further opportunities without applying unapproved changes.
#
# Usage:
#   pc-smoothness.sh            run full cleanup + audit + summary (stdout)
#   pc-smoothness.sh --dry-run  report only, change nothing
#
# stdout = summary + opportunity lines (cron delivers to Discord).
# Full detail -> $HERMES_INFRA_DIR/logs/pc-smoothness.log

set -u

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:$PATH"
export LC_ALL=C
USER="${USER:-$(id -un)}"

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

INFRA_DIR="${HERMES_INFRA_DIR:-$HOME/Developer/hermes-infra}"
# HERMES_INFRA_DIR is exported as the LITERAL string '$HOME/...' in this
# environment — expand it so logs land in the real repo, not a '$HOME' dir.
case "$INFRA_DIR" in
  \$HOME/*) INFRA_DIR="$HOME/${INFRA_DIR#\$HOME/}" ;;
esac
LOG_FILE="$INFRA_DIR/logs/pc-smoothness.log"
mkdir -p "$INFRA_DIR/logs"

LOCK_DIR="/tmp/pc-smoothness.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  # Stale-lock recovery: if the lock is older than an hour, steal it
  # (a SIGKILLed run can never run the EXIT trap).
  if [ -d "$LOCK_DIR" ] && [ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +60 2>/dev/null)" ]; then
    rmdir "$LOCK_DIR" 2>/dev/null
    mkdir "$LOCK_DIR" 2>/dev/null || {
      echo "PC Smoothness: lock busy — skipping this hour."
      exit 0
    }
  else
    echo "PC Smoothness: another instance is already running — skipping this hour."
    exit 0
  fi
fi
PS_TABLE="$(mktemp /tmp/pc-smoothness.ps.XXXXXX)"
trap 'rm -f "$PS_TABLE"; rmdir "$LOCK_DIR" 2>/dev/null' EXIT

ORPHAN_MIN_AGE="${ORPHAN_MIN_AGE:-600}"  # seconds; only kill orphans older than this
TEMP_AGE_DAYS="+1"        # /tmp + /var/tmp: user files older than 24h
CRASH_AGE_DAYS="+7"       # DiagnosticReports older than 7 days
DISK_WARN_PCT=85
MEM_WARN_PCT=80
CPU_WARN_PCT=80

log() { printf '%s\n' "$*" >> "$LOG_FILE"; }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
human_bytes() {
  local b=$1
  awk -v b="$b" 'BEGIN{
    if (b >= 1073741824) printf "%.2f GB", b/1073741824
    else if (b >= 1048576) printf "%.2f MB", b/1048576
    else printf "%.1f KB", b/1024
  }'
}

age_seconds() {  # etime like "MM:SS", "HH:MM:SS" or "D-HH:MM:SS" -> seconds
  local e="$1" d h m s
  case "$e" in
    *-*) d="${e%%-*}"; e="${e#*-}";;
    *)   d=0;;
  esac
  h=0; m=0; s=0
  case "$e" in
    *:*:*) h="${e%%:*}"; e="${e#*:}"; m="${e%%:*}"; s="${e##*:}";;
    *:*)   m="${e%%:*}"; s="${e##*:}";;
    *)     s="$e";;
  esac
  # strip leading zeros — bash arithmetic treats 08/09 as invalid octal
  d="${d#0}"; h="${h#0}"; m="${m#0}"; s="${s#0}"
  [ -z "$d" ] && d=0; [ -z "$h" ] && h=0; [ -z "$m" ] && m=0; [ -z "$s" ] && s=0
  echo $(( (d*24 + h)*3600 + m*60 + s ))
}

# Process-table lookups (bash 3.2: no assoc arrays — use awk on a file)
get_ppid() { awk -v p="$1" '$1==p {print $2; exit}' "$PS_TABLE"; }
get_cmd()  { awk -v p="$1" '$1==p {$1=$2=$3=""; sub(/^ +/,""); print; exit}' "$PS_TABLE"; }

# Browser binaries that can run headless (matched on the full command line —
# executable paths contain spaces, e.g. ".../Google Chrome --headless").
BROWSER_BIN_PATTERN='Google Chrome Helper|Google Chrome|chrome|chromium|Chromium|headless_shell|chrome-headless-shell|firefox|Firefox|Microsoft Edge|msedge|brave|Brave Browser'

# Extra fingerprints that mark a headless browser as TEST-HARNESS-OWNED.
TEST_FP_PATTERN='playwright|puppeteer|chromedriver|selenium|webdriver|--user-data-dir=/tmp|--user-data-dir=/var/folders|--remote-debugging-port|headless_shell|chrome-headless-shell'

is_browser_cmd()  { echo "$1" | grep -qE "(^|/)($BROWSER_BIN_PATTERN)([ ]|$)"; }
is_headless_cmd() { echo "$1" | grep -q -- '--headless'; }
# headless_shell / chrome-headless-shell never carry --headless in argv
is_headless_browser() {
  is_browser_cmd "$1" || return 1
  is_headless_cmd "$1" && return 0
  case "$1" in *headless_shell*|*chrome-headless-shell*) return 0;; esac
  return 1
}
has_test_fp()      { echo "$1" | grep -qiE "$TEST_FP_PATTERN"; }

# launchd-managed job? (a launchd-spawned headless browser is NOT an orphan)
is_launchd_job() {
  launchctl list 2>/dev/null | awk -v p="$1" '$1==p {found=1} END{exit !found}'
}

# ---------------------------------------------------------------------------
# Phase 1 — orphaned headless browser termination
# ---------------------------------------------------------------------------
ps -axo pid=,ppid=,etime=,command= > "$PS_TABLE" 2>/dev/null

CANDIDATES=""     # space-separated pids of headless browser processes
while read -r pid _ etime cmd; do
  [ -z "$pid" ] && continue
  if is_headless_browser "$cmd"; then
    CANDIDATES="$CANDIDATES $pid"
  fi
done < "$PS_TABLE"

KILLED_CNT=0
ORPHANS_NOFP=""
for pid in $CANDIDATES; do
  pp="$(get_ppid "$pid")"
  [ -z "$pp" ] && continue
  # Only kill the ROOT of each headless tree (helpers die with their parent).
  case " $CANDIDATES " in *" $pp "*) continue;; esac
  [ "$pid" -le 1 ] && continue

  age="$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"
  [ -z "$age" ] && continue
  [ "$(age_seconds "$age")" -lt "$ORPHAN_MIN_AGE" ] && continue

  cmd="$(get_cmd "$pid")"
  # Parent must be dead (reparented to launchd) => truly orphaned tree.
  [ "$pp" != "1" ] && continue
  # A launchd-managed job is NOT an orphan — leave it alone.
  if is_launchd_job "$pid"; then
    log "SKIPPED launchd-managed headless browser: $pid"
    continue
  fi

  if ! has_test_fp "$cmd"; then
    ORPHANS_NOFP="$ORPHANS_NOFP $pid"
    continue  # ambiguous orphan — report, do not kill
  fi

  KILLED_CNT=$((KILLED_CNT+1))
  if [ "$DRY_RUN" -eq 0 ]; then
    kill -TERM "$pid" 2>/dev/null
    sleep 2
    kill -KILL "$pid" 2>/dev/null
  fi
  log "KILLED orphaned headless tree root: $pid ($cmd)"
done

# ---------------------------------------------------------------------------
# Phase 2 — stale user temp + crash file cleanup (batched, no per-file forks)
# ---------------------------------------------------------------------------
FILES_REMOVED=0
BYTES_REMOVED=0

cleanup_batch() {  # label find_args... -> count+bytes+delete stale files
  local label="$1"; shift
  local n bytes
  read -r n bytes < <(find "$@" -print0 2>/dev/null \
    | xargs -0 stat -f '%z' 2>/dev/null \
    | awk '{s+=$1; n++} END{print n+0, s+0}')
  [ -z "$n" ] && n=0; [ -z "$bytes" ] && bytes=0
  if [ "$n" -gt 0 ]; then
    FILES_REMOVED=$((FILES_REMOVED + n))
    BYTES_REMOVED=$((BYTES_REMOVED + bytes))
    log "REMOVED ${label}: ${n} files (${bytes} bytes)"
    if [ "$DRY_RUN" -eq 0 ]; then
      find "$@" -delete 2>/dev/null
    fi
  fi
}

# NOTE: /tmp is a symlink to /private/tmp and `find /tmp` silently skips it
# on this macOS — use the canonical path.
cleanup_batch "stale temp" /private/tmp /var/tmp -xdev -user "$USER" -type f \
  -mtime "$TEMP_AGE_DAYS" \
  ! -path '*playwright*' ! -path '*puppeteer*' ! -path '*chromium*' \
  ! -path '*chromedriver*' ! -path '*chrome_dev*' \
  ! -path '*cortana*' ! -path '*hermes*' ! -path '*pi-*' ! -path '*gateway*'

# empty temp dirs older than 1 day (only in non-dry-run)
if [ "$DRY_RUN" -eq 0 ]; then
  find /private/tmp /var/tmp -xdev -user "$USER" -type d -empty -mtime "$TEMP_AGE_DAYS" \
    ! -path '*playwright*' ! -path '*puppeteer*' \
    ! -path '*cortana*' ! -path '*hermes*' ! -path '*pi-*' ! -path '*gateway*' -delete 2>/dev/null
fi

CRASH_DIR="$HOME/Library/Logs/DiagnosticReports"
if [ -d "$CRASH_DIR" ]; then
  cleanup_batch "crash reports" "$CRASH_DIR" -maxdepth 1 -type f \
    \( -name '*.ips' -o -name '*.crash' -o -name '*.panic' \) -mtime "$CRASH_AGE_DAYS"
fi

# ---------------------------------------------------------------------------
# Phase 2b — stale service-temp tree pruning (git-worktree-aware)
# ---------------------------------------------------------------------------
# The desktop asked for auto-pruning of stale service-temp trees: over a week
# old, or sooner when verifiably dead (worktree branch merged/PR closed and
# the checkout is clean). Safety rules, in order:
#   1. NEVER touch a tree with any live process reference (lsof).
#   2. NEVER touch a git worktree with uncommitted changes (dirty).
#   3. `git worktree remove` only deletes the CHECKOUT — branch refs and all
#      commits stay in the repo + origin, so a clean worktree costs nothing
#      to prune even when its PR was closed-not-merged.
#   4. Plain scratch dirs (no .git): prune only when older than TREE_AGE_DAYS.
TREE_AGE_DAYS=7
TREE_MIN_KB=10240          # only consider trees > 10 MB (matches report threshold)
KEPT_TREES=""              # candidates that were reported but NOT pruned
PRUNED_TREE_CNT=0

is_worktree() {  # dir -> 0 if it's a registered git worktree
  [ -f "$1/.git" ] && grep -q '^gitdir:' "$1/.git" 2>/dev/null
}

wt_repo() {  # worktree dir -> main repo path ("" if unparseable)
  awk '/^gitdir:/{print $2}' "$1/.git" 2>/dev/null | sed 's#/.git/worktrees/.*##'
}

wt_branch() {  # worktree dir -> current branch ("" if detached)
  git -C "$1" symbolic-ref --short HEAD 2>/dev/null
}

wt_dirty() {  # worktree dir -> number of modified/staged (non-untracked) lines
  git -C "$1" status --porcelain 2>/dev/null | grep -v '^??' | wc -l | tr -d ' '
}

prune_tree() {  # path -> remove + accumulate totals
  local d="$1"
  local n sz repo
  n=$(find "$d" -type f 2>/dev/null | wc -l | tr -d ' ')
  [ -z "$n" ] && n=0
  sz=$(du -sk "$d" 2>/dev/null | awk '{print $1}')
  [ -z "$sz" ] && sz=0
  FILES_REMOVED=$((FILES_REMOVED + n))
  BYTES_REMOVED=$((BYTES_REMOVED + sz * 1024))
  PRUNED_TREE_CNT=$((PRUNED_TREE_CNT + 1))
  log "REMOVED stale service-temp tree: $d ($n files, $(human_bytes $((sz * 1024))))"
  if [ "$DRY_RUN" -eq 0 ]; then
    if is_worktree "$d"; then
      # Clean removal for registered worktrees: unregisters admin metadata
      # too (plain rm -rf leaves a stale .git/worktrees/<name> entry).
      repo="$(wt_repo "$d")"
      if [ -n "$repo" ] && ! git -C "$repo" worktree remove --force "$d" 2>/dev/null; then
        rm -rf "$d" 2>/dev/null
        git -C "$repo" worktree prune 2>/dev/null
      fi
    else
      rm -rf "$d" 2>/dev/null
    fi
  fi
}

for d in /private/tmp/*; do
  [ -d "$d" ] || continue
  name="$(basename "$d")"
  branch=""
  sz="$(du -sk "$d" 2>/dev/null | awk '{print $1}')"
  [ -z "$sz" ] && sz=0
  refs="$(lsof +D "$d" 2>/dev/null | grep -v '^COMMAND' | wc -l | tr -d ' ')"
  [ "${refs:-0}" -gt 0 ] && continue                      # live process -> never

  age_days=$(( ($(date +%s) - $(stat -f '%m' "$d")) / 86400 ))
  prune=0

  if is_worktree "$d"; then
    repo="$(wt_repo "$d")"
    branch="$(wt_branch "$d")"
    [ -n "$repo" ] || { KEPT_TREES="$KEPT_TREES $name(unresolved-repo)"; continue; }
    [ "$(wt_dirty "$d")" -eq 0 ] || { KEPT_TREES="$KEPT_TREES $name(dirty)"; continue; }

    if [ -n "$branch" ]; then
      # Verified dead: branch merged into main/staging (ff/rebase merges) ...
      if git -C "$repo" merge-base --is-ancestor "$branch" origin/main 2>/dev/null \
         || git -C "$repo" merge-base --is-ancestor "$branch" origin/staging 2>/dev/null; then
        prune=1
      fi
      # ... or gh reports the PR is merged (squash merges are not ancestors)
      # or closed-not-merged while the branch is still on origin (superseded
      # duplicate — the checkout is disposable; the branch ref survives).
      # Check ALL PRs for the branch: a merged PR trumps a later-closed dup.
      if [ "$prune" -eq 0 ] && command -v gh >/dev/null 2>&1; then
        remote="$(git -C "$repo" remote get-url origin 2>/dev/null | sed -E 's#https?://github.com/##; s#\.git$##')"
        if [ -n "$remote" ]; then
          states="$(GH_CONNECT_TIMEOUT=5 gh pr list --repo "$remote" --head "$branch" \
                    --state all --json state --jq '[.[].state] | join(",")' 2>/dev/null)"
          case "$states" in
            *MERGED*) prune=1 ;;
            *CLOSED*)
              if git -C "$repo" rev-parse --verify -q "origin/$branch" >/dev/null 2>&1; then
                prune=1   # closed + pushed to origin: work preserved remotely
              fi
              ;;
          esac
        fi
      fi
    fi
    # The desktop rule: anything over a week old is auto-prune material.
    [ "$age_days" -ge "$TREE_AGE_DAYS" ] && prune=1
  else
    # Plain scratch dir: stale-age rule only, and only if > 10 MB (small
    # scratch dirs are not worth the churn).
    [ "${sz:-0}" -ge "$TREE_MIN_KB" ] && [ "$age_days" -ge "$TREE_AGE_DAYS" ] && prune=1
  fi

  if [ "$prune" -eq 1 ]; then
    prune_tree "$d"
  else
    # Only report meaningful kept candidates (>10MB plain dirs, or any
    # registered worktree — tiny scratch dirs are noise).
    if is_worktree "$d" || [ "$sz" -ge "$TREE_MIN_KB" ]; then
      KEPT_TREES="$KEPT_TREES $name(${branch:-detached},${age_days}d,sz=$(human_bytes $((sz * 1024))))"
    fi
  fi
done

# ---------------------------------------------------------------------------
# Phase 3 — audit snapshot
# ---------------------------------------------------------------------------
# CPU busy% + disk0 tps from iostat (2 samples, use the last).
# Column layout with one disk arg: 1 KB/t  2 tps  3 MB/s  4 us  5 sy  6 id
IOSTAT_OUT="$(iostat -w 1 -c 2 disk0 2>/dev/null | tail -1)"
CPU_BUSY="$(echo "$IOSTAT_OUT" | awk '{printf "%d", 100-$6}')"
DISK_TPS="$(echo "$IOSTAT_OUT" | awk '{print $3}')"
DISK_STATE="idle"; [ "${DISK_TPS%.*}" -ge 100 ] 2>/dev/null && DISK_STATE="active"

# Memory used% via memory_pressure
MEM_FREE="$(memory_pressure -Q 2>/dev/null | awk '/free percentage/{print $NF}' | tr -d '%')"
if [ -n "$MEM_FREE" ]; then MEM_USED=$((100 - MEM_FREE)); else MEM_USED="?"; fi

# GPU temp + busy% — needs root (powermetrics). Graceful if unavailable.
GPU_TEMP="n/a"; GPU_BUSY="n/a"; PM_CMD=""
if command -v powermetrics >/dev/null 2>&1; then
  if sudo -n true 2>/dev/null; then
    PM_CMD="sudo -n powermetrics"
  else
    PW="$(grep '^SUDO_PASSWORD=' "$HOME/.hermes/.env" 2>/dev/null | cut -d= -f2-)"
    # use whatever password is in the env — it may legitimately contain spaces
    if [ -n "${PW:-}" ]; then
      PM_CMD="echo \"$PW\" | sudo -S powermetrics"
    fi
  fi
fi
if [ -n "$PM_CMD" ]; then
  PM_OUT="$(eval "$PM_CMD --samplers gpu_power -n 1 -i 500" 2>/dev/null)"
  GPU_TEMP="$(echo "$PM_OUT" | grep -iE 'GPU die temperature' | tail -1 | awk '{printf "%d", $4}')"
  GPU_BUSY="$(echo "$PM_OUT" | grep -iE 'GPU .*residency' | tail -1 | awk '{for(i=1;i<=NF;i++) if($i ~ /^[0-9.]+%$/) {printf "%d", $i; exit}}')"
  if [ -n "$GPU_TEMP" ]; then GPU_TEMP="${GPU_TEMP}C"; else GPU_TEMP="n/a"; fi
  [ -n "$GPU_BUSY" ] || GPU_BUSY="n/a"
fi

# Disk space
DISK_PCT="$(df -k / 2>/dev/null | tail -1 | awk '{print $5}' | tr -d '%')"
DISK_AVAIL_KB="$(df -k / 2>/dev/null | tail -1 | awk '{print $4}')"
DISK_AVAIL="$(human_bytes "$((DISK_AVAIL_KB * 1024))")"

# Heavy processes (top 5 by CPU)
HEAVY="$(ps -A -o pid=,pcpu=,pmem=,comm= -r 2>/dev/null | head -5 | awk '{printf "  %s %s%% CPU %s%% mem %s\n", $1, $2, $3, $4}')"

# ---------------------------------------------------------------------------
# Phase 4 — opportunities (REPORT ONLY, no changes)
# ---------------------------------------------------------------------------
OPPS=()
[ -n "$DISK_PCT" ] && [ "$DISK_PCT" -ge "$DISK_WARN_PCT" ] && \
  OPPS+=("Disk at ${DISK_PCT}% — consider freeing space (${DISK_AVAIL} free).")
{ [ "$MEM_USED" != "?" ] && [ "$MEM_USED" -ge "$MEM_WARN_PCT" ]; } && \
  OPPS+=("Memory at ${MEM_USED}% — consider closing heavy apps.")
[ "${CPU_BUSY:-0}" -ge "$CPU_WARN_PCT" ] && \
  OPPS+=("CPU at ${CPU_BUSY}% — sustained load detected.")
if [ "$GPU_TEMP" = "n/a" ]; then
  if [ -z "$PM_CMD" ]; then
    OPPS+=("GPU temp not sampled: powermetrics needs root — set a real SUDO_PASSWORD in ~/.hermes/.env or add a NOPASSWD sudoers rule for powermetrics.")
  else
    OPPS+=("GPU die temperature not exposed by this Mac's powermetrics (hardware/OS limit); GPU busy sampled.")
  fi
fi
if [ -n "$ORPHANS_NOFP" ]; then
  OPPS+=("Found orphaned headless browser(s) without test fingerprints — left untouched (manual review:$ORPHANS_NOFP).")
fi
# Stale test-runner sessions (protected, but worth flagging if idle >24h)
STALE_TESTS=""
for pid in $(pgrep -f 'playwright|puppeteer|chromedriver' 2>/dev/null); do
  [ -z "$pid" ] && continue
  info="$(ps -o etime=,command= -p "$pid" 2>/dev/null | head -1)"
  [ -z "$info" ] && continue
  etime="$(echo "$info" | awk '{print $1}')"
  cmd="$(echo "$info" | sed -E 's/^[^ ]+ +//')"
  a="$(age_seconds "$etime")"
  [ "$a" -ge 86400 ] && STALE_TESTS="$STALE_TESTS pid=$pid($(echo "$cmd" | awk '{print $1}' | sed 's#.*/##') ${etime})"
done
[ -n "$STALE_TESTS" ] && \
  OPPS+=("Stale test-runner session(s) idle >24h:$STALE_TESTS — restart if unused (not killed automatically).")

# Stale service-temp trees that Phase 2b decided to KEEP (verified or too
# fresh). Phase 2b prunes the verifiably-dead ones; these still need eyes.
[ -n "$KEPT_TREES" ] && \
  OPPS+=("Service-temp tree(s) kept (not yet auto-prunable):$KEPT_TREES")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
FREED="$(human_bytes "$BYTES_REMOVED")"
if [ "$KILLED_CNT" -gt 0 ]; then
  ORPHAN_MSG="terminated ${KILLED_CNT} orphaned headless instance(s)"
else
  ORPHAN_MSG="no orphaned headless instances"
fi

SUMMARY="PC Smoothness cleanup removed ${FILES_REMOVED} stale files, recovering about ${FREED}. Current snapshot: CPU ${CPU_BUSY:-?}%, memory ${MEM_USED}%, GPU ${GPU_TEMP}, disk ${DISK_STATE}, and ${ORPHAN_MSG}."
[ "$PRUNED_TREE_CNT" -gt 0 ] && SUMMARY="$SUMMARY Pruned ${PRUNED_TREE_CNT} stale service-temp tree(s)."

echo "$SUMMARY"
for o in "${OPPS[@]}"; do echo "  ⚠ $o"; done

log ""
log "=== $(date '+%Y-%m-%d %H:%M:%S') ${DRY_RUN:+DRY-RUN }==="
log "$SUMMARY"
log "Disk: ${DISK_PCT}% used, ${DISK_AVAIL} free. GPU busy: ${GPU_BUSY}. Heavy:"
log "$HEAVY"
for o in "${OPPS[@]}"; do log "OPP: $o"; done

exit 0
