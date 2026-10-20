#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""List the MIB files needed to name the OIDs in an snmpwalk.

Usage:
    snmpbulkwalk -On ... HOST 1.3.6.1.4.1 | python3 extract_mibs.py MIB_DIR [...] [options]
    python3 extract_mibs.py MIB_DIR [...] [options] < walk.txt

MIB_DIR  a directory of MIBs that loads cleanly, such as OUT_DIR/mibs written
         by fix_cisco_mibs.py. May be repeated; if several directories define
         the same module, the first one wins

Reads the walk from stdin. It must be numeric (snmpwalk -On). Prints the path
of every MIB file needed, including the modules they import, one per line.
Unresolved OIDs and a summary go to stderr.

--verify loads only the listed files into Net-SNMP (snmptranslate) and checks
that every OID gets the same name as with all of MIB_DIR loaded.
"""
import argparse
import os
import pickle
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smiscan  # noqa: E402

DEFAULT_PREFIXES = ('1.3.6.1.4.1.9', '1.3.6.1.4.1.14179')
ROOTS = {'ccitt': (0,), 'iso': (1,), 'joint-iso-ccitt': (2,)}

NUMERIC_RE = re.compile(r'^\.?(\d+(?:\.\d+)+)\s+=')
SYMBOLIC_RE = re.compile(r'^[A-Za-z][A-Za-z0-9-]*(?:::|\.)\S*\s+=')


def read(p):
    with open(p, encoding='latin-1') as fh:
        return fh.read()


class Progress:
    """One status line on stderr, rewritten in place. Silent unless stderr is a tty."""

    def __init__(self, stream=sys.stderr):
        self.stream = stream
        self.on = stream.isatty()
        self.last = 0

    def show(self, msg, force=True):
        if not self.on:
            return
        now = time.monotonic()
        if not force and now - self.last < 0.2:
            return
        self.last = now
        self.stream.write('\r\033[K' + msg)
        self.stream.flush()

    def clear(self):
        if self.on:
            self.stream.write('\r\033[K')
            self.stream.flush()


QUIET = Progress(open(os.devnull, 'w'))


# --------------------------------------------------------------------------
# MIB index
# --------------------------------------------------------------------------

def cache_path():
    base = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
    return os.path.join(base, 'ent9-mibfix', 'modules.pickle')


def scanner_stamp():
    """Changes when the scanning code changes, so old cache entries are dropped."""
    return tuple(os.stat(f).st_mtime_ns for f in (smiscan.__file__, __file__))


def read_cache(path):
    try:
        with open(path, 'rb') as fh:
            data = pickle.load(fh)
        if data.get('stamp') == scanner_stamp():
            return data['files']
    except Exception:
        pass
    return {}


def write_cache(path, files):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = '%s.%d' % (path, os.getpid())
        with open(tmp, 'wb') as fh:
            pickle.dump({'stamp': scanner_stamp(), 'files': files}, fh, pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    except OSError:
        pass


def scan_file(p):
    """(module, imports, defs) of a MIB file, or None if it has no module."""
    tc = smiscan.clean(read(p))
    mod = smiscan.module_name(tc)
    if not mod:
        return None
    imports, _ = smiscan.parse_imports(tc)
    defs = {name: (macro, comps) for name, macro, comps in smiscan.oid_assignments(tc)}
    return mod, imports, defs


def load_modules(mibdirs, progress=QUIET, cache=None):
    """Return {module: info} for every MIB file in mibdirs.

    Scan results are kept in cache (a file path; default cache_path(), '' for
    none) and reused while a file's size and mtime stay the same.
    """
    if cache is None:
        cache = cache_path()
    cached = read_cache(cache) if cache else {}
    changed = False
    mods = {}
    paths = [os.path.join(d, f) for d in mibdirs for f in sorted(os.listdir(d))]
    for i, p in enumerate(paths, 1):
        progress.show('reading MIB files: %d/%d' % (i, len(paths)), force=False)
        try:
            st = os.stat(p)
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        key, sig = os.path.abspath(p), (st.st_mtime_ns, st.st_size)
        hit = cached.get(key)
        if hit and hit[0] == sig:
            entry = hit[1]
        else:
            entry = scan_file(p)
            cached[key] = (sig, entry)
            changed = True
        if not entry or entry[0] in mods:
            continue
        mod, imports, defs = entry
        mods[mod] = {'path': p, 'imports': imports, 'defs': defs}
    if cache and changed:
        write_cache(cache, cached)
    return mods


def module_names(d):
    """Module names defined by the files in d and its subdirectories."""
    names = set()
    for root, _, files in os.walk(d, followlinks=True):
        for f in files:
            mod = smiscan.module_name(smiscan.clean(read(os.path.join(root, f))))
            if mod:
                names.add(mod)
    return names


class OidIndex:
    def __init__(self, mods):
        self.mods = mods
        # fallback for symbols used without an import
        self.anywhere = {}
        for mod, info in mods.items():
            for name in info['defs']:
                self.anywhere.setdefault(name, mod)
        self.memo = {}
        self.nodes = {}  # oid tuple -> [(module, name, macro)]
        for mod, info in sorted(mods.items()):
            for name, (macro, _) in info['defs'].items():
                oid = self.resolve(mod, name)
                if oid:
                    self.nodes.setdefault(oid, []).append((mod, name, macro))

    def lookup(self, mod, name):
        """Module whose definition of name is visible from mod."""
        info = self.mods.get(mod)
        if info and name in info['defs']:
            return mod
        if info and name in info['imports'] and info['imports'][name] in self.mods:
            return self.lookup(info['imports'][name], name)
        return self.anywhere.get(name)

    def resolve(self, mod, name, seen=()):
        key = (mod, name)
        if key in self.memo:
            return self.memo[key]
        if name in ROOTS:
            return ROOTS[name]
        owner = self.lookup(mod, name)
        if owner is None or (owner, name) in seen:
            return None
        if owner != mod:
            oid = self.resolve(owner, name, seen)
            self.memo[key] = oid
            return oid
        _, comps = self.mods[mod]['defs'][name]
        oid = self.resolve_value(mod, comps, seen + (key,))
        self.memo[key] = oid
        return oid

    def resolve_value(self, mod, comps, seen):
        if not comps:
            return None
        first, rest = comps[0], comps[1:]
        if isinstance(first, int):
            base = (first,)
        else:
            base = self.resolve(mod, first, seen)
            if base is None:
                return None
        return base + tuple(rest)

    def match(self, oid):
        """Longest defined prefix of oid: (prefix, [(module, name, macro)])."""
        for n in range(len(oid), 0, -1):
            hit = self.nodes.get(oid[:n])
            if hit:
                return oid[:n], hit
        return (), []

    def name_of(self, oid):
        prefix, hit = self.match(oid)
        if not hit:
            return '.'.join(map(str, oid))
        tail = oid[len(prefix):]
        return hit[0][1] + ''.join('.%d' % c for c in tail)


def subdirs(d):
    """d and all its subdirectories, following symlinks."""
    return [root for root, _, _ in os.walk(d, followlinks=True)]


def extract(index, targets):
    """Return (modules defining targets, {oid: length of deepest known node} of the rest)."""
    direct = set()
    unresolved = {}
    for oid in targets:
        prefix, hit = index.match(oid)
        objs = [h for h in hit if h[2] == 'OBJECT-TYPE']
        if objs and len(oid) > len(prefix):
            direct.update(h[0] for h in objs)
        else:
            unresolved[oid] = len(prefix)
    return direct, unresolved


def dependencies(mods, roots, exclude):
    """roots plus every module they import, recursively.

    Returns (needed, skipped, missing): modules found in mods, excluded modules
    that were reached, and modules that are neither in mods nor excluded.
    """
    needed, skipped, missing, todo = set(), set(), set(), list(roots)
    while todo:
        mod = todo.pop()
        if mod in needed:
            continue
        if mod in exclude:
            skipped.add(mod)
            continue
        if mod not in mods:
            missing.add(mod)
            continue
        needed.add(mod)
        for dep in set(mods[mod]['imports'].values()):
            if dep not in needed:
                todo.append(dep)
    return needed, skipped, missing


# --------------------------------------------------------------------------
# verify with Net-SNMP
# --------------------------------------------------------------------------

TREE_RE = re.compile(r'^"([^"]*)"\s+"([\d.]+)"')


def start_tree(mibpath, modules):
    """Start snmptranslate dumping the tree it builds from mibpath and modules."""
    env = dict(os.environ, SNMPCONFPATH=os.devnull)  # ignore snmp.conf and ~/.snmp
    env.pop('MIBS', None)
    env.pop('MIBDIRS', None)
    cmd = ['snmptranslate', '-Pu', '-M', os.pathsep.join(mibpath),
           '-m', os.pathsep.join(sorted(modules)), '-Tz']
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, universal_newlines=True, errors='replace')


def finish_tree(proc, progress=QUIET, label=''):
    """Wait for start_tree; return ({oid tuple: name}, set of warnings)."""
    t0 = time.monotonic()
    while True:
        try:
            out, err = proc.communicate(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            progress.show('%s (%ds)' % (label, time.monotonic() - t0))
    tree = {}
    for line in out.splitlines():
        m = TREE_RE.match(line)
        if m:
            tree[tuple(int(c) for c in m.group(2).split('.'))] = m.group(1)
    # drop directories so warnings from different copies compare equal
    warnings = {re.sub(r'[^\s()]*[/\\]', '', w) for w in err.splitlines()
                if w and not w.startswith('MIB search path:')}
    return tree, warnings


def tree_name(tree, oid):
    """Net-SNMP style name of oid: deepest known node plus the numeric rest.

    Returns (length of that node's OID, name).
    """
    for n in range(len(oid), 0, -1):
        if oid[:n] in tree:
            return n, tree[oid[:n]] + ''.join('.%d' % c for c in oid[n:])
    return 0, '.'.join(map(str, oid))


def verify(files, modules, targets, unresolved, exclude_dirs, reference, progress=QUIET):
    """Check that files alone name every target as the reference tree does.

    reference is the result of finish_tree() on all MIBs. Targets in
    unresolved (from extract) are skipped unless the reference knows a deeper
    node than our index did. Returns (gaps, warnings, checked):
    {(reference name, name with files only): count}, the snmptranslate
    warnings that only appear with files only, and the number of targets checked.
    """
    ref_tree, ref_warnings = reference
    with tempfile.TemporaryDirectory(prefix='ent9-verify-') as tmp:
        for p in files:
            shutil.copy(p, tmp)
        path = [tmp] + [s for d in exclude_dirs for s in subdirs(d)]
        tree, warnings = finish_tree(start_tree(path, modules), progress,
                                     'verify: loading the %d extracted files' % len(files))
    gaps, checked = {}, 0
    for oid in targets:
        n, want = tree_name(ref_tree, oid)
        if oid in unresolved and n <= unresolved[oid]:
            continue
        checked += 1
        if tree_name(tree, oid)[1] != want:
            # group by the reference node, not by instance
            key = (ref_tree[oid[:n]] if n else want, tree_name(tree, oid[:n])[1])
            gaps[key] = gaps.get(key, 0) + 1
    return gaps, sorted(warnings - ref_warnings), checked


# --------------------------------------------------------------------------
# walk input
# --------------------------------------------------------------------------

def read_walk(stream):
    """Return (numeric OIDs, count of symbolic OID lines)."""
    oids, symbolic = [], 0
    for line in stream:
        m = NUMERIC_RE.match(line)
        if m:
            oids.append(tuple(int(c) for c in m.group(1).split('.')))
        elif SYMBOLIC_RE.match(line):
            symbolic += 1
        # anything else is a continuation of a multi-line value
    return oids, symbolic


def parse_prefix(s):
    try:
        return tuple(int(c) for c in s.strip('.').split('.'))
    except ValueError:
        raise argparse.ArgumentTypeError('not a numeric OID: %s' % s)


# --------------------------------------------------------------------------
# archive
# --------------------------------------------------------------------------

def archive_format(path):
    """Return (top folder, extension) of an archive name, or None if unsupported."""
    base = os.path.basename(path)
    for ext in ('.tar.gz', '.tgz', '.tar', '.zip'):
        if base.lower().endswith(ext):
            return base[:-len(ext)], ext
    return None


def write_archive(path, files):
    top, ext = archive_format(path)
    if ext == '.zip':
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in files:
                z.write(p, top + '/' + os.path.basename(p))
    else:
        mode = 'w' if ext == '.tar' else 'w:gz'
        with tarfile.open(path, mode) as t:
            for p in files:
                t.add(p, top + '/' + os.path.basename(p))


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description='List the MIB files needed to name the OIDs in an snmpwalk '
                    '(read from stdin, numeric: snmpwalk -On).')
    ap.add_argument('mibdirs', nargs='+', metavar='MIB_DIR',
                    help='directory of MIBs, e.g. OUT_DIR/mibs from fix_cisco_mibs.py; '
                         'the first one wins when several define a module')
    ap.add_argument('--prefix', action='append', type=parse_prefix, metavar='OID',
                    help='only look at OIDs under this prefix; may be repeated '
                         '(default: %s)' % ' and '.join(DEFAULT_PREFIXES))
    ap.add_argument('--exclude-dir', action='append', default=[], metavar='DIR',
                    help='leave out modules that already exist in DIR or its '
                         'subdirectories, e.g. /usr/share/snmp/mibs; may be repeated')
    ap.add_argument('--archive', metavar='FILE',
                    help='also pack the files into FILE (.zip, .tar.gz, .tgz or .tar)')
    ap.add_argument('--verify', action='store_true',
                    help='check with snmptranslate that the listed files name every OID '
                         'as all of MIB_DIR does; exit 1 if not')
    args = ap.parse_args()
    prefixes = args.prefix or [parse_prefix(p) for p in DEFAULT_PREFIXES]

    for d in args.mibdirs:
        if not os.path.isdir(d):
            sys.exit('error: not a directory: %s' % d)
    if sys.stdin.isatty():
        sys.exit('error: pipe an snmpwalk -On output into stdin')
    if args.archive and not archive_format(args.archive):
        sys.exit('error: --archive must end in .zip, .tar.gz, .tgz or .tar')
    if args.verify and not shutil.which('snmptranslate'):
        sys.exit('error: --verify needs snmptranslate (Net-SNMP) in PATH')

    oids, symbolic = read_walk(sys.stdin)
    if symbolic:
        print('warning: %d lines have non-numeric OIDs and were ignored; '
              're-run snmpwalk with -On' % symbolic, file=sys.stderr)
    if not oids:
        sys.exit('error: no numeric OIDs in the input; run snmpwalk with -On')
    targets = sorted({o for o in oids if any(o[:len(p)] == p for p in prefixes)})

    progress = Progress()
    if args.verify:
        # the reference tree takes as long as reading the MIBs, so build it meanwhile
        ref_path = args.mibdirs + [s for d in args.exclude_dir for s in subdirs(d)]
        ref_proc = start_tree(ref_path, ['ALL'])
    mods = load_modules(args.mibdirs, progress)
    progress.show('indexing OIDs')
    index = OidIndex(mods)
    exclude = set()
    for d in args.exclude_dir:
        progress.show('reading %s' % d)
        exclude |= module_names(d)
    direct, unresolved = extract(index, targets)
    progress.clear()

    needed, skipped, missing = dependencies(mods, direct, exclude)
    files = sorted(mods[m]['path'] for m in needed)
    for p in files:
        print(p)
    sys.stdout.flush()
    if args.archive:
        write_archive(args.archive, files)

    err = sys.stderr
    print('%d OIDs read, %d under %s' % (
        len(oids), len(targets), ', '.join('.'.join(map(str, p)) for p in prefixes)), file=err)
    print('%d modules define them; %d files in total with imports' % (
        len(direct), len(files)), file=err)
    if skipped:
        print('left out (already in --exclude-dir): %s' % ', '.join(sorted(skipped)), file=err)
    if missing:
        print('warning: imported modules not found: %s' % ', '.join(sorted(missing)), file=err)
    if unresolved:
        subtrees = {}  # deepest known name -> count
        for oid, n in unresolved.items():
            key = index.name_of(oid[:n + 1] if n else oid)
            subtrees[key] = subtrees.get(key, 0) + 1
        print('warning: %d OIDs not defined by any MIB (count by subtree):' % (
            len(unresolved)), file=err)
        for key, n in sorted(subtrees.items(), key=lambda kv: (-kv[1], kv[0])):
            print('  %6d  %s' % (n, key), file=err)

    if args.verify:
        reference = finish_tree(ref_proc, progress,
                                'verify: loading all MIBs for reference')
        gaps, warnings, checked = verify(files, needed, targets, unresolved,
                                         args.exclude_dir, reference, progress)
        progress.clear()
        if warnings:
            print('verify: snmptranslate warnings with only the listed files:', file=err)
            for w in warnings:
                print('  ' + w, file=err)
        if gaps:
            print('verify: FAILED: %d OIDs get a different name with only the listed '
                  'files (count, name with all MIBs <- with listed files):' % (
                      sum(gaps.values())), file=err)
            for (want, got), n in sorted(gaps.items(), key=lambda kv: (-kv[1], kv[0])):
                print('  %6d  %s <- %s' % (n, want, got), file=err)
        if gaps or warnings:
            sys.exit(1)
        print('verify: OK, %d OIDs get the same name as with all MIBs '
              '(%d not defined by any MIB are skipped)' % (checked, len(targets) - checked),
              file=err)


if __name__ == '__main__':
    main()
