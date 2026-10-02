#!/usr/bin/env bash
set -u

parse_file=""
out_file=""
run_id=""
terminal=""
types="worker_done,escalation,question"
timeout_ms="300000"
ack=""
body_chars=240

usage() {
  cat <<'EOF'
usage:
  orca-wait.sh --parse <raw-output> [--out <copy>] [--body-chars N]
  orca-wait.sh --run R --terminal C [--types T] [--timeout-ms N] [--ack D] [--out FILE]
EOF
}

while (($#)); do
  case "$1" in
    --parse) parse_file=${2:?}; shift 2 ;;
    --out) out_file=${2:?}; shift 2 ;;
    --run) run_id=${2:?}; shift 2 ;;
    --terminal) terminal=${2:?}; shift 2 ;;
    --types) types=${2:?}; shift 2 ;;
    --timeout-ms) timeout_ms=${2:?}; shift 2 ;;
    --ack) ack=${2:?}; shift 2 ;;
    --body-chars) body_chars=${2:?}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if [[ -n "$parse_file" ]]; then
  [[ -f "$parse_file" ]] || { echo "ERROR: parse file not found: $parse_file" >&2; exit 1; }
  if [[ -z "$out_file" ]]; then
    out_file=$parse_file
  elif [[ "$out_file" != "$parse_file" ]]; then
    cp "$parse_file" "$out_file" || exit 1
  fi
else
  [[ -n "$run_id" && -n "$terminal" ]] || { echo "ERROR: --run and --terminal are required" >&2; exit 1; }
  if [[ -z "$out_file" ]]; then
    out_file="${TMPDIR:-/tmp}/orca-wait-$(date +%Y%m%d-%H%M%S)-$$.log"
  fi
  orca_cmd=(orca)
  if [[ -n "${ORCA_CLI_COMMAND:-}" ]]; then read -r -a orca_cmd <<<"$ORCA_CLI_COMMAND"; fi
  command=("${orca_cmd[@]}" orchestration check --run "$run_id" --terminal "$terminal" --wait --types "$types" --timeout-ms "$timeout_ms" --json)
  [[ -z "$ack" ]] || command+=(--ack "$ack")
  set +e
  "${command[@]}" >"$out_file" 2>&1
  command_rc=$?
  set -e
  if ((command_rc != 0)); then
    echo "ERROR: orca check exited $command_rc; raw output: $out_file" >&2
    cat "$out_file" >&2
    exit 1
  fi
fi

echo "raw-output=$out_file"
set +e
python3 - "$out_file" "$body_chars" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
limit = int(sys.argv[2])
text = path.read_text(encoding="utf-8", errors="replace")
decoder = json.JSONDecoder()
objects = []
pos = 0
while pos < len(text):
    start = text.find("{", pos)
    if start < 0:
        break
    try:
        obj, end = decoder.raw_decode(text, start)
    except json.JSONDecodeError:
        pos = start + 1
        continue
    if not (isinstance(obj, dict) and obj.get("_keepalive") is True):
        objects.append(obj)
    pos = end

if not objects:
    print("ERROR: no non-keepalive JSON object found", file=sys.stderr)
    raise SystemExit(1)
result_obj = objects[-1]
if not isinstance(result_obj, dict) or result_obj.get("ok") is not True:
    if isinstance(result_obj, dict):
        error = result_obj.get("error")
        if isinstance(error, dict) and error.get("code"):
            print(f"ERROR: orca check returned error.code={error['code']}", file=sys.stderr)
    print("ERROR: final JSON is not an ok result", file=sys.stderr)
    print(json.dumps(result_obj, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)
result = result_obj.get("result")
if not isinstance(result, dict):
    print("ERROR: final JSON has no result object", file=sys.stderr)
    raise SystemExit(1)
messages = result.get("messages") or []
count = result.get("count", len(messages))
timed_out = bool(result.get("timedOut", False))
delivery = result.get("deliveryId")
print(f"timedOut={str(timed_out).lower()} count={count} deliveryId={delivery or '-'}")
for message in messages:
    if not isinstance(message, dict):
        continue
    mtype = message.get("type", "unknown")
    subject = message.get("subject") or ""
    body = str(message.get("body") or "").replace("\n", " ")
    if len(body) > limit:
        body = body[:limit] + "…"
    payload = json.dumps(message.get("payload"), ensure_ascii=False, separators=(",", ":"))
    print(f"[{mtype}] {subject}")
    print(f"  body: {body}")
    print(f"  payload: {payload}")
if timed_out:
    raise SystemExit(3)
if count and messages:
    raise SystemExit(0)
print("ERROR: result contained no messages and was not marked timedOut", file=sys.stderr)
raise SystemExit(1)
PY
parse_rc=$?
set -e

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
    set +e
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
print(" ".join((f"provider={fields[0]}", f"bucket={fields[1]}", f"used_pct={fields[2]}", f"decision={fields[3]}")))
PY
    )
    fields_rc=$?
    set -e
    if ((fields_rc == 0)); then
      echo "quota[$provider]: $quota_fields"
    else
      first_error=$(head -n 1 "$quota_err")
      [[ -n "$first_error" ]] || first_error=$(head -n 1 "$quota_out")
      [[ -n "$first_error" ]] || first_error="exit $quota_rc"
      echo "quota[$provider]: SKIP (查詢失敗: $first_error)"
    fi
    rm -f "$quota_out" "$quota_err"
  done
else
  echo "quota[claude]: SKIP cc-quota/agent-orch not found"
  echo "quota[codex]: SKIP cc-quota/agent-orch not found"
fi

exit "$parse_rc"
