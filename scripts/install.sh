#!/usr/bin/env bash
set -u

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
failures=0
link_failures=0
windows=0
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) windows=1 ;;
esac

link_skill() {
  local label=$1 destination=$2
  if ! mkdir -p "$(dirname "$destination")"; then
    echo "ERROR $label: cannot create parent directory for $destination"
    failures=$((failures + 1))
    return
  fi
  if [[ -L "$destination" ]]; then
    if ((windows)) && [[ -e "$destination.lnk" ]]; then
      echo "ERROR $label: $destination is a Windows shortcut (.lnk) made by an earlier install, not a real symlink; remove $destination.lnk and rerun"
      failures=$((failures + 1))
      return
    fi
    local current
    current=$(readlink "$destination")
    if [[ "$current" == "$root" ]]; then
      echo "ok $label: $destination -> $root"
    else
      echo "ERROR $label: $destination already points to $current; not overwriting"
      failures=$((failures + 1))
    fi
  elif [[ -e "$destination" ]]; then
    echo "ERROR $label: $destination already exists and is not a symlink; not overwriting"
    if ((windows)); then
      echo "HINT $label: $destination may be a copy from an earlier broken install; if so, remove it yourself and rerun this installer (with Developer Mode on)."
    fi
    failures=$((failures + 1))
  else
    MSYS="${MSYS:+$MSYS }winsymlinks:nativestrict" \
      CYGWIN="${CYGWIN:+$CYGWIN }winsymlinks:nativestrict" \
      ln -s "$root" "$destination"
    if [[ -L "$destination" ]] && [[ "$(readlink "$destination")" == "$root" ]] &&
      ! { ((windows)) && [[ -e "$destination.lnk" ]]; }; then
      echo "linked $label: $destination -> $root"
    else
      echo "ERROR $label: could not create a symlink to $root at $destination"
      # Leave unexpected artifacts for inspection; never recursively delete here.
      if [[ -e "$destination" && ! -L "$destination" ]]; then
        echo "HINT $label: remove the non-symlink left at $destination before rerunning."
      fi
      failures=$((failures + 1))
      link_failures=$((link_failures + 1))
    fi
  fi
}

link_skill "Claude Code" "$HOME/.claude/skills/orca-collab"
pi_root=${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}
link_skill "pi" "$pi_root/skills/orca-collab"
link_skill "Codex（~/.agents/skills，pi 也讀）" "$HOME/.agents/skills/orca-collab"

if ((link_failures > 0 && windows)); then
  echo "HINT Windows: enable Developer Mode (or run as administrator) to allow native symlinks."
  echo "Remove any copied directories at the destinations reported above, then rerun this installer."
fi

((failures == 0))
