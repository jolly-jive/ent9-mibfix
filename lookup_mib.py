#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""Tell which MIB module and file define an OID or a name.

Usage:
    python3 lookup_mib.py MIB_DIR [MIB_DIR ...] QUERY [QUERY ...] [--deps [--exclude-dir DIR] [--load-order] | --detail]
    python3 lookup_mib.py MIB_DIR [MIB_DIR ...] [--deps [--exclude-dir DIR] [--load-order] | --detail] < queries.txt

MIB_DIR  a directory of MIBs, such as OUT_DIR/mibs written by fix_cisco_mibs.py.
         The leading arguments that are directories are MIB_DIRs; the rest are
         queries. If several directories define the same module, the first wins
QUERY    a numeric OID (1.3.6.1.4.1.9.9.13.1.3.1.3.1), a name (ifDescr), a
         module-qualified name (IF-MIB::ifDescr), or a name with an instance
         (ifDescr.1, SNMPv2-SMI::enterprises.9.9.13)

With no QUERY, reads one per line from stdin (the first word of each line, so
snmpwalk -On output works too). Prints one line per match:

    OID <tab> MODULE::name[.rest] <tab> kind <tab> file

where name is the deepest node any MIB defines and .rest the arcs below it. A
name defined by several modules gives one line each.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_mibs  # noqa: E402
import smiscan  # noqa: E402

NUMERIC_RE = re.compile(r'^\.?(\d+(?:\.\d+)*)$')
SYMBOLIC_RE = re.compile(r'^(?:([A-Za-z][A-Za-z0-9_-]*)::)?([A-Za-z][A-Za-z0-9-]*)((?:\.\d+)*)$')


def parse_oid(s):
    return tuple(int(c) for c in s.strip('.').split('.')) if s else ()


class Lookup:
    def __init__(self, mods, index):
        self.mods = mods
        self.index = index
        self.by_name = {}  # name -> {oid}
        for oid, hits in index.nodes.items():
            for _, name, _ in hits:
                self.by_name.setdefault(name, set()).add(oid)

    def oids(self, query):
        """OIDs a query stands for; empty if it is unknown."""
        m = NUMERIC_RE.match(query)
        if m:
            return [parse_oid(m.group(1))]
        m = SYMBOLIC_RE.match(query)
        if not m:
            return []
        mod, name, rest = m.group(1), m.group(2), parse_oid(m.group(3))
        if mod:
            info = self.mods.get(mod)
            if not info or (name not in info['defs'] and name not in info['imports']):
                return []
            base = self.index.resolve(mod, name)
            return [base + rest] if base else []
        return sorted(oid + rest for oid in self.by_name.get(name, ()))

    def find(self, query):
        """[(oid, prefix, (module, name, kind))] for a query."""
        found = []
        for oid in self.oids(query):
            prefix, hits = self.index.match(oid)
            found.extend((oid, prefix, h) for h in hits)
        return found


# --------------------------------------------------------------------------
# definition text for --detail
# --------------------------------------------------------------------------

def definition(path, name, kind):
    """The definition of name in path, comments removed, or None."""
    text = smiscan.strip_comments(extract_mibs.read(path))
    kind_re = r'OBJECT\s+IDENTIFIER' if kind == 'OBJECT IDENTIFIER' else re.escape(kind)
    m = re.search(r'(?<![A-Za-z0-9-])' + re.escape(name) + r'\s+' + kind_re + r'\b', text)
    if not m:
        return None
    # up to the closing brace of "::= { ... }", skipping quoted strings
    i, n, assigned = m.end(), len(text), False
    while i < n:
        ch = text[i]
        if ch == '"':
            j = text.find('"', i + 1)
            i = n if j < 0 else j + 1
            continue
        if text.startswith('::=', i):
            assigned = True
        elif assigned and ch == '}':
            break
        i += 1
    lines = [ln.rstrip() for ln in text[m.start():i + 1].split('\n')]
    lines = [ln for ln in lines if ln]
    # keep the indentation relative to the first line
    indent = min(len(ln) - len(ln.lstrip()) for ln in lines[1:]) if len(lines) > 1 else 0
    return '\n'.join([lines[0].strip()] + ['    ' + ln[indent:] for ln in lines[1:]])


