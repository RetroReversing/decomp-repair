#!/usr/bin/env python3
"""Release decomprepair: bump the version, tag it and say what changed, once per batch of merged changes.

Agents used to tag releases themselves and raced each other for the next number (a tag made locally was taken meanwhile,
a bump landed on a pin that did not exist yet). The release workflow (.github/workflows/release.yml) now does it, on every
merge to main and on a schedule: if main has commits since the last tag, it bumps the patch version in pyproject.toml and
uv.lock, commits `Release decomprepair X.Y.Z: <what changed>`, pushes that commit and the tag together, and creates the
GitHub release. Changes are merged to main with no bump and no tag.

    release.py plan                 print what would be released: the version, the notes, or nothing to release
    release.py release [--no-push]  do it (the workflow's step); with --no-push, commit and tag locally only

With GITHUB_OUTPUT set, `plan` and `release` also write `version=` and (`release`) `notes_file=` for later steps.
The pin in decompdecomp follows by its own workflow (library-pin.yml there). A manual release still works: a
pyproject.toml version above the last tag is released as it is, with no extra bump.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
VERSION_FILES = {"pyproject.toml", "uv.lock"}
PR_SUFFIX = re.compile(r"\s*\(#\d+\)$")
SUMMARY_CHARS = 110
PUSH_ATTEMPTS = 3
VERSION_LINE = re.compile(r'(?m)^version = "[^"]+"')
LOCK_BLOCK = re.compile(r'(\[\[package\]\]\nname = "decomprepair"\nversion = )"[^"]+"')


def git(*args, cwd=".", check=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check).stdout.strip()


def identity(cwd="."):
    """`-c user.name/user.email` for a commit or annotated tag when git has none configured (a CI runner, a test)."""
    missing = [key for key in ("user.name", "user.email") if not git("config", key, cwd=cwd, check=False)]
    defaults = {"user.name": "decomp-repair release", "user.email": "actions@users.noreply.github.com"}
    return [part for key in missing for part in ("-c", f"{key}={defaults[key]}")]


def parse(version):
    return tuple(int(part) for part in version.split("."))


def last_tag(cwd="."):
    tags = [t for t in git("tag", "--list", "v*", cwd=cwd).split() if TAG.match(t)]
    return max(tags, key=lambda t: parse(t[1:])) if tags else None


def unreleased(tag, cwd="."):
    """Subjects of the merged changes since `tag`, oldest first. A commit that touches only the version files is a
    release commit (this script's own), not a change; going by what a commit touches rather than its subject means a
    merged change titled "Release decomprepair ..." still counts."""
    span = f"{tag}..HEAD" if tag else "HEAD"
    log = git("log", "--no-merges", "--reverse", "--format=%x1e%s", "--name-only", span, cwd=cwd)
    subjects = []
    for block in log.split("\x1e"):  # (git() strips whitespace, which includes the first separator)
        subject, *files = [line for line in block.splitlines() if line] or [""]
        if subject and not set(files) <= VERSION_FILES:
            subjects.append(PR_SUFFIX.sub("", subject))
    return subjects


def project_version(cwd="."):
    match = VERSION_LINE.search((Path(cwd) / "pyproject.toml").read_text())
    return match[0].split('"')[1]


def next_version(tag, in_project):
    """The last tag's patch plus one, unless pyproject.toml already names a higher version (a manual release)."""
    bumped = ".".join(map(str, (lambda v: (v[0], v[1], v[2] + 1))(parse(tag[1:])))) if tag else in_project
    return in_project if tag and parse(in_project) > parse(tag[1:]) else bumped


def summary(subjects):
    if len(subjects) == 1:
        return subjects[0]
    text = f"{len(subjects)} changes: " + "; ".join(s.split(":")[0] if ":" in s[:60] else s[:40] for s in subjects)
    return text if len(text) <= SUMMARY_CHARS else text[:SUMMARY_CHARS - 1].rstrip() + "…"


def plan(cwd="."):
    """(version, subjects) to release, or None when main has nothing new since the last tag."""
    tag = last_tag(cwd)
    subjects = unreleased(tag, cwd)
    if not subjects:
        return None
    return next_version(tag, project_version(cwd)), subjects


def bump_files(version, cwd="."):
    path = Path(cwd) / "pyproject.toml"
    path.write_text(VERSION_LINE.sub(f'version = "{version}"', path.read_text(), count=1))
    lock = Path(cwd) / "uv.lock"
    if lock.exists():
        lock.write_text(LOCK_BLOCK.sub(rf'\1"{version}"', lock.read_text(), count=1))


def notes(version, subjects):
    return f"decomprepair {version}\n\n" + "\n".join(f"- {s}" for s in subjects) + "\n"


def output(**values):
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a") as out:
            out.writelines(f"{key}={value}\n" for key, value in values.items())


def release(cwd=".", push=True, remote="origin", notes_path="release-notes.md"):
    for attempt in range(1, PUSH_ATTEMPTS + 1):
        found = plan(cwd)
        if found is None:
            print("nothing to release: main has no changes since the last tag")
            return None
        version, subjects = found
        tag = f"v{version}"
        if git("tag", "--list", tag, cwd=cwd):
            sys.exit(f"{tag} exists but is not the newest tag; refusing to move a tag")
        lock_has_it = f'name = "decomprepair"\nversion = "{version}"' in (Path(cwd) / "uv.lock").read_text()
        if project_version(cwd) != version or not lock_has_it:
            bump_files(version, cwd)
            git("add", "pyproject.toml", "uv.lock", cwd=cwd)
            git(*identity(cwd), "commit", "-q", "-m", f"Release decomprepair {version}: {summary(subjects)}\n\n"
                + "\n".join(f"- {s}" for s in subjects), cwd=cwd)
        git(*identity(cwd), "tag", "-a", tag, "-m", f"decomprepair {version}", cwd=cwd)
        if not push:
            break
        pushed = subprocess.run(["git", "push", "--atomic", remote, "HEAD:refs/heads/main", f"refs/tags/{tag}"],
                                cwd=cwd, capture_output=True, text=True)
        if pushed.returncode == 0:
            break
        # main moved while this ran (a merge landed): start again from the new main, with no local tag or release commit
        print(f"push rejected (attempt {attempt}): {pushed.stderr.strip()[-200:]}")
        git("tag", "-d", tag, cwd=cwd)
        git("fetch", "-q", remote, "main", cwd=cwd)
        git("reset", "-q", "--hard", f"{remote}/main", cwd=cwd)
    else:
        sys.exit("could not push the release after several attempts: main kept moving; the next run retries")
    Path(cwd, notes_path).write_text(notes(version, subjects))
    output(version=version, tag=tag, notes_file=notes_path)
    print(f"released {tag}")
    return version


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    r = sub.add_parser("release")
    r.add_argument("--no-push", action="store_true")
    a = ap.parse_args(argv)
    if a.command == "plan":
        found = plan()
        output(version=found[0] if found else "")
        print(f"would release {found[0]}:\n" + "\n".join(f"- {s}" for s in found[1]) if found else "nothing to release")
    else:
        release(push=not a.no_push)


if __name__ == "__main__":
    main()
