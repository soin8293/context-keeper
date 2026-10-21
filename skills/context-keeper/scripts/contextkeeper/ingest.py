"""Automatic ingestion: turn a project's existing docs into records.

Phase 4 of the plan: nobody types context in by hand. `ingest` scans the
project's markdown docs (AGENTS.md, CONTEXT.md, README.md, docs/...), pulls
out statements that read like decisions, constraints, state, facts or
questions, and stores them as records linked to their source file and section.

It is deterministic pattern matching, not a model: a heading that names a
kind ("## Constraints") classifies every item under it; otherwise the line's
own words do. Quality gates drop commands, code and navigation boilerplate
so ingested records stay readable.

Idempotency and respect for history:
- re-running never duplicates: a (kind, text) pair that exists in *any* status
  is skipped, so a retired or corrected record cannot be resurrected;
- ingest never edits or removes records. When a source line changes, the new
  text is added and the old record is *reported* as possibly stale; superseding
  or retiring stays a deliberate act (rule 1: never rewrite history).

Nothing is dropped silently (the tool's own first rule). A file skipped for
size or a read error is reported under `skipped`; a candidate that closely
restates an existing record is reported under `duplicates` and not added, so
near-duplicates surface for a decision instead of piling up.
"""
from __future__ import annotations

import os
import pathlib
import re
import json
import hashlib
import fnmatch
from collections import Counter

from .store import ContextError, Store

MAX_FILES = 200
MAX_FILE_BYTES = 1024 * 1024  # 1 MB default; see the --max-file-bytes flag
MAX_ITEMS_PER_FILE = 200
NEAR_DUPLICATE_THRESHOLD = 0.8

PRIORITY_FILES = (
    "AGENTS.md",
    "CONTEXT.md",
    "CLAUDE.md",
    "DECISIONS.md",
    "STATUS.md",
    "PLAN.md",
    "ROADMAP.md",
    "NOTES.md",
    "README.md",
)
SCAN_DIRS = ("decisions", "doc", "docs", "planning", "research", "sources")
EXCLUDE_DIRS = {".context-keeper", ".git", "__pycache__", "briefs", "node_modules", "venv", ".venv"}
EXCLUDE_FILES = {"CHANGELOG.md", "LICENSE", "LICENSE.md"}

BEGIN = "<!-- context-keeper:begin -->"
END = "<!-- context-keeper:end -->"
SNAPSHOT_MARK = "<!-- context-keeper:snapshot"

FENCE = re.compile(r"^(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
BULLET = re.compile(r"^(?:[-*+]|\d{1,3}[.)])\s+(.+)$")
CHECKBOX = re.compile(r"^\[( |x|X)\]\s*(.*)$")
TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_SEP = re.compile(r"^:?-{3,}:?$")
PATHLIKE = re.compile(r"^(\.\.?[/\\])?[\w .\-/\\]+\.(md|py|ts|tsx|js|json|toml|yaml|yml|txt)$", re.I)
COMMAND = re.compile(
    r"^(python|py|pip|pip3|npm|npx|pnpm|yarn|bun|node|cd|git|docker|make|pytest|opencode|powershell|curl|sh|bash)\b",
    re.I,
)
NAVVERB = re.compile(r"^(read|see|open|browse|view)\b", re.I)
IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
BOLD = re.compile(r"\*\*(.+?)\*\*")
EMPH = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
CODE = re.compile(r"`([^`]*)`")
WORD = re.compile(r"[a-z0-9]+")

# A heading that names a kind classifies every item under it.
HEADING_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("constraint", re.compile(r"constraint|rule|guard|policy", re.I)),
    ("decision", re.compile(r"decision|verdict|chose|choice", re.I)),
    ("question", re.compile(r"\b(question|open|tbd|unknown)\b", re.I)),
    ("state", re.compile(r"status|state|progress|phase|todo|roadmap", re.I)),
    ("fact", re.compile(r"\bfacts?\b", re.I)),
)
# Otherwise the line's own words decide.
LINE_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("constraint", re.compile(r"^(never|always|do not|don'?t|must not|mustn'?t|shall not)\b|\b(never|must|forbidden|prohibited)\b", re.I)),
    ("decision", re.compile(r"^(we|the team|the project)\s+(use|used|chose|choosing|adopt|adopted|decided|prefer)s?\b|^uses\b|\b(decision|verdict)\b", re.I)),
    ("question", re.compile(r"\?|\b(tbd|to be determined|open question)\b", re.I)),
    ("state", re.compile(r"^(in progress|on hold|blocked|paused|done|wip)\b", re.I)),
    ("fact", re.compile(r"^(fact|note that|note:)\b", re.I)),
)


