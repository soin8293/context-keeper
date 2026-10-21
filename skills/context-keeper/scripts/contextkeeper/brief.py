"""Whole-record task packets, linked amendments and compact scoped freshness."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .store import ContextError, Store, now
from .freshness import compact_snapshot, digest, source_issues

RESERVED_KINDS = ('constraint', 'decision')
STOPWORDS = set('the and for with that this from into about what when where which should would could have has had are was were will can not but you your our their them its how why who all any use using make made get got need want task work'.split())


def tokens(text):
    return [w for w in re.findall(r'[a-z0-9]+', (text or '').lower()) if len(w) >= 3 and w not in STOPWORDS]


def _score(text, task_tokens):
    return len(set(tokens(text)) & task_tokens)


def build_brief(store: Store, task: str, scope=None, budget_chars=8000,
                include_superseded=False, reserved_share=.5,
                omitted_summary_threshold=25, full_omitted=False,
                output_chars=16000, required=(), global_policy='all'):
    if budget_chars < 0 or output_chars < 500 or not 0 <= reserved_share <= 1:
        raise ContextError('Use a nonnegative record budget, output cap >=500, and reserved share between 0 and 1.')
    if global_policy not in ('all', 'relevant', 'exclude'):
        raise ContextError('Unknown global policy.')
    include_globals = global_policy != 'exclude'
    required = list(dict.fromkeys(required))
    base = {r['id']: r for r in store.current(scope, include_globals=include_globals)}
    scope_ids = set(base)
    task_tokens = set(tokens(task))
    policy_excluded = []
    if global_policy == 'relevant' and scope is not None:
        for rid, row in list(base.items()):
            if not row['scope'] and not row['mandatory'] and not _score(row['text'], task_tokens):
                policy_excluded.append(rid)
                del base[rid]
    for rid in required:
        base[rid] = store.get(rid)
    candidates = store.linked(base)
    policy_excluded = [rid for rid in policy_excluded if rid not in candidates]
    groups, seen = [], set()
    for rid in candidates:
        if rid in seen:
            continue
        group = list(store.linked({rid: candidates[rid]}).values())
        seen.update(r['id'] for r in group)
        groups.append(group)
    def forced(group):
        return len(group) > 1 or any(r['mandatory'] or r['id'] in required for r in group)
    def rank(group):
        return (-int(forced(group)), -max(_score(r['text'], task_tokens) for r in group),
                -int(any(r['scope'] for r in group)),
                -int(any(r['kind'] in RESERVED_KINDS for r in group)), min(r['id'] for r in group))
    groups.sort(key=rank)
    chosen, omitted, deferred = [], [], []
    used = 0
    def add(group):
        nonlocal used
        size = sum(len(r['text']) for r in group)
        if used + size <= budget_chars:
            chosen.append(group)
            used += size
        else:
            omitted.extend({'id': r['id'], 'kind': r['kind'], 'size': len(r['text']), 'reason': 'char_budget_exceeded',
                            'required': forced(group)} for r in group)
    for group in groups:
        size = sum(len(r['text']) for r in group)
        eligible = any(r['kind'] in RESERVED_KINDS and
                       (scope is None or r['scope']) for r in group)
        if forced(group) or (eligible and used + size <= int(budget_chars * reserved_share)):
            add(group)
        else:
            deferred.append(group)
    for group in sorted(deferred, key=rank):
        add(group)
    snap = compact_snapshot(store, scope, include_globals, required)
    issues = source_issues(store, scope, include_globals, required)
    if any(r['status'] != 'current' for r in candidates.values()):
        issues.append({'reason': 'noncurrent_required_or_amendment_endpoint'})
    scope_excluded = len({r['id'] for r in store.current()} - scope_ids - set(candidates))

    def render():
        included = [r for group in chosen for r in group]
        incomplete = bool(issues or any(o['required'] for o in omitted))
        lines = ['# Context brief', '<!-- context-keeper:brief v2 -->', '',
                 f'- **Task:** {task.strip()}', f'- **Scope:** {scope if scope is not None else "(all)"}; globals: {global_policy}; mandatory records always apply',
                 f'- **Generated:** {now()}',
                 f'- **Status:** {"INCOMPLETE — resolve required context/source issues" if incomplete else "Review omissions and governing sources before relying on this packet"}',
                 f'- **Included:** {len(included)} of {len(candidates)} candidates', '']
        for title, kind in [('Constraints','constraint'), ('Decisions','decision'), ('State','state'), ('Facts','fact'), ('Questions','question'), ('Other','note')]:
            rows = [r for r in included if r['kind'] == kind]
            if not rows:
                continue
            lines.append('## ' + title)
            for r in rows:
                source = store.conn.execute('SELECT * FROM source WHERE id=?', (r['source_id'],)).fetchone()
                citation = ''
                if source:
                    citation = f" — source #{source['id']}: {source['ref']}"
                    if source['origin']:
                        rel, _, anchor = source['ref'].partition('#')
                        path = (Path(source['origin']) / rel).resolve()
                        if path.is_relative_to(Path(source['origin']).resolve()):
                            citation += ' <' + path.as_uri() + ('#' + anchor if anchor else '') + '>'
                        else:
                            citation += ' (outside declared origin; unresolved)'
                    elif source['checked']:
                        citation += ' (origin unresolved)'
                lines.append(f"- **[{r['kind'][0].upper()}{r['id']}]** {r['text']} (scope: {r['scope'] or 'global'}; {r['status']}){citation}")
                for link in store.amendments():
                    if link['base_id'] == r['id']:
                        lines.append(f"  - Partly amended by #{link['amendment_id']}: {link['reason']}")
                if include_superseded and r['supersedes']:
                    old = store.get(r['supersedes'])
                    lines.append(f"  - Superseded (history only) #{old['id']}: {old['text']}")
            lines.append('')
        if omitted:
            if len(omitted) > omitted_summary_threshold and not full_omitted:
                lines.append(f'## Omitted ({len(omitted)} records did not fit)')
                lines.extend(f'- {count} × {kind}' for kind, count in sorted(Counter(o['kind'] for o in omitted).items()))
                lines.append('- Use --full-omitted or search for the detailed list.')
            else:
                lines.append('## Omitted (did not fit)')
                lines.extend(f"- #{o['id']} ({o['kind']}, {o['size']} chars) — {o['reason']}" + ('; REQUIRED GROUP' if o['required'] else '') for o in omitted)
            lines.append('')
        if issues:
            lines += [f'## Source/context issues ({len(issues)})', '- Run reconcile --json for exact sources and actions; this packet is incomplete.', '']
        lines += ['## Coverage', f'- candidates: {len(candidates)}; included: {len(included)}; omitted: {len(omitted)}; record text: {used}/{budget_chars} chars',
                  f'- excluded by scope/global policy: {max(0, scope_excluded)}/{len(policy_excluded)}; whole-output cap: {output_chars} chars',
                  '- Selection and freshness do not establish semantic truth or live agent availability.', '',
                  '<!-- context-keeper:snapshot ' + json.dumps(snap, sort_keys=True) + ' -->']
        return '\n'.join(lines), included, incomplete
    chosen.sort(key=rank)
    text, included, incomplete = render()
    while len(text) > output_chars and chosen:
        group = chosen.pop()
        used -= sum(len(r['text']) for r in group)
        omitted.extend({'id': r['id'], 'kind': r['kind'], 'size': len(r['text']), 'reason': 'output_budget_exceeded', 'required': forced(group)} for r in group)
        text, included, incomplete = render()
    if len(text) > output_chars:
        raise ContextError(f'Complete metadata/omission report needs {len(text)} characters; raise --output-budget or narrow scopes/omit --full-omitted. No truncated packet produced.')
    return {'text': text, 'token': digest(snap), 'included': [r['id'] for r in included], 'omitted': omitted,
            'issues': issues, 'incomplete': incomplete,
            'coverage': {'candidates': len(candidates), 'included': len(included), 'omitted': len(omitted),
                         'reserved_included': sum(r['kind'] in RESERVED_KINDS for r in included),
                         'reserved_omitted': sum(o['kind'] in RESERVED_KINDS for o in omitted),
                         'used_chars': used, 'budget_chars': budget_chars, 'output_chars': len(text), 'output_budget': output_chars,
                         'scope_excluded': max(0, scope_excluded), 'policy_excluded': len(policy_excluded)}}


def extract_snapshot(brief_text):
    match = re.search(r'<!-- context-keeper:snapshot (\{.*?\}) -->', brief_text)
    if not match:
        return None
    try:
        value = json.loads(match.group(1))
        if not isinstance(value, dict):
            return None
        if 'version' in value:
            if value.get('version') != 2 or set(value) != {'version', 'scope', 'include_globals', 'required', 'records', 'sources'}:
                return None
            if value['scope'] is not None and not (isinstance(value['scope'], str) or isinstance(value['scope'], list) and all(isinstance(s, str) for s in value['scope'])):
                return None
            if type(value['include_globals']) is not bool or not isinstance(value['required'], list) or any(type(i) is not int for i in value['required']):
                return None
            if any(not isinstance(value[k], str) or not re.fullmatch('[0-9a-f]{64}', value[k]) for k in ('records', 'sources')):
                return None
        elif any(not k.isdigit() or not isinstance(v, str) for k, v in value.items()):
            return None
        return value
    except (ValueError, TypeError):
        return None


def diff_snapshot(old, new):
    if old.get('version') == 2:
        fresh = old == new if new.get('version') == 2 else old['records'] == digest(new)
        return {'fresh': fresh, 'added': [], 'changed': [], 'removed_from_current': [], 'compact': True}
    return {'added': sorted(int(k) for k in new if k not in old),
            'changed': sorted(int(k) for k in old if k in new and old[k] != new[k]),
            'removed_from_current': sorted(int(k) for k in old if k not in new), 'fresh': old == new}
