#!/usr/bin/env bash
set -u

repo="${ORCA_COLLAB_REPO:-}"
while (($#)); do
  case "$1" in
    --repo) [[ $# -ge 2 ]] || { echo "FAIL repo: --repo 需要路徑"; exit 1; }; repo=$2; shift 2 ;;
    -h|--help) echo "usage: $0 --repo <target-repo>"; exit 0 ;;
    *) echo "FAIL arguments: unknown argument $1"; exit 1 ;;
  esac
done

failures=0
pass() { printf 'PASS %s\n' "$*"; }
fail() { printf 'FAIL %s\n' "$*"; failures=$((failures + 1)); }
skip() { printf 'SKIP %s\n' "$*"; }

if [[ -z "$repo" ]]; then
  fail "repo: use --repo or ORCA_COLLAB_REPO"
elif [[ ! -d "$repo" ]]; then
  fail "repo: directory not found: $repo"
elif ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  fail "repo: not a git repo: ${repo}（Orca 對非 git 資料夾只給一個工作區，無法平行開 worktree；要隔離派工先 git init）"
else
  dirty=$(git -C "$repo" status --porcelain 2>&1) || dirty="<git status failed>"
  if [[ -z "$dirty" ]]; then
    pass "repo clean: $repo"
  else
    dirty_count=$(printf '%s\n' "$dirty" | wc -l | tr -d ' ')
    printf 'WARN repo dirty: %s（%s 個未提交改動，工人在 worktree 從 base branch 切出，看不到這些）\n' "$repo" "$dirty_count"
    printf '%s\n' "$dirty" | sed 's/^/  /'
  fi
fi

orca_cmd=(orca)
if [[ -n "${ORCA_CLI_COMMAND:-}" ]]; then
  read -r -a orca_cmd <<<"$ORCA_CLI_COMMAND"
fi
if command -v "${orca_cmd[0]}" >/dev/null 2>&1; then
  status_out=$("${orca_cmd[@]}" status --json 2>&1)
  if STATUS_JSON="$status_out" python3 - <<'PY' >/dev/null 2>&1
import json, os
obj = json.loads(os.environ["STATUS_JSON"])
runtime = obj.get("result", {}).get("runtime", obj.get("runtime", {}))
raise SystemExit(0 if runtime.get("state") == "ready" else 1)
PY
  then pass "orca runtime ready"
  else fail "orca runtime not ready: $status_out"
  fi

  if "${orca_cmd[@]}" terminal create --help >/dev/null 2>&1; then
    pass "orca terminal create --help"
  else
    fail "orca terminal create --help unavailable"
  fi
else
  fail "orca command not found: ${orca_cmd[0]}"
fi

if command -v pi >/dev/null 2>&1; then
  pi_version=$(pi --version 2>&1) && pass "pi: $pi_version" || fail "pi --version failed: $pi_version"
else
  fail "pi command not found"
fi

# cc-quota＝agent-orch quota gate 與 orca account list 互為替代；沒有才直接用 agent-orch。
if command -v cc-quota >/dev/null 2>&1; then
  quota_cmd=(cc-quota --provider)
elif command -v agent-orch >/dev/null 2>&1; then
  quota_cmd=(agent-orch quota check --provider)
else
  quota_cmd=()
fi

if ((${#quota_cmd[@]})); then
  for provider in claude codex; do
    quota_out=$(mktemp)
    quota_err=$(mktemp)
    "${quota_cmd[@]}" "$provider" >"$quota_out" 2>"$quota_err"
    quota_rc=$?
    quota_fields=$(python3 - "$quota_out" "$provider" <<'PY'
import json
import sys
from pathlib import Path

try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    fields = (
        str(data.get("provider") or sys.argv[2]),
        str(data.get("bucket") or "-"),
        str(data.get("used_pct") if data.get("used_pct") is not None else "-"),
        str(data["decision"]),
    )
except (OSError, ValueError, KeyError, TypeError):
    raise SystemExit(1)
print("\t".join(fields))
PY
    )
    fields_rc=$?
    if ((fields_rc == 0)); then
      IFS=$'\t' read -r result_provider bucket used_pct decision <<<"$quota_fields"
      summary="provider=$result_provider bucket=$bucket used_pct=$used_pct decision=$decision"
      if [[ "$decision" == "allow" ]]; then pass "quota: $summary"; else fail "quota: $summary"; fi
    else
      first_error=$(head -n 1 "$quota_err")
      [[ -n "$first_error" ]] || first_error=$(head -n 1 "$quota_out")
      [[ -n "$first_error" ]] || first_error="exit $quota_rc"
      fail "quota $provider query failed: $first_error"
    fi
    rm -f "$quota_out" "$quota_err"
  done
else
  skip "quota claude: cc-quota/agent-orch not found"
  skip "quota codex: cc-quota/agent-orch not found"
fi

((failures == 0))
