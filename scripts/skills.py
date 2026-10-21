"""Discover, validate, test and install named skills from this collection."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ".skill-install.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def hashes(folder):
    result = {}
    for path in sorted(Path(folder).rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Resolve linked files deliberately before installation: {path.name}")
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc" or path.name == RECEIPT:
            continue
        result[path.relative_to(folder).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def catalog():
    return {p.name: p for p in sorted((ROOT / "skills").iterdir()) if p.is_dir() and (p / "SKILL.md").is_file()}


def validate_skill(folder):
    import yaml
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    require(match, f"{folder.name}: missing YAML frontmatter")
    meta = yaml.safe_load(match.group(1))
    require(isinstance(meta, dict), f"{folder.name}: frontmatter must be a mapping")
    name = meta.get("name", "")
    require(isinstance(name, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) and len(name) <= 64,
            f"{folder.name}: invalid skill name")
    require(name == folder.name, f"{folder.name}: name and directory differ")
    require(isinstance(meta.get("description"), str) and meta["description"].strip(), f"{name}: missing description")
    require("[TODO" not in text, f"{name}: unfinished scaffold")
    ui = folder / "agents/openai.yaml"
    if ui.exists():
        data = yaml.safe_load(ui.read_text(encoding="utf-8")) or {}
        prompt = data.get("interface", {}).get("default_prompt", "")
        require(not prompt or "$" + name in prompt, f"{name}: default prompt must reference the skill")
    hashes(folder)
    return meta


def check():
    skills = catalog()
    require(skills, "No skills found")
    for name, folder in skills.items():
        validate_skill(folder)
        for p in folder.rglob("*.md"):
            for target in re.findall(r"\]\(([^)]+)\)", p.read_text(encoding="utf-8")):
                target = target.strip("<>").split("#")[0]
                if not target or "://" in target:
                    continue
                require((p.parent / target).exists(), f"Broken reference in {name}: {target}")
        require((ROOT / "docs/validation" / (name + ".md")).is_file(), f"{name}: add a validation record")
    # A focused source check, not a claim of exhaustive secret detection.
    for p in ROOT.rglob("*"):
        if not p.is_file() or any(part in {".git", ".venv", "__pycache__"} for part in p.relative_to(ROOT).parts):
            continue
        if p.suffix.lower() not in {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".js", ".cjs", ".ts"}:
            continue
        text = p.read_text(encoding="utf-8")
        require(not re.search(r"[A-Za-z]:\\Users\\[A-Za-z0-9_. -]+\\", text), f"Personal Windows path in {p.relative_to(ROOT)}")
        require(not re.search(r"(?:ghp_|gho_)[A-Za-z0-9]{25,}", text), f"Possible GitHub token in {p.relative_to(ROOT)}")
    return {"skills_checked": list(skills), "structure_links_and_focused_source_checks": "passed"}


def tests():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    suites = []
    if (ROOT / "tests").exists():
        suites.append(ROOT / "tests")
    suites += [p / "scripts" for p in catalog().values() if list((p / "scripts").glob("test_*.py"))]
    for suite in suites:
        subprocess.run([sys.executable, str(ROOT / "scripts/run_suite.py"), str(suite)],
                       cwd=ROOT, env=env, check=True)
    return {"test_suites": len(suites), "status": "passed"}


def guarded_file_update(stage, target, backup, old_manifest, new_manifest):
    """Windows fallback: verified external backup, receipt last, rollback on error.

    Called only after a failed directory rename with the old target restored.
    Never adopts local edits or changes ACLs. Only manifest-owned files change.
    """
    require(hashes(target) == old_manifest, 'Target changed before fallback; reconcile local edits')
    require(hashes(stage) == new_manifest, 'Stage changed before fallback')
    require(not backup.exists(), 'Fallback backup already exists')
    shutil.copytree(target, backup)
    require(hashes(backup) == old_manifest, 'Fallback backup mismatch')
    require(hashes(target) == old_manifest, 'Target changed during backup')
    old_receipt = (target / RECEIPT).read_bytes() if (target / RECEIPT).exists() else None
    for rel in set(old_manifest) | set(new_manifest):
        require((target / rel).resolve().is_relative_to(target.resolve()), 'File escapes target')
    try:
        for rel in new_manifest:
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage / rel, dest)
        for rel in set(old_manifest) - set(new_manifest):
            (target / rel).unlink()
        require(hashes(target) == new_manifest, 'Fallback install mismatch')
        shutil.copy2(stage / RECEIPT, target / RECEIPT)
    except Exception:
        # Restore from complete verified backup; retain it for manual recovery.
        for rel in set(new_manifest) - set(old_manifest):
            (target / rel).unlink(missing_ok=True)
        for rel in old_manifest:
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup / rel, dest)
        if old_receipt is None:
            (target / RECEIPT).unlink(missing_ok=True)
        else:
            (target / RECEIPT).write_bytes(old_receipt)
        require(hashes(target) == old_manifest, f'Rollback incomplete; recover from {backup}')
        raise


def install(name, target_root, adopt_receipt=None):
    skills = catalog()
    require(name in skills, "Unknown skill; run list")
    src = skills[name]
    validate_skill(src)
    root = Path(target_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    require(target.resolve().is_relative_to(root) and not target.is_symlink(), "Install target must be a real child directory")
    require(not root.is_relative_to(ROOT), "Install outside the maintained repository")
    manifest = hashes(src)
    if target.exists():
        previous_path = Path(adopt_receipt).resolve() if adopt_receipt else target / RECEIPT
        require(previous_path.is_file(), "Existing install has no receipt; reconcile it or adopt a verified external receipt")
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        require(hashes(target) == previous["files"], "Installed files have local edits; reconcile before updating")
    elif adopt_receipt:
        raise ValueError("Adoption requires an existing installation")
    token = uuid.uuid4().hex
    staging_root = (root.parent / 'skill-install-staging').resolve()
    staging_root.mkdir(parents=True, exist_ok=True)
    stage = staging_root / (name + '-' + token)
    require(stage.resolve().parent == staging_root and not staging_root.is_relative_to(root), "Invalid stage directory")
    stage.mkdir()
    for rel in manifest:
        dest = stage / rel
        require(dest.resolve().is_relative_to(stage), "Skill file escapes stage")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, dest)
    require(hashes(stage) == manifest, "Staged file hash mismatch")
    payload = {"skill": name, "source": str(src), "files": manifest,
               "installed_utc": datetime.now(timezone.utc).isoformat()}
    (stage / RECEIPT).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    backup = None
    if target.exists():
        backup_root = (root.parent / "skill-install-backups").resolve()
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / (name + "-" + token)
        require(backup.resolve().is_relative_to(backup_root), "Backup escapes intended directory")
    mode = 'directory-swap'
    try:
        if backup:
            require(hashes(target) == previous['files'], 'Target changed during staging; reconcile local edits')
            target.rename(backup)
            require(hashes(backup) == previous['files'], 'Target changed before directory swap; old install restored')
        stage.rename(target)
    except PermissionError:
        if backup is None:
            raise
        if not target.exists():
            # The old directory moved, but the stage did not. Restore before fallback.
            try:
                backup.rename(target)
            except OSError:
                shutil.copytree(backup, target)
            require(hashes(target) == previous['files'], 'Could not restore old target')
        file_backup = backup.with_name(backup.name + '-file-update')
        guarded_file_update(stage, target, file_backup, previous['files'], manifest)
        backup = file_backup
        mode = 'guarded-file-update'
        require(stage.resolve().parent == staging_root, 'Cleanup escaped staging root')
        shutil.rmtree(stage)
    except (OSError, ValueError):
        if backup is not None and not target.exists():
            backup.rename(target)
        raise
    require(hashes(target) == manifest, "Installed file hash mismatch")
    return {"skill": name, "installed": str(target), "files": len(manifest),
            "backup": str(backup) if backup else None, "hashes": "match source", 'mode': mode}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest="command", required=True)
    for name in ("list", "check", "test"):
        subs.add_parser(name)
    q = subs.add_parser("install")
    q.add_argument("skill")
    q.add_argument("--target-root", required=True)
    q.add_argument("--adopt-receipt")
    args = p.parse_args()
    try:
        if args.command == "list":
            result = {"skills": list(catalog())}
        elif args.command == "check":
            result = check()
        elif args.command == "test":
            result = tests()
        else:
            result = install(args.skill, args.target_root, args.adopt_receipt)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        p.exit(1, f"Skill collection: {exc}\n")


if __name__ == "__main__":
    main()
