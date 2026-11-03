#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""Check that a change to fix_cisco_mibs.py keeps its output, or show how it changed.

Usage:
    python3 tools/check_fix_output.py CISCO_MIBS_REPO [EXTRA_MIB_DIR ...] [--baseline REV] [--keep DIR]

Runs fix_cisco_mibs.py twice on the same input, at the same time: once as it
is at REV (default HEAD, taken with git archive) and once as it is in the
working tree. Then compares the two OUT_DIRs and the JSON each printed.
Prints the differences and exits 1 if there are any, 0 if the output is the same.

Use it before committing a change that should not change the output (a
refactoring), or to see exactly what a fix changes.
"""
import argparse
import difflib
import filecmp
import io
import os
import subprocess
import sys
import tarfile
import tempfile

TOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_DIFF_LINES = 40  # per file


def export(rev, dest):
    """Write the files of rev into dest."""
    data = subprocess.run(['git', '-C', TOP, 'archive', rev], stdout=subprocess.PIPE,
                          check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        if hasattr(tarfile, 'data_filter'):
            tar.extractall(dest, filter='data')
        else:
            tar.extractall(dest)


def start(script_dir, repo, out, extra):
    return subprocess.Popen([sys.executable, os.path.join(script_dir, 'fix_cisco_mibs.py'), '-q',
                             repo, out] + extra,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)


def finish(proc, label):
    out, err = proc.communicate()
    if proc.returncode not in (0, 1):  # 1: fixes that did not apply, output still written
        sys.exit('error: fix_cisco_mibs.py (%s) failed:\n%s' % (label, err))
    return out


def files_under(d):
    return sorted(os.path.relpath(os.path.join(root, f), d)
                  for root, _, files in os.walk(d) for f in files)


def text_lines(path):
    """Lines of a file: CHANGES*.md and changes.json are UTF-8, MIBs may be Latin-1."""
    with open(path, 'rb') as fh:
        data = fh.read()
    try:
        return data.decode('utf-8').splitlines(True)
    except UnicodeDecodeError:
        return data.decode('latin-1').splitlines(True)


def show_diff(a, b, name):
    lines = list(difflib.unified_diff(text_lines(a), text_lines(b),
                                      'baseline/' + name, 'working/' + name))
    for line in lines[:MAX_DIFF_LINES]:
        sys.stdout.write(line if line.endswith('\n') else line + '\n')
    if len(lines) > MAX_DIFF_LINES:
        print('... %d more lines' % (len(lines) - MAX_DIFF_LINES))


def main():
    ap = argparse.ArgumentParser(
        description='Run fix_cisco_mibs.py at a git revision and from the working tree, '
                    'and compare the output.')
    ap.add_argument('repo', metavar='CISCO_MIBS_REPO', help='a clone of cisco/cisco-mibs')
    ap.add_argument('extra', nargs='*', metavar='EXTRA_MIB_DIR',
                    help='passed on to fix_cisco_mibs.py')
    ap.add_argument('--baseline', default='HEAD', metavar='REV',
                    help='git revision to compare with (default: HEAD)')
    ap.add_argument('--keep', metavar='DIR',
                    help='keep both outputs in DIR/baseline and DIR/working (DIR must not exist)')
    args = ap.parse_args()
    if args.keep and os.path.exists(args.keep):
        sys.exit('error: %s already exists' % args.keep)
    repo = os.path.abspath(args.repo)
    extra = [os.path.abspath(d) for d in args.extra]

    with tempfile.TemporaryDirectory(prefix='ent9-check-') as tmp:
        work = args.keep or tmp
        base_src = os.path.join(tmp, 'src')
        export(args.baseline, base_src)
        base_out, work_out = os.path.join(work, 'baseline'), os.path.join(work, 'working')
        print('running fix_cisco_mibs.py at %s and from the working tree...' % args.baseline,
              file=sys.stderr)
        procs = [start(base_src, repo, base_out, extra), start(TOP, repo, work_out, extra)]
        base_json, work_json = finish(procs[0], args.baseline), finish(procs[1], 'working tree')

        base_files, work_files = files_under(base_out), files_under(work_out)
        only_base = sorted(set(base_files) - set(work_files))
        only_work = sorted(set(work_files) - set(base_files))
        common = sorted(set(base_files) & set(work_files))
        _, changed, errors = filecmp.cmpfiles(base_out, work_out, common, shallow=False)
        for f in only_base:
            print('only at %s: %s' % (args.baseline, f))
        for f in only_work:
            print('only in the working tree: %s' % f)
        for f in changed + errors:
            print('changed: %s' % f)
            show_diff(os.path.join(base_out, f), os.path.join(work_out, f), f)
        if base_json != work_json:
            print('changed: counts printed to stdout')
            sys.stdout.writelines(difflib.unified_diff(
                base_json.splitlines(True), work_json.splitlines(True), 'baseline', 'working'))
        differs = only_base or only_work or changed or errors or base_json != work_json
        sys.stdout.flush()
        print('%s: %d files compared' % ('DIFFERENT' if differs else 'SAME', len(common)),
              file=sys.stderr)
        if args.keep:
            print('outputs kept in %s' % args.keep, file=sys.stderr)
    sys.exit(1 if differs else 0)


if __name__ == '__main__':
    main()
