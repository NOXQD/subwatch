import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sh(*args, env=None):
    return subprocess.run(["bash", *args], cwd=ROOT, capture_output=True, text=True, env=env, timeout=120)


def test_syntax():
    for script in ("install.sh", "uninstall.sh"):
        assert sh("-n", script).returncode == 0


def test_help_is_russian():
    out = sh("install.sh", "--help").stdout
    assert "--dry-run" in out and "показать, что будет сделано" in out
    assert "--purge" in sh("uninstall.sh", "--help").stdout


def test_unknown_flag():
    res = sh("install.sh", "--bogus")
    assert res.returncode == 2 and "Неизвестный параметр" in res.stderr


def test_dry_run_changes_nothing(tmp_path):
    import os

    env = {**os.environ, "HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "c"),
           "XDG_DATA_HOME": str(tmp_path / "d"), "UV_TOOL_BIN_DIR": str(tmp_path / "bin"),
           "PATH": "/usr/bin:/bin"}
    res = sh("install.sh", "--dry-run", "--no-sudo", env=env)
    assert res.returncode == 0, res.stderr
    assert "[dry-run]" in res.stdout and "Режим проверки" in res.stdout
    assert not (tmp_path / "c").exists() and not (tmp_path / "bin").exists()
    res = sh("uninstall.sh", "--dry-run", env=env)
    assert res.returncode == 0 and "уже удалён" in res.stdout