# --------------------------------------------------------------------------

def read_queries(stream):
    for line in stream:
        words = line.split()
        if words and not words[0].startswith('#'):
            yield words[0]


def main():
    ap = argparse.ArgumentParser(
        usage='%(prog)s MIB_DIR [MIB_DIR ...] [QUERY ...] '
              '[--deps [--exclude-dir DIR] [--load-order] | --detail]',
        description='Tell which MIB module and file define an OID or a name. '
                    'With no QUERY, reads one per line from stdin.')
    ap.add_argument('args', nargs='+', metavar='MIB_DIR|QUERY',
                    help='directories of MIBs (the leading arguments that are '
                         'directories), then OIDs or names such as '
                         '1.3.6.1.2.1.2.2.1.2, ifDescr, IF-MIB::ifDescr.1')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--deps', action='store_true',
                      help='instead of the matches, print the files needed to name '
                           'them, including the modules they import, one per line')
    mode.add_argument('--detail', action='store_true',
                      help='also print each definition (SYNTAX, MAX-ACCESS, '
                           'DESCRIPTION and so on)')
    ap.add_argument('--exclude-dir', action='append', default=[], metavar='DIR',
                    help='with --deps, leave out modules that already exist in DIR or '
                         'its subdirectories, e.g. /usr/share/snmp/mibs; may be repeated')
    ap.add_argument('--load-order', action='store_true',
                    help='with --deps, list the files so that each comes after the ones '
                         'it imports (default: by name)')
    args = ap.parse_args()

    n = 0
    while n < len(args.args) and os.path.isdir(args.args[n]):
        n += 1
    mibdirs, queries = args.args[:n], args.args[n:]
    if not mibdirs:
        sys.exit('error: the first argument must be a MIB directory: %s' % args.args[0])
    if args.exclude_dir and not args.deps:
        sys.exit('error: --exclude-dir needs --deps')
    if args.load_order and not args.deps:
        sys.exit('error: --load-order needs --deps')
    for d in args.exclude_dir:
        if not os.path.isdir(d):
            sys.exit('error: not a directory: %s' % d)
    if not queries:
        if sys.stdin.isatty():
            sys.exit('error: give a QUERY or pipe queries into stdin')
        queries = list(read_queries(sys.stdin))

    progress = extract_mibs.Progress()
    mods = extract_mibs.load_modules(mibdirs, progress)
    progress.show('indexing OIDs')
    lookup = Lookup(mods, extract_mibs.OidIndex(mods))
    exclude = set()
    for d in args.exclude_dir:
        progress.show('reading %s' % d)
        exclude |= extract_mibs.module_names(d)
    progress.clear()

    roots, unknown = set(), []
    for q in queries:
        found = lookup.find(q)
        if not found:
            unknown.append(q)
        for oid, prefix, (mod, name, kind) in found:
            roots.add(mod)
            if args.deps:
                continue
            rest = ''.join('.%d' % c for c in oid[len(prefix):])
            print('\t'.join(['.'.join(map(str, oid)), '%s::%s%s' % (mod, name, rest),
                             kind, mods[mod]['path']]))
            if args.detail:
                text = definition(mods[mod]['path'], name, kind)
                print('\n'.join('    ' + ln for ln in (text or '(not found)').split('\n')))
                print()

    if args.deps:
        needed, skipped, missing = extract_mibs.dependencies(mods, roots, exclude)
        extract_mibs.print_files(mods, needed, args.load_order)
        if skipped:
            print('left out (already in --exclude-dir): %s' % ', '.join(sorted(skipped)),
                  file=sys.stderr)
        if missing:
            print('warning: imported modules not found: %s' % ', '.join(sorted(missing)),
                  file=sys.stderr)
    sys.stdout.flush()
    for q in unknown:
        print('not found: %s' % q, file=sys.stderr)
    if unknown:
        sys.exit(1)


if __name__ == '__main__':
    main()