def _clean(s: str) -> str:
    s = IMAGE.sub("", s)
    s = LINK.sub(r"\1", s)
    s = BOLD.sub(r"\1", s)
    s = EMPH.sub(r"\1", s)
    s = CODE.sub(r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def _slug(heading: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", heading.lower())).strip("-")


def _classify(text: str, heading: str) -> str:
    for kind, pat in HEADING_KINDS:
        if pat.search(heading):
            return kind
    for kind, pat in LINE_KINDS:
        if pat.search(text):
            return kind
    return "note"


def _tokenset(text: str) -> frozenset[str]:
    return frozenset(WORD.findall(text.lower()))


def _similarity(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def strip_marked(text: str) -> str:
    """Remove Context Keeper's own marked blocks and snapshot comments."""
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if BEGIN in line:
            inside = True
            continue
        if END in line:
            inside = False
            continue
        if not inside and SNAPSHOT_MARK not in line:
            out.append(line)
    return "\n".join(out)


def extract_items(text: str, max_items: int | None = MAX_ITEMS_PER_FILE) -> list[dict]:
    """Extract candidate records from markdown text. Deterministic, no model."""
    items: list[dict] = []
    heading = ""
    fence_marker = ""
    in_table = False
    current: dict | None = None  # open bullet, for joining wrapped lines
    paragraph: dict | None = None

    lines = text.splitlines()
    for index, raw in enumerate(lines):
        line = raw.rstrip()

        fence = FENCE.match(line.lstrip())
        if fence:
            marker, suffix = fence.groups()
            if not fence_marker:
                fence_marker = marker
            elif marker[0] == fence_marker[0] and len(marker) >= len(fence_marker) and not suffix.strip():
                fence_marker = ""
            in_table = False
            current = None
            paragraph = None
            continue
        if fence_marker:
            continue

        m = HEADING.match(line)
        if m:
            heading = m.group(2).strip()
            in_table = False
            current = None
            paragraph = None
            continue

        m = TABLE_ROW.match(line)
        if m:
            current = None
            paragraph = None
            cells = [_clean(c) for c in m.group(1).split("|")]
            if cells and all(TABLE_SEP.fullmatch(c) for c in cells):
                continue  # separator row
            # A following delimiter identifies a new header, including another
            # table immediately after this one. Blank lines alone do not turn a
            # continuing data row into a header.
            following = TABLE_ROW.match(lines[index + 1]) if index + 1 < len(lines) else None
            if following:
                delimiter = [c.strip() for c in following.group(1).split("|")]
                if len(delimiter) == len(cells) and all(TABLE_SEP.fullmatch(c) for c in delimiter):
                    in_table = True
                    continue
            if not in_table:
                in_table = True
                continue  # header row: labels, not content
            if any(PATHLIKE.match(c) for c in cells if c):
                continue  # navigation table row
            text2 = " — ".join(c for c in cells if c)
            if len(text2) >= 10 and re.search(r"[A-Za-z]{3}", text2):
                items.append({"kind": _classify(text2, heading), "text": text2, "anchor": heading})
            continue

        if not line.strip():
            current = None
            paragraph = None
            continue

        in_table = False

        m = BULLET.match(line.lstrip())
        if m:
            paragraph = None
            content = m.group(1)
            is_todo = False
            cm = CHECKBOX.match(content)
            if cm:
                is_todo = cm.group(1) == " "
                content = cm.group(2)
            text2 = _clean(content)
            if len(text2) < 10 or not re.search(r"[A-Za-z]{3}", text2):
                current = None
                continue
            if COMMAND.match(text2) or NAVVERB.match(text2):
                current = None
                continue
            kind = "state" if is_todo else _classify(text2, heading)
            item = {"kind": kind, "text": text2, "anchor": heading}
            items.append(item)
            current = item
            continue

        # An indented line continues the bullet above it (wrapped markdown).
        if current is not None and line[:1] in (" ", "\t"):
            cont = _clean(line)
            if cont:
                current["text"] = f"{current['text']} {cont}".strip()
            continue

        # Conservative prose capture only under an explicit governing heading.
        # Ordinary narrative, quotes, HTML and commands remain outside capture.
        current = None
        if any(p.search(heading) for k, p in HEADING_KINDS if k in ('constraint', 'decision', 'state')):
            text2 = _clean(line)
            if (len(text2) >= 10 and re.search(r'[A-Za-z]{3}', text2)
                    and not line.lstrip().startswith(('>', '<', '!', '|'))
                    and not COMMAND.match(text2) and not NAVVERB.match(text2)):
                if paragraph is not None:
                    paragraph['text'] += ' ' + text2
                else:
                    paragraph = {'kind': _classify(text2, heading), 'text': text2, 'anchor': heading}
                    items.append(paragraph)
            else:
                paragraph = None

    return items if max_items is None else items[:max(0, max_items)]


def source_config(root):
    """Project-owned selection; roots are never inferred from record references."""
    path = root / '.context-keeper' / 'sources.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContextError(f'Invalid source configuration: {exc}') from exc
    if not isinstance(data, dict) or set(data) - {'active', 'include', 'exclude', 'max_files', 'max_items', 'max_file_bytes'}:
        raise ContextError('sources.json supports active/include/exclude and max_files/max_items/max_file_bytes only.')
    for key in ('active', 'include', 'exclude'):
        if key in data and (not isinstance(data[key], list) or any(not isinstance(p, str) or pathlib.Path(p).is_absolute() or '..' in pathlib.PurePath(p).parts for p in data[key])):
            raise ContextError(f'{key} must contain project-relative paths/globs, without parent traversal.')
    for key in ('max_files', 'max_items', 'max_file_bytes'):
        if key in data and (type(data[key]) is not int or data[key] < 1):
            raise ContextError(f'{key} must be a positive integer.')
    return data


def discover_files(
    root: pathlib.Path, max_file_bytes: int = MAX_FILE_BYTES, *, config=None, max_files=None
) -> tuple[list[tuple[str, pathlib.Path]], list[dict]]:
    """Deterministic, bounded list of (relative path, absolute path) to scan.

    Returns (found, skipped). `skipped` records every candidate not returned,
    with a reason, so a file is never dropped silently.
    """
    found: list[tuple[str, pathlib.Path]] = []
    skipped: list[dict] = []
    seen: set[str] = set()

    excluded = {n.upper() for n in EXCLUDE_FILES}
    root_resolved = root.resolve()
    config = source_config(root) if config is None else config
    max_files = max_files if max_files is not None else config.get('max_files', MAX_FILES)

    def consider(path: pathlib.Path) -> None:
        # Resolve to the real on-disk path so a file is reported by its true name
        # and not seen twice under two casings (NOTES.md vs notes.md on Windows).
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = os.path.normcase(str(resolved))
        if not resolved.is_relative_to(root_resolved):
            skipped.append({'file': path.relative_to(root).as_posix(), 'reason': 'outside_project'})
            return
        if key in seen or resolved.name.upper() in excluded:
            return
        seen.add(key)
        try:
            rel = resolved.relative_to(root_resolved).as_posix()
        except ValueError:
            rel = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, pattern) for pattern in config.get('exclude', [])):
            skipped.append({'file': rel, 'reason': 'configured_exclusion'})
            return
        if len(found) >= max_files:
            skipped.append({"file": rel, "reason": "file_limit"})
            return
        try:
            size = path.stat().st_size
        except OSError:
            skipped.append({"file": rel, "reason": "unreadable"})
            return
        if size > max_file_bytes:
            skipped.append({"file": rel, "reason": "too_large", "size": size})
            return
        found.append((rel, path))

    for pattern in config.get('active', []) + config.get('include', []):
        matches = sorted(root.glob(pattern))
        if not matches:
            skipped.append({'file': pattern, 'reason': 'configured_source_missing'})
        for path in matches:
            if path.is_file():
                consider(path)
    for name in PRIORITY_FILES:
        p = root / name
        if p.is_file():
            consider(p)

    for p in sorted(root.glob("*.md")):
        if p.is_file():
            consider(p)

    for d in SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.md")):
            if p.is_file() and not any(part in EXCLUDE_DIRS for part in p.relative_to(root).parts):
                consider(p)

    return found, skipped


def ingest(
    store: Store,
    root: pathlib.Path,
    scope: str = "",
    dry_run: bool = False,
    max_file_bytes: int | None = None,
    near_duplicate_threshold: float = NEAR_DUPLICATE_THRESHOLD,
    max_items: int | None = None,
    max_files: int | None = None,
) -> dict:
    """Scan the project's docs and turn them into source-linked records."""
    root = pathlib.Path(root).resolve()
    if not root.is_dir():
        raise ContextError(f"not a directory: {root}")

    config = source_config(root)
    max_file_bytes = max_file_bytes if max_file_bytes is not None else config.get('max_file_bytes', MAX_FILE_BYTES)
    max_items = max_items if max_items is not None else config.get('max_items', MAX_ITEMS_PER_FILE)
    if max_items < 1 or max_file_bytes < 1 or (max_files is not None and max_files < 1):
        raise ContextError('Ingestion limits must be positive.')
    files, skipped = discover_files(root, max_file_bytes, config=config, max_files=max_files)
    origin = str(root)

    # (kind, text) in ANY status: skip, so retired/corrected records stay dead.
    existing = {
        (r['kind'], r['text'], r['ref'])
        for r in store.conn.execute('SELECT r.kind,r.text,s.ref FROM record r JOIN source s ON r.source_id=s.id WHERE r.scope=? AND s.origin=?', (scope, origin))
    }

    # Current records grouped by kind (for near-duplicate checks) and by checked
    # source file (for the staleness report).
    by_kind: dict[str, list[tuple[int, frozenset[str], str]]] = {}
    current_by_file: dict[str, list[dict]] = {}
    for r in store.conn.execute(
        "SELECT r.id AS id, r.kind AS kind, r.text AS text, s.ref AS ref, "
        "s.checked AS checked, s.origin FROM record r LEFT JOIN source s ON r.source_id = s.id "
        "WHERE r.status = 'current' AND r.scope=? AND (s.origin=? OR s.origin IS NULL)", (scope, origin)
    ):
        by_kind.setdefault(r["kind"], []).append((r["id"], _tokenset(r["text"]), r["text"]))
        if r["ref"] and r["checked"] and r['origin'] == origin:
            current_by_file.setdefault(r["ref"].split("#")[0], []).append(
                {"id": r["id"], "kind": r["kind"], "text": r["text"], "ref": r["ref"]}
            )

    per_file: list[dict] = []
    added_kinds: Counter[str] = Counter()
    duplicates: list[dict] = []
    item_texts_by_file: dict[str, set[str]] = {}
    source_changes = []
    unresolved = []
    unknown = [dict(r) for r in store.conn.execute('SELECT DISTINCT s.id,s.ref FROM source s JOIN record r ON r.source_id=s.id WHERE s.checked=1 AND s.origin IS NULL AND r.status=\'current\' AND r.scope=?', (scope,))]

    for rel, path in files:
        try:
            raw = path.read_bytes()
            text = raw.decode('utf-8-sig')
        except (OSError, UnicodeError):
            skipped.append({"file": rel, "reason": "unreadable_or_invalid_utf8"})
            continue
        if SNAPSHOT_MARK in text or '<!-- context-keeper:brief' in text:
            skipped.append({'file': rel, 'reason': 'generated_brief'})
            continue
        digest = hashlib.sha256(raw).hexdigest()
        scan = store.conn.execute('SELECT * FROM source_scan WHERE origin=? AND ref=? AND scope=?', (origin, rel, scope)).fetchone()
        changed = bool(scan and scan['digest'] != digest)
        if changed:
            source_changes.append({'file': rel, 'reason': 'file_bytes_changed'})
        candidates = extract_items(strip_marked(text), max_items=None)
        items = candidates[:max_items]
        if len(candidates) > len(items):
            skipped.append({'file': rel, 'reason': 'item_limit', 'omitted_items': len(candidates)-len(items)})
        item_texts_by_file[rel] = {i["text"] for i in items}

        n_added = n_existing = n_dup = 0
        for it in items:
            ref = f"{rel}#{_slug(it['anchor'])}" if it["anchor"] else rel
            key = (it["kind"], it["text"], ref)
            if key in existing:
                n_existing += 1
                continue
            # Near-duplicate of an existing current record? report, don't add.
            toks = _tokenset(it["text"])
            best = None
            for rid, rtoks, rtext in by_kind.get(it["kind"], []):
                sim = _similarity(toks, rtoks)
                if sim >= near_duplicate_threshold and (best is None or sim > best[1]):
                    best = (rid, sim, rtext)
            if best is not None:
                duplicates.append(
                    {
                        "file": rel,
                        "kind": it["kind"],
                        "text": it["text"],
                        "of_id": best[0],
                        "similarity": round(best[1], 2),
                        "of_text": best[2],
                    }
                )
                n_dup += 1
                existing.add(key)
                continue
            rid = -1  # unknown until written; -1 means "added earlier in this run"
            if not dry_run:
                ref = f"{rel}#{_slug(it['anchor'])}" if it["anchor"] else rel
                sid = store.find_or_add_source(ref, note="auto-ingested", checked=True, origin=origin)
                rid = store.add(it["kind"], it["text"], scope=scope, source_id=sid)
            existing.add(key)  # dedupe within this run too, so dry-run counts match
            by_kind.setdefault(it["kind"], []).append((rid, toks, it["text"]))
            n_added += 1
            added_kinds[it["kind"]] += 1

        per_file.append(
            {"file": rel, "items": len(items), "added": n_added, "existing": n_existing, "duplicates": n_dup}
        )
        # A raw change that adds no captured passage needs an explicit writer
        # review; an ingest success cannot silently bless uncaptured prose.
        pending = bool((scan and scan['unresolved']) or (changed and not n_added))
        if pending:
            unresolved.append({'file': rel, 'reason': 'source_change_requires_review', 'digest': digest})
        if not dry_run:
            store.conn.execute('INSERT OR REPLACE INTO source_scan VALUES (?,?,?,?,?)', (origin, rel, scope, digest, int(pending)))
            store.conn.commit()

    totals = {
        "added": sum(f["added"] for f in per_file),
        "existing": sum(f["existing"] for f in per_file),
        "duplicates": sum(f["duplicates"] for f in per_file),
        "skipped": len(skipped),
    }

    # Records whose source file was scanned but whose exact text is gone.
    stale: list[dict] = []
    for rel in sorted(item_texts_by_file):
        for rec in current_by_file.get(rel, []):
            if rec["text"] not in item_texts_by_file[rel]:
                stale.append(rec)
    for rel, records in current_by_file.items():
        source_path = (root / rel).resolve()
        if not source_path.is_relative_to(root) or not source_path.is_file():
            stale.extend({**rec, 'reason': 'missing_or_outside_project_source'} for rec in records)
        elif rel not in item_texts_by_file:
            stale.extend({**rec, 'reason': 'record_source_not_scanned_in_active_selection'} for rec in records)

    if not dry_run:
        store.log_event(
            "ingest",
            f"scanned {len(files)} files, added {totals['added']}, existing {totals['existing']}, "
            f"duplicates {totals['duplicates']}, stale {len(stale)}, skipped {totals['skipped']}",
        )

    return {
        "root": str(root),
        "files": per_file,
        "totals": totals,
        "added_kinds": dict(added_kinds),
        "stale": stale,
        "skipped": skipped,
        "duplicates": duplicates,
        'source_changes': source_changes,
        'unresolved': unresolved,
        'unknown_origins': unknown,
    }


def acknowledge_source(store, root, ref, scope, reason):
    """Explicit writer attestation after inspecting a raw-only source change."""
    root = pathlib.Path(root).resolve()
    path = (root / ref).resolve()
    if not reason.strip() or not path.is_relative_to(root) or not path.is_file():
        raise ContextError('Acknowledgment needs an in-root source file and a review reason.')
    row = store.conn.execute('SELECT digest FROM source_scan WHERE origin=? AND ref=? AND scope=?', (str(root), ref, scope)).fetchone()
    if not row or row['digest'] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise ContextError('Run authorized ingest, then inspect this exact source revision before acknowledging.')
    store.conn.execute('UPDATE source_scan SET unresolved=0 WHERE origin=? AND ref=? AND scope=?', (str(root), ref, scope))
    store.log_event('source-review', f'{root}/{ref} ({scope}): {reason}')
