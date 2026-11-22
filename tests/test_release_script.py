"""scripts/release.py: one release per batch of merged changes, made by the workflow instead of by each agent."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_script", ROOT / "scripts" / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

LOCK = '[[package]]\nname = "other"\nversion = "9.9.9"\n\n[[package]]\nname = "decomprepair"\nversion = "0.5.1"\nsource = { editable = "." }\n'


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    # like a CI runner: no git identity configured anywhere, so the script supplies its own
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(origin), str(work))
    (work / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.5.1"\n')
    (work / "uv.lock").write_text(LOCK)
    git(work, "add", ".")
    git(work, "commit", "-qm", "Release decomprepair 0.5.1: start")
    git(work, "tag", "-a", "v0.5.1", "-m", "0.5.1")
    git(work, "push", "-q", "origin", "HEAD:main", "v0.5.1")
    return work


def change(work, name, subject):
    (work / name).write_text(subject)
    git(work, "add", ".")
    git(work, "commit", "-qm", subject)


def test_nothing_is_released_when_main_has_no_change_since_the_last_tag(repo, capsys):
    assert release.plan(repo) is None
    assert release.release(repo, push=False) is None
    assert "nothing to release" in capsys.readouterr().out


def test_a_batch_of_changes_becomes_one_patch_release_with_notes(repo):
    change(repo, "a", "ternary_clamp_split: a clamp as a copy (#12)")
    change(repo, "b", "Fix the walk shape test")
    version, subjects = release.plan(repo)
    assert version == "0.5.2" and subjects == ["ternary_clamp_split: a clamp as a copy", "Fix the walk shape test"]
    assert release.release(repo, push=False) == "0.5.2"
    assert git(repo, "log", "-1", "--format=%s").startswith("Release decomprepair 0.5.2: 2 changes: ternary_clamp_split;")
    assert 'version = "0.5.2"' in (repo / "pyproject.toml").read_text()
    lock = (repo / "uv.lock").read_text()
    assert 'name = "decomprepair"\nversion = "0.5.2"' in lock and 'name = "other"\nversion = "9.9.9"' in lock
    assert git(repo, "tag", "--list", "v0.5.2") == "v0.5.2"
    assert "- Fix the walk shape test" in (repo / "release-notes.md").read_text()
    assert release.plan(repo) is None  # the release commit itself is not a change to release


def test_release_pushes_the_commit_and_tag_together_and_survives_a_moving_main(repo, tmp_path):
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    change(repo, "a", "Add one family (#3)")
    change(other, "z", "Someone else's merge")
    git(other, "push", "-q", "origin", "HEAD:main")  # main moves before the release is pushed
    assert release.release(repo, push=True) == "0.5.2"
    assert git(tmp_path / "origin.git", "tag", "--list", "v0.5.2") == "v0.5.2"
    subjects = git(tmp_path / "origin.git", "log", "--format=%s", "main").splitlines()
    assert subjects[0].startswith("Release decomprepair 0.5.2:") and "Someone else's merge" in subjects


def test_a_manual_bump_above_the_last_tag_is_released_as_named_without_another_bump(repo):
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.6.0"\n')
    (repo / "uv.lock").write_text(LOCK.replace("0.5.1", "0.6.0"))
    change(repo, "a", "Prepare 0.6")
    assert release.release(repo, push=False) == "0.6.0"
    assert git(repo, "log", "-1", "--format=%s") == "Prepare 0.6"  # no extra release commit
    assert git(repo, "tag", "--list", "v0.6.0") == "v0.6.0"


def test_tags_are_compared_as_numbers_and_other_tags_are_ignored(repo):
    git(repo, "tag", "v0.5.9")
    git(repo, "tag", "v0.5.10")
    git(repo, "tag", "v1.0.10-rr")
    assert release.last_tag(repo) == "v0.5.10"
    assert release.next_version("v0.5.10", "0.5.1") == "0.5.11"


def test_a_merged_change_titled_release_still_counts_but_a_version_only_commit_does_not(repo):
    change(repo, "a", "Release decomprepair 0.5.2: some family")
    assert release.plan(repo)[1] == ["Release decomprepair 0.5.2: some family"]
    release.release(repo, push=False)
    assert release.plan(repo) is None
