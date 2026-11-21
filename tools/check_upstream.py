#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""Check whether cisco-mibs has moved on from the commit in UPSTREAM, and what that changes.

Usage:
    python3 tools/check_upstream.py [--report-dir DIR] [--keep DIR] [--upstream FILE]

1. Asks GitHub (git ls-remote) for the head of cisco-mibs main. If it is the
   commit in UPSTREAM, says so and exits 0.
2. Otherwise clones cisco-mibs (file contents only for the two commits), lists
   the commits and changed files in between, and runs fix_cisco_mibs.py on both
   commits at the same time, with Net-SNMP's and LibreNMS's mibs/ at the
   commits in UPSTREAM. Then compares the two outputs.
3. Prints a Markdown report. With --report-dir, also writes it there as
   title.txt and body.md (used by .github/workflows/upstream.yml to open an issue).

Exits 1 if cisco-mibs has new commits, 0 if not, 2 on errors.
Needs git and network access; nothing is pushed or published.
"""
import argparse
import filecmp
import json
import os
import subprocess
import sys
import tempfile

TOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPSTREAM = os.path.join(TOP, 'UPSTREAM')
BRANCH = 'main'
# Monthly CANA releases touch only these: new product OIDs, low risk
CANA_FILES = {'v2/CISCO-PRODUCTS-MIB.my', 'v2/CISCO-ENTITY-VENDORTYPE-OID-MIB.my'}
# Written by fix_cisco_mibs.py on every run; their content is summarized by the counts
LOG_FILES = {'CHANGES.md', 'CHANGES.ja.md', 'changes.json'}
MAX_LIST = 50  # lines per list in the report


class Error(Exception):
    pass


def read_upstream(path=UPSTREAM):
    """{name: (commit, url)} from the UPSTREAM file."""
    pins = {}
    with open(path, encoding='utf-8') as fh:
        for n, line in enumerate(fh, 1):
            line = line.split('#', 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 3 or len(parts[1]) != 40:
                raise Error('%s:%d: expected "name commit url"' % (path, n))
            pins[parts[0]] = (parts[1], parts[2])
    for name in ('cisco-mibs', 'net-snmp', 'librenms'):
        if name not in pins:
            raise Error('%s: no line for %s' % (path, name))
    return pins


def is_mib_path(path):
    """Whether fix_cisco_mibs.py reads this cisco-mibs path."""
    return path.startswith(('v1/', 'v2/'))


def classify(paths):
    """What kind of change a list of changed cisco-mibs paths is.

    'none': no MIB changed (only files outside v1/ and v2/),
    'cana': only the files that the monthly CANA releases touch,
    'mibs': anything else.
    """
    mibs = {p for p in paths if is_mib_path(p)}
    if not mibs:
        return 'none'
    return 'cana' if mibs <= CANA_FILES else 'mibs'


def git(*args, cwd=None):
    proc = subprocess.run(['git', '-c', 'advice.detachedHead=false'] + list(args), cwd=cwd,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, encoding='utf-8', errors='replace')
    if proc.returncode:
        raise Error('git %s failed:\n%s' % (' '.join(args), proc.stderr.strip()))
    return proc.stdout


def remote_head(url, branch=BRANCH):
    out = git('ls-remote', url, 'refs/heads/' + branch).split()
    if not out:
        raise Error('%s has no branch %s' % (url, branch))
    return out[0]


def clone_both(url, old, new, dest):
    """Clone url into dest/repo without file contents, and check out old and new
    as worktrees dest/old and dest/new."""
    repo = os.path.join(dest, 'repo')
    git('clone', '--quiet', '--filter=blob:none', '--no-checkout', url, repo)
    for rev in (old, new):
        git('cat-file', '-e', rev + '^{commit}', cwd=repo)
    for name, rev in (('old', old), ('new', new)):
        git('worktree', 'add', '--quiet', '--detach', os.path.join(dest, name), rev, cwd=repo)
    return repo


def fetch_mibs(url, commit, dest):
    """Check out only the files directly in mibs/ of url at commit into dest."""
    os.makedirs(dest)
    git('init', '--quiet', cwd=dest)
    git('config', 'core.sparseCheckout', 'true', cwd=dest)
    with open(os.path.join(dest, '.git', 'info', 'sparse-checkout'), 'w') as fh:
        fh.write('/mibs/*\n!/mibs/*/\n')
    git('fetch', '--quiet', '--depth', '1', '--filter=blob:none', url, commit, cwd=dest)
    git('checkout', '--quiet', 'FETCH_HEAD', cwd=dest)
    return os.path.join(dest, 'mibs')


def start_fix(repo, out, extra):
    return subprocess.Popen([sys.executable, os.path.join(TOP, 'fix_cisco_mibs.py'), '-q',
                             repo, out] + extra,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True, encoding='utf-8', errors='replace')


def finish_fix(proc, label):
    """(exit status, counts, warning lines) of a fix_cisco_mibs.py run."""
    out, err = proc.communicate()
    if proc.returncode not in (0, 1):  # 1: fixes that did not apply, output still written
        raise Error('fix_cisco_mibs.py (%s) failed:\n%s' % (label, err.strip()))
    # leave out the line naming CHANGES.md: its path differs every run
    warnings = [line for line in err.splitlines() if line.startswith(('warning:', 'error:'))
                and not line.startswith('warning: see ')]
    return proc.returncode, json.loads(out), warnings


def files_under(d):
    return sorted(os.path.relpath(os.path.join(root, f), d).replace(os.sep, '/')
                  for root, _, files in os.walk(d) for f in files)


def compare_outputs(old, new):
    """(added, removed, changed) files of the output, without the change logs."""
    a = set(files_under(old)) - LOG_FILES
    b = set(files_under(new)) - LOG_FILES
    common = sorted(a & b)
    _, changed, errors = filecmp.cmpfiles(old, new, common, shallow=False)
    return sorted(b - a), sorted(a - b), sorted(changed + errors)


def text_block(lines):
    """A fenced block, so that text from upstream can't mention people or add links."""
    lines = list(lines)
    if len(lines) > MAX_LIST:
        lines = lines[:MAX_LIST] + ['... %d more' % (len(lines) - MAX_LIST)]
    body = '\n'.join(line.replace('```', "'''") for line in lines)
    return '```text\n%s\n```\n' % body


