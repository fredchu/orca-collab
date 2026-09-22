import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "scripts" / "install.sh"
BASH = shutil.which("bash") or "bash"


def run_install(tmp_path, shim=None, extra_env=None):
    home = tmp_path / "home"
    pi_root = tmp_path / "pi"
    env = os.environ.copy()
    env["HOME"] = home.as_posix()
    env["PI_CODING_AGENT_DIR"] = pi_root.as_posix()
    if extra_env:
        env.update(extra_env)
    command = [BASH, INSTALL.as_posix()]
    if shim is not None:
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        executable = fake_bin / "ln"
        executable.write_text("#!/bin/sh\n" + shim, encoding="utf-8", newline="\n")
        executable.chmod(0o755)
        env["INSTALL_TEST_BIN"] = fake_bin.as_posix()
        # Set PATH inside Bash so Windows drive letters are not path separators.
        command = [
            BASH, "-c",
            'export PATH="$(cd "$INSTALL_TEST_BIN" && pwd):$PATH"; exec bash "$1"',
            "install-test", INSTALL.as_posix(),
        ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=env)
    return result, home, pi_root


def test_install_creates_three_links_and_is_idempotent(tmp_path):
    first, home, pi_root = run_install(tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr
    links = (
        home / ".claude" / "skills" / "orca-collab",
        pi_root / "skills" / "orca-collab",
        home / ".agents" / "skills" / "orca-collab",
    )
    assert first.stdout.count("linked ") == 3
    assert all(link.is_symlink() and link.resolve() == ROOT for link in links)

    second, _, _ = run_install(tmp_path)
    assert second.returncode == 0, second.stdout + second.stderr
    assert second.stdout.count("ok ") == 3
    assert all(link.is_symlink() and link.resolve() == ROOT for link in links)


def test_install_refuses_wrong_existing_symlink(tmp_path):
    home = tmp_path / "home"
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    destination = home / ".claude" / "skills" / "orca-collab"
    destination.parent.mkdir(parents=True)
    destination.symlink_to(wrong)

    result, _, _ = run_install(tmp_path)
    assert result.returncode == 1
    assert "ERROR Claude Code" in result.stdout
    assert "not overwriting" in result.stdout
    assert destination.is_symlink() and destination.resolve() == wrong.resolve()
    assert "HINT Windows:" not in result.stdout


@pytest.mark.parametrize("shim", [
    'cp -R "$2" "$3"\n',
    'exit 0\n',
    'exit 9\n',
    'ln_real=$(command -p -v ln); "$ln_real" -s "$HOME" "$3"\n',
])
def test_install_rejects_invalid_ln_results(tmp_path, shim):
    result, home, pi_root = run_install(tmp_path, shim)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "linked " not in result.stdout
    assert result.stdout.count("ERROR ") == 3
    assert "ERROR Claude Code" in result.stdout
    if os.name == "nt":
        assert result.stdout.count("HINT Windows: enable Developer Mode") == 1
        assert "then rerun this installer" in result.stdout
    if shim.startswith("cp"):
        destination = home / ".claude/skills/orca-collab"
        assert destination.is_dir() and not destination.is_symlink()
        assert (destination / "scripts/install.sh").is_file()
        assert "remove the non-symlink left at " in result.stdout
        assert "orca-collab before rerunning" in result.stdout


def test_install_preserves_existing_directory(tmp_path):
    destination = tmp_path / "home/.claude/skills/orca-collab"
    destination.mkdir(parents=True)
    marker = destination / "keep.txt"
    marker.write_bytes(b"existing user data")
    result, _, _ = run_install(tmp_path)
    assert result.returncode == 1
    assert "ERROR Claude Code" in result.stdout
    assert "linked Claude Code" not in result.stdout
    assert "not overwriting" in result.stdout
    if os.name == "nt":
        assert (
            "may be a copy from an earlier broken install; if so, remove it yourself "
            "and rerun this installer (with Developer Mode on)."
        ) in result.stdout
    assert marker.read_bytes() == b"existing user data"
    assert list(destination.iterdir()) == [marker]
    assert not destination.is_symlink()
    assert "HINT Windows:" not in result.stdout
    assert result.stdout.count("linked ") == 2


def test_install_parent_creation_failure_continues(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    blocker = home / ".claude"
    blocker.write_bytes(b"not a directory")
    result, _, _ = run_install(tmp_path)
    assert result.returncode == 1
    assert "ERROR Claude Code: cannot create parent directory" in result.stdout
    assert "linked Claude Code" not in result.stdout
    assert result.stdout.count("linked ") == 2
    assert blocker.read_bytes() == b"not a directory"
    assert "HINT Windows:" not in result.stdout


def test_install_appends_strict_options_for_ln(tmp_path):
    shim = (
        'case "$MSYS" in "existing winsymlinks:deepcopy winsymlinks:nativestrict") ;; *) exit 8 ;; esac\n'
        'case "$CYGWIN" in "existing winsymlinks:sys winsymlinks:nativestrict") ;; *) exit 8 ;; esac\n'
        # macOS 的 ln 在 /bin，Linux／Git Bash 在 /usr/bin（或兩者都有）
        'for real in /bin/ln /usr/bin/ln; do [ -x "$real" ] && exec "$real" "$@"; done\n'
        'exit 9\n'
    )
    result, _, _ = run_install(tmp_path, shim, {
        "MSYS": "existing winsymlinks:deepcopy",
        "CYGWIN": "existing winsymlinks:sys",
    })
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("linked ") == 3


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows Git Bash .lnk shortcut support")
@pytest.mark.parametrize("wrong_target", [False, True])
def test_install_refuses_existing_windows_shortcut(tmp_path, wrong_target):
    home = tmp_path / "home"
    destination = home / ".claude/skills/orca-collab"
    destination.parent.mkdir(parents=True)
    target = ROOT
    if wrong_target:
        target = tmp_path / "wrong"
        target.mkdir()
    env = os.environ.copy()
    env["HOME"] = home.as_posix()
    env["PI_CODING_AGENT_DIR"] = (tmp_path / "pi").as_posix()
    setup = subprocess.run(
        [BASH, "-c",
         'root=$(cd "$1" && pwd -P); MSYS=winsymlinks:lnk ln -s "$root" "$2"; '
         '[[ -L "$2" && -e "$2.lnk" ]]',
         "shortcut-test", target.as_posix(), destination.as_posix()],
        env=env, capture_output=True, text=True, encoding="utf-8",
    )
    assert setup.returncode == 0, setup.stdout + setup.stderr
    shortcut = Path(str(destination) + ".lnk")
    original = shortcut.read_bytes()
    result, _, _ = run_install(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "ERROR Claude Code:" in result.stdout
    assert "is a Windows shortcut (.lnk)" in result.stdout
    assert "orca-collab.lnk and rerun" in result.stdout
    assert "ok Claude Code:" not in result.stdout
    assert "linked Claude Code:" not in result.stdout
    assert "HINT Windows:" not in result.stdout
    assert result.stdout.count("linked ") == 2
    assert shortcut.read_bytes() == original
