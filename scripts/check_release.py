"""Portable form of the publishing workspace's existing Markdown/file audit.

Check selected Git working files; never inspect ignored local project data.
This is a release-content check, not a secret scanner or functional test.
"""
from pathlib import Path
import json
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT=Path(__file__).resolve().parents[1]


def headings(text):
    used={};result=set()
    for title in re.findall(r'^#{1,6}\s+(.+?)\s*#*\s*$',text,re.M):
        slug=re.sub(r'[^\w\s-]','',title.lower()).strip().replace(' ','-')
        n=used.get(slug,0);used[slug]=n+1
        result.add(slug+('-'+str(n) if n else ''))
    return result


def inspect_files(root,names):
    root=Path(root).resolve();issues=[]
    for name in names:
        path=root/name
        def issue(kind,**detail):issues.append({'file':name,'kind':kind,**detail})
        if path.is_symlink():
            issue('linked-file');continue
        if not path.is_file():
            continue
        if not path.stat().st_size:
            issue('empty-file');continue
        if path.suffix.lower() in ('.db','.sqlite','.sqlite3','.eml','.msg','.pem','.key'):
            issue('private-data-format')
        if path.suffix.lower() not in ('.md','.py','.txt','.json','.yaml','.yml') and path.name not in ('LICENSE','.gitignore'):
            continue
        text=path.read_text(encoding='utf-8')
        if re.search(r'[A-Za-z]:\\Users\\[A-Za-z0-9_. -]+\\',text) or re.search(r'/home/[a-zA-Z0-9_.-]+/',text):
            issue('source-machine-path')
        if path.suffix.lower()!='.md':
            continue
        if not text.strip():issue('blank-document')
        if re.search(r'\{\{[A-Z][A-Z_]+\}\}',text) or '[TODO' in text:issue('unresolved-template')
        prose=re.sub(r'(?ms)^\s*(`{3,}|~{3,}).*?^\s*\1\s*$','',text)
        targets=re.findall(r'\]\(<?([^\s)>]+)>?(?:\s+[^)]*)?\)',prose)
        targets+=re.findall(r'(?m)^\s*\[[^\]]+\]:\s*<?([^\s>]+)>?',prose)
        for target in targets:
            if target.startswith('//') or re.match(r'^(https?|mailto|data|tel):',target,re.I):continue
            part=urlsplit(target)
            dest=(path.parent/unquote(part.path)).resolve() if part.path else path
            if not dest.is_relative_to(root):
                issue('link-outside-repository',target=target);continue
            if not dest.exists():
                issue('missing-local-link',target=target);continue
            if part.fragment and dest.is_file() and dest.suffix.lower()=='.md':
                if unquote(part.fragment) not in headings(dest.read_text(encoding='utf-8')):
                    issue('missing-local-anchor',target=target)
    return issues


def main():
    names=set()
    for command in (['git','ls-files','-z'],['git','ls-files','--others','--exclude-standard','-z']):
        names.update(subprocess.check_output(command,cwd=ROOT).decode('utf-8').split('\0'))
    names.discard('')
    required={'README.md','LICENSE','CHANGELOG.md','CONTRIBUTING.md','SECURITY.md','docs/architecture.md','docs/migration.md','docs/testing.md','examples/demo.py','examples/expected-handoff.md','.github/workflows/checks.yml'}
    issues=[{'file':n,'kind':'missing-release-file'}for n in sorted(required) if n not in names]
    issues+=inspect_files(ROOT,sorted(names))
    print(json.dumps({'files_checked':len(names),'issues':issues,'scope':'Selected working files, local links and anchors; not live HTTP, rights, secrets or behavior'},indent=2))
    return 1 if issues else 0


if __name__=='__main__':raise SystemExit(main())
