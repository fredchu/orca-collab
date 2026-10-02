import os
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.py"
PREFLIGHT = ROOT / "scripts" / "preflight.sh"


def run_bootstrap(tmp_path, *args):
    env = os.environ.copy()
    env["ORCA_COLLAB_DIR"] = str(tmp_path / "collab")
    return subprocess.run(
        [sys.executable, str(BOOTSTRAP), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_collab_briefing_has_fixed_sections_and_command_mode(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    result = run_bootstrap(tmp_path, "--topic", "orca-review", "--repo", str(repo), "--mode", "collab")
    assert result.returncode == 0, result.stderr
    briefing = tmp_path / "collab" / f"{date.today():%Y%m%d}-orca-review" / "briefing.md"
    body = briefing.read_text()
    for heading in ("## 你是誰", "## 任務", "## 角色與席位", "## 硬約束", "## 檔案所有權", "## 驗收", "## 回報格式", "## 意圖 gate", "## 收尾"):
        assert heading in body
    assert "pi --model" in body and "--model <待填 Fable model>" in body
    assert "Role: orchestrator" in result.stdout
    assert "run-create" in result.stdout and '--from "$C"' in result.stdout
    assert "--worktree new-child --name orca-review" in result.stdout
    assert "--agent claude" in result.stdout
    assert "orchestration check" in result.stdout and '--terminal "$C"' in result.stdout
    assert "開 implementer／verifier" in result.stdout


def test_mode_difference_is_visible_in_briefing_and_commands(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    result = run_bootstrap(tmp_path, "--topic", "single-job", "--repo", str(repo), "--mode", "single")
    assert result.returncode == 0, result.stderr
    body = (tmp_path / "collab" / f"{date.today():%Y%m%d}-single-job" / "briefing.md").read_text()
    assert "bootstrap mode: single; sessions: 1" in body
    assert "沒有第二層席位" in body
    assert "Role: single-worker" in result.stdout
    assert "直接等 single worker" in result.stdout


def test_invalid_slugs_are_rejected_without_creating_directory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for slug in ("中文", "Upper", "../escape", "two--dashes", "space here", "-edge"):
        result = run_bootstrap(tmp_path, f"--topic={slug}", "--repo", str(repo), "--mode", "single")
        assert result.returncode != 0, slug
        assert "只准 [a-z0-9-]" in result.stderr
    assert not (tmp_path / "collab").exists()


def _write_executable(path, body):
    path.write_text(body)
    path.chmod(0o755)


def _preflight_env(tmp_path, decision):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "orca", "#!/bin/sh\nif [ \"$1\" = status ]; then echo '{\"ok\":true,\"result\":{\"runtime\":{\"state\":\"ready\"}}}'; exit 0; fi\nexit 0\n")
    _write_executable(fake_bin / "pi", "#!/bin/sh\necho 'pi test-version'\n")
    _write_executable(
        fake_bin / "agent-orch",
        f'''#!/bin/sh
provider="$4"
printf '{{"provider":"%s","bucket":"test_window","used_pct":42,"decision":"{decision}"}}\\n' "$provider"
''',
    )
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"
    return env


def test_preflight_dirty_repo_is_warn(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "dirty.txt").write_text("dirty")
    env = _preflight_env(tmp_path, "allow")
    result = subprocess.run(["bash", str(PREFLIGHT), "--repo", str(repo)], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"WARN repo dirty: {repo}（1 個未提交改動" in result.stdout
    assert "看不到這些" in result.stdout
    assert "?? dirty.txt" in result.stdout
    assert "PASS orca runtime ready" in result.stdout


def test_preflight_non_git_folder_fails_with_git_init_hint(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    env = _preflight_env(tmp_path, "allow")
    result = subprocess.run(["bash", str(PREFLIGHT), "--repo", str(folder)], capture_output=True, text=True, env=env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "unbound variable" not in result.stderr  # 全形括號緊接 $repo 會被 bash 吃進變數名
    assert f"FAIL repo: not a git repo: {folder}（" in result.stdout
    assert "git init" in result.stdout


def test_preflight_quota_allow_prints_four_fields_and_passes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    result = subprocess.run(
        ["bash", str(PREFLIGHT), "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=_preflight_env(tmp_path, "allow"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS quota: provider=claude bucket=test_window used_pct=42 decision=allow" in result.stdout
    assert "PASS quota: provider=codex bucket=test_window used_pct=42 decision=allow" in result.stdout
    assert '"decision"' not in result.stdout


def test_preflight_quota_deny_fails(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    result = subprocess.run(
        ["bash", str(PREFLIGHT), "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=_preflight_env(tmp_path, "deny"),
    )
    assert result.returncode == 1
    assert "FAIL quota: provider=claude bucket=test_window used_pct=42 decision=deny" in result.stdout
    assert "FAIL quota: provider=codex bucket=test_window used_pct=42 decision=deny" in result.stdout


def test_preflight_prefers_cc_quota_over_agent_orch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    env = _preflight_env(tmp_path, "deny")  # agent-orch 會回 deny；有 cc-quota 就不該用到它
    _write_executable(
        tmp_path / "bin" / "cc-quota",
        '''#!/bin/sh
printf '{"source":"orca","bucket":"weekly","used_pct":61,"decision":"allow"}\\n'
''',
    )
    result = subprocess.run(["bash", str(PREFLIGHT), "--repo", str(repo)], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS quota: provider=claude bucket=weekly used_pct=61 decision=allow" in result.stdout
    assert "PASS quota: provider=codex bucket=weekly used_pct=61 decision=allow" in result.stdout