TAGS = {'none': 'no MIB changes', 'cana': 'CANA only'}


def make_title(new, kind, patch_missed):
    tags = [TAGS[kind]] if kind in TAGS else []
    if patch_missed:
        tags.append('fixes not applied')
    return 'cisco-mibs updated to %s%s' % (new[:7], ''.join(' [%s]' % t for t in tags))


def make_report(info):
    """(title, body) of the report. info is a dict filled in by check()."""
    old, new = info['old'], info['new']
    kind = info['kind']
    new_rc, new_counts, new_warn = info['fix_new']
    old_rc, old_counts, old_warn = info['fix_old']
    patch_missed = new_rc == 1
    b = []
    b.append('cisco-mibs `%s` is at `%s` (%s), %d commit(s) after `%s` (%s), '
             'the commit in `UPSTREAM`.\n'
             % (BRANCH, new[:7], info['new_date'], len(info['commits']), old[:7],
                info['old_date']))
    b.append('Compare: %s/compare/%s...%s\n' % (info['url'], old[:7], new[:7]))
    b.append({
        'none': '**No MIB changed** (only files outside `v1/` and `v2/`).\n',
        'cana': '**CANA only**: only %s changed (new product OIDs).\n'
                % ' / '.join('`%s`' % f.split('/')[1] for f in sorted(CANA_FILES)),
        'mibs': '**MIBs changed** beyond the monthly CANA files.\n',
    }[kind])
    b.append('### Commits\n')
    b.append(text_block(info['commits']))
    mib_lines = [line for line in info['changed'] if is_mib_path(line.split('\t', 1)[1])]
    others = {}
    for line in info['changed']:
        path = line.split('\t', 1)[1]
        if not is_mib_path(path):
            top = path.split('/', 1)[0] + ('/' if '/' in path else '')
            others[top] = others.get(top, 0) + 1
    b.append('### Changed files in `v1/` and `v2/`\n')
    b.append(text_block(mib_lines) if mib_lines else '(none)\n')
    if others:
        b.append('Elsewhere (not read by fix_cisco_mibs.py): %s.\n'
                 % ', '.join('`%s` %d' % kv for kv in sorted(others.items())))
    b.append('### fix_cisco_mibs.py\n')
    b.append('| | `%s` | `%s` |\n|---|---|---|' % (old[:7], new[:7]))
    b.append('| exit status | %d | %d |' % (old_rc, new_rc))
    for k in sorted(set(old_counts) | set(new_counts)):
        o, n = old_counts.get(k, 0), new_counts.get(k, 0)
        if o != n:
            b.append('| %s | %d | %d |' % (k, o, n))
    b.append('')
    if patch_missed:
        b.append('Some targeted fixes no longer apply: the patches need updating.\n')
    gone = [w for w in old_warn if w not in new_warn]
    came = [w for w in new_warn if w not in old_warn]
    if gone or came:
        b.append('Warnings that changed (`-` only at `%s`, `+` only at `%s`):\n'
                 % (old[:7], new[:7]))
        b.append(text_block(['- ' + w for w in gone] + ['+ ' + w for w in came]))
    else:
        b.append('Warnings: same as at `%s`.\n' % old[:7])
    added, removed, changed = info['output']
    b.append('### Output\n')
    if added or removed or changed:
        b.append(text_block(['added:   ' + f for f in added] + ['removed: ' + f for f in removed]
                            + ['changed: ' + f for f in changed]))
    else:
        b.append('No output file differs (change logs aside).\n')
    b.append('### What to do\n')
    b.append('Follow "Following upstream" in the README: check the changes, update '
             '`UPSTREAM` and the numbers in the README, and close this issue. '
             'Until `UPSTREAM` changes, later runs add a comment here when `%s` moves again.\n'
             % BRANCH)
    return make_title(new, kind, patch_missed), '\n'.join(b)


def check(work, log, upstream=UPSTREAM):
    pins = read_upstream(upstream)
    old, url = pins['cisco-mibs']
    log('asking %s for %s...' % (url, BRANCH))
    new = remote_head(url)
    if new == old:
        return None
    log('%s moved: %s -> %s; cloning...' % (BRANCH, old[:7], new[:7]))
    repo = clone_both(url, old, new, os.path.join(work, 'cisco-mibs'))
    info = {'old': old, 'new': new, 'url': url}
    info['old_date'], info['new_date'] = (git('log', '-1', '--format=%cs', r, cwd=repo).strip()
                                          for r in (old, new))
    info['commits'] = git('log', '--format=%h %cs %s', '%s..%s' % (old, new),
                          cwd=repo).splitlines()
    info['changed'] = git('diff', '--no-renames', '--name-status', old, new,
                          cwd=repo).splitlines()
    info['kind'] = classify([line.split('\t', 1)[1] for line in info['changed']])
    extra = [fetch_mibs(pins[name][1], pins[name][0], os.path.join(work, name))
             for name in ('net-snmp', 'librenms')]
    log('running fix_cisco_mibs.py at both commits...')
    outs = [os.path.join(work, 'out-old'), os.path.join(work, 'out-new')]
    procs = [start_fix(os.path.join(work, 'cisco-mibs', d), o, extra)
             for d, o in zip(('old', 'new'), outs)]
    info['fix_old'] = finish_fix(procs[0], old[:7])
    info['fix_new'] = finish_fix(procs[1], new[:7])
    info['output'] = compare_outputs(*outs)
    return make_report(info)


def main():
    ap = argparse.ArgumentParser(
        description='Check whether cisco-mibs has moved on from the commit in UPSTREAM.')
    ap.add_argument('--report-dir', metavar='DIR',
                    help='also write the report to DIR/title.txt and DIR/body.md')
    ap.add_argument('--upstream', metavar='FILE', default=UPSTREAM,
                    help='the file with the pinned commits (default: UPSTREAM)')
    ap.add_argument('--keep', metavar='DIR',
                    help='keep the clones and both outputs in DIR (DIR must not exist)')
    args = ap.parse_args()

    def log(msg):
        print(msg, file=sys.stderr)
        sys.stderr.flush()

    try:
        if args.keep and os.path.exists(args.keep):
            raise Error('%s already exists' % args.keep)
        with tempfile.TemporaryDirectory(prefix='ent9-upstream-') as tmp:
            if args.keep:
                os.makedirs(args.keep)
            report = check(args.keep or tmp, log, args.upstream)
    except (Error, OSError, ValueError) as e:
        print('error: %s' % e, file=sys.stderr)
        sys.exit(2)
    if report is None:
        log('cisco-mibs %s is still at the commit in UPSTREAM' % BRANCH)
        sys.exit(0)
    title, body = report
    print('# ' + title + '\n')
    print(body)
    if args.report_dir:
        os.makedirs(args.report_dir, exist_ok=True)
        for name, text in (('title.txt', title + '\n'), ('body.md', body)):
            with open(os.path.join(args.report_dir, name), 'w', encoding='utf-8',
                      newline='\n') as fh:
                fh.write(text)
    if args.keep:
        log('clones and outputs kept in %s' % args.keep)
    sys.exit(1)


if __name__ == '__main__':
    main()
