#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""Turn Cisco's public MIBs (v2/) into a self-contained set that loads cleanly.

Usage:
    python3 fix_cisco_mibs.py CISCO_MIBS_REPO OUT_DIR [EXTRA_MIB_DIR ...] [-q]

CISCO_MIBS_REPO  a clone of https://github.com/cisco/cisco-mibs
OUT_DIR          created by this script (aborts if it exists). Writes one
                 <module name>.my per module to OUT_DIR/mibs/, and logs every
                 change to OUT_DIR/CHANGES.md, CHANGES.ja.md and changes.json
EXTRA_MIB_DIR    where to look for standard MIBs that v2/ imports but Cisco
                 does not ship (e.g. Net-SNMP's mibs/). May be repeated
-q, --quiet      do not show progress on stderr

Prints a count of changes by kind (JSON) to stdout. Progress goes to stderr:
one line rewritten in place on a terminal, otherwise one line per step.

The source repository is never modified.
"""
import argparse
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_mibs  # noqa: E402
import smiscan  # noqa: E402

CHANGES = []


class Steps(extract_mibs.Progress):
    """Progress as "[n/N] step: 47% (i/total)", rewritten in place on a terminal.

    Off a terminal (e.g. a log file), only the step titles are printed, one per line.
    """

    def __init__(self, total, stream=sys.stderr, quiet=False):
        super().__init__(stream, quiet)
        self.lines = not quiet and not self.on
        self.total, self.n, self.title = total, 0, ''

    def step(self, title):
        self.n += 1
        self.title = '[%d/%d] %s' % (self.n, self.total, title)
        if self.lines:
            self.stream.write(self.title + '...\n')
            self.stream.flush()
        self.show(self.title)

    def each(self, items, what=''):
        """Yield the items, showing how far through them we are."""
        items = list(items)
        for i, x in enumerate(items):
            self.show('%s%s: %d%% (%d/%d)' % (self.title, what, i * 100 // len(items), i, len(items)),
                      force=False)
            yield x


PROGRESS = Steps(0, quiet=True)

# Messages are written in English here. Their Japanese versions (for
# CHANGES.ja.md) are in messages.ja.json, keyed by the English text.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'messages.ja.json'),
          encoding='utf-8') as _fh:
    JA = json.load(_fh)


class Msg:
    """A str.format template plus its arguments, rendered in English or Japanese.

    Arguments may themselves be Msg objects, or lists of them (joined with ", ").
    """

    def __init__(self, text, **args):
        self.text, self.args = text, args

    def render(self, ja=False):
        def arg(v):
            if isinstance(v, Msg):
                return v.render(ja)
            if isinstance(v, list):
                return ', '.join(arg(x) for x in v)
            return v
        return (JA[self.text] if ja else self.text).format(**{k: arg(v) for k, v in self.args.items()})


def log(module, kind, text, **args):
    msg = Msg(text, **args)
    CHANGES.append({'module': module, 'kind': kind, 'detail': msg.render(), 'detail_ja': msg.render(ja=True)})


def read(p):
    with open(p, encoding='latin-1') as fh:
        return fh.read()


def write(p, text):
    with open(p, 'w', encoding='latin-1', newline='\n') as fh:
        fh.write(text)


def header_info(text):
    tc = smiscan.clean(text)
    mod = smiscan.module_name(tc)
    m = re.search(r'LAST-UPDATED\s*"(\d+)Z?"', smiscan.strip_comments(text))
    lu = m.group(1) if m else ''
    # normalise 2-digit years (YYMMDDHHMM) to 4 digits for comparison
    if len(lu) == 10:
        lu = ('19' if int(lu[:2]) > 50 else '20') + lu
    return mod, lu


# --------------------------------------------------------------------------
# 1. choose one file per module, name it after the module
# --------------------------------------------------------------------------

def collect(srcdir, pattern=r'\.my$', what=''):
    out = {}
    for f in PROGRESS.each(sorted(os.listdir(srcdir)), what):
        p = os.path.join(srcdir, f)
        if not os.path.isfile(p) or not re.search(pattern, f):
            continue
        text = read(p)
        mod, lu = header_info(text)
        if mod:
            out.setdefault(mod, []).append((lu, f, p))
    return out


def select_modules(v2dir, outdir):
    mods = collect(v2dir, r'\.(my|txt)$')
    chosen = {}
    for mod, cands in sorted(mods.items()):
        cands.sort(key=lambda c: (c[0], c[1] == mod + '.my'), reverse=True)
        lu, f, p = cands[0]
        chosen[mod] = p
        if len(cands) > 1:
            def dated(c):
                return Msg('{file} ({date})', file=c[1], date=c[0] or Msg('no date'))
            log(mod, 'duplicate-module',
                '{n} files define the same module. Kept {kept}, which has the newest '
                'LAST-UPDATED (on a tie, the one named after the module). Dropped {others}',
                n=len(cands), kept=dated(cands[0]), others=[dated(c) for c in cands[1:]])
        if f != mod + '.my':
            same_stem = os.path.splitext(f)[0] == mod
            log(mod, 'renamed', '{file} -> {mod}.my ({reason})', file=f, mod=mod,
                reason=Msg('extension unified to .my' if same_stem else 'file name did not match the module name'))
        shutil.copyfile(p, os.path.join(outdir, mod + '.my'))
    return chosen


# --------------------------------------------------------------------------
# 2. bring in modules that are imported but not shipped in v2/, and the
#    OLD-CISCO-* modules (only in v1/, but current IOS still answers them)
# --------------------------------------------------------------------------

def add_old_cisco_modules(v1dir, outdir):
    present = {f[:-3] for f in os.listdir(outdir) if f.endswith('.my')}
    for mod, cands in sorted(collect(v1dir).items()):
        if not mod.startswith('OLD-CISCO-') or mod in present:
            continue
        cands.sort(reverse=True)
        lu, f, p = cands[0]
        shutil.copyfile(p, os.path.join(outdir, mod + '.my'))
        log(mod, 'added-old',
            'Not in v2/, but devices still answer its OIDs (enterprises.9.2 etc.). Added from v1/{file}', file=f)


def add_missing_dependencies(outdir, search_dirs):
    pool = {}
    for d in search_dirs:
        for mod, cands in collect(d, r'', ' (reading %s)' % d).items():
            cands.sort(reverse=True)
            pool.setdefault(mod, (d, cands[0][2]))
    passes = 0
    while True:
        passes += 1
        present = {f[:-3] for f in os.listdir(outdir) if f.endswith('.my')}
        needed = {}
        for f in PROGRESS.each(os.listdir(outdir), ' (pass %d)' % passes):
            if not f.endswith('.my'):
                continue
            info = smiscan.scan(read(os.path.join(outdir, f)))
            for mod in set(info['imports'].values()):
                if mod not in present:
                    needed.setdefault(mod, []).append(f[:-3])
        added = 0
        for mod, users in sorted(needed.items()):
            if mod in pool:
                src = pool[mod][1]
                shutil.copyfile(src, os.path.join(outdir, mod + '.my'))
                where = os.path.basename(os.path.dirname(src)) + '/' + os.path.basename(src)
                head = ', '.join(sorted(users)[:5])
                if len(users) > 5:
                    text = 'Not in v2/, but imported by {users} and others. Added from {where}'
                else:
                    text = 'Not in v2/, but imported by {users}. Added from {where}'
                log(mod, 'added-dependency', text, users=head, where=where)
                added += 1
        if not added:
            return


def report_unresolved_dependencies(outdir):
    present = {f[:-3] for f in os.listdir(outdir) if f.endswith('.my')}
    needed = {}
    for f in PROGRESS.each(os.listdir(outdir)):
        if f.endswith('.my'):
            for mod in set(smiscan.scan(read(os.path.join(outdir, f)))['imports'].values()):
                if mod not in present:
                    needed.setdefault(mod, []).append(f[:-3])
    for mod, users in sorted(needed.items()):
        users = ', '.join(sorted(users))
        log(mod, 'unresolved-dependency', 'Imported by {users}, but not found', users=users)


# --------------------------------------------------------------------------
# 3. targeted textual patches (each must match, otherwise it is reported)
# --------------------------------------------------------------------------

def patch(outdir, mod, old, new, desc, count=1, regex=False):
    """desc is a message text (see Msg), so literal braces must be doubled."""
    p = os.path.join(outdir, mod + '.my')
    if not os.path.exists(p):
        log(mod, 'patch-skipped', 'Module not found: {desc}', desc=Msg(desc))
        return
    text = read(p)
    if regex:
        new_text, n = re.subn(old, new, text, count=0 if count == 0 else count)
    else:
        n = text.count(old) if count == 0 else min(text.count(old), count)
        new_text = text.replace(old, new, n if count else -1)
    if n == 0:
        log(mod, 'patch-not-applied', 'Target text not found (maybe fixed upstream): {desc}', desc=Msg(desc))
        return
    write(p, new_text)
    log(mod, 'patched', desc)


def specific_patches(outdir):
    patch(outdir, 'ADMIN-AUTH-STATS-MIB', 'Integer32 (0..MAX)', 'Integer32 (0..2147483647)',
          'MAX used in an Integer32 range (not allowed in SMIv2). Replaced with 2147483647', count=0)
    patch(outdir, 'CISCO-LWAPP-RF-MIB', 'ciscoLwappRFMIBComplianceRev7".', 'ciscoLwappRFMIBComplianceRev7"',
          'Extra "." after the closing quote of a DESCRIPTION string')
    patch(outdir, 'CISCO-LWAPP-TC-MIB', r'\nEND\s*\n\s*END\b', '\nEND',
          'END appears twice at the end of the module', regex=True)
    patch(outdir, 'DNS-SERVER-MIB', r'(mib-2\s*\n\s*FROM\s+)RFC-1213\b', r'\1RFC1213-MIB',
          'mib-2 was imported from RFC-1213, which does not exist. Changed to RFC1213-MIB', regex=True)
    patch(outdir, 'CISCO-RTTMON-TC-MIB', 'a Fabric Path Network."\n\n        NOTE:',
          'a Fabric Path Network.\n\n        NOTE:',
          'DESCRIPTION string was closed before the NOTE paragraph')
    patch(outdir, 'CISCO-ST-TC', r'maximum of 32Gbit\."(\s*\n\s*fiftyG)', r'maximum of 32Gbit.\1',
          'DESCRIPTION string was closed in the middle of the value list', regex=True)
    patch(outdir, 'MPLS-LSR-MIB-CAPABILITY',
          r'(DESCRIPTION\s*\n\s*"Agent capabilities for MPLS-LSR-MIB"\s*\n\s*)LAST-UPDATED',
          r'\1REVISION', 'The second LAST-UPDATED clause should be REVISION', regex=True)
    patch(outdir, 'CISCO-FC-FE-MIB',
          r'compliance statement\."\s*\n(\s*)"-Added the following object to FcIfEntry:',
          r'compliance statement.\n\n\1 -Added the following object to FcIfEntry:',
          'One REVISION clause had two DESCRIPTION strings (the second revision has no date). '
          'Joined them into one without guessing a date', regex=True)
    patch(outdir, 'CISCO-LWAPP-DOT11-MIB', 'SEQUENCE OF Cld11axTargetWakeupTimeBoradcastEntry',
          'SEQUENCE OF Cld11axTargetWakeupTimeBroadcastEntry',
          'Typo in a SEQUENCE OF type name (Boradcast)')
    patch(outdir, 'CISCO-WAN-MODULE-CAPABILITY', r'(ciscoAgentCapability\s*\n\s*FROM\s+)CISCOWAN-SMI',
          r'\1CISCO-SMI', 'Wrong import source for ciscoAgentCapability (CISCO-SMI, not CISCOWAN-SMI)',
          regex=True)
    patch(outdir, 'CISCO-FC-FE-MIB', r'TRUE\(1\)(\s*\n\s*)FALSE\(0\)', r'true(1),\1false(0)',
          'Enum labels TRUE/FALSE (upper case, no comma) changed to true/false', regex=True)
    patch(outdir, 'CISCO-LWAPP-RF-MIB',
          r'\n(cLMultiBSSIDProfileRowStatus OBJECT-TYPE)[ \t]*\n(?=(?:[ \t]*(?:--[^\n]*)?\n)*\s*ciscoLwappRFMIBCompliances\b)',
          r'\n-- \1  (dangling duplicate header, commented out by fix script)\n',
          'A lone "cLMultiBSSIDProfileRowStatus OBJECT-TYPE" header with no body was left over '
          '(the object is already defined earlier as {{ cLMultiBSSIDProfileEntry 9 }}). Commented out', regex=True)
    # AGENT-CAPABILITIES whose OID clauses were left after every VARIATION
    p = os.path.join(outdir, 'CISCO-ATM-PVCTRAP-EXTN-CAPABILITY.my')
    if os.path.exists(p):
        text = read(p)
        pat = re.compile(r'^(\s*)(::=\s*\{\s*ciscoATMPVCTRAPExtnCapability\s+\d+\s*\})', re.M)
        hits = pat.findall(text)
        if len(hits) > 1:
            text = pat.sub(r'\1-- \2  (commented out by fix script)', text)
            text = re.sub(r'\nEND\s*$', '\n    ::= { ciscoATMPVCTRAPExtnCapability 1 }\n\nEND\n', text)
            write(p, text)
            log('CISCO-ATM-PVCTRAP-EXTN-CAPABILITY', 'patched',
                'AGENT-CAPABILITIES had {n} "::=" clauses (one per VARIATION). Commented them all out '
                'and put a single "::= {{ ciscoATMPVCTRAPExtnCapability 1 }}" at the end (judgment call)',
                n=len(hits))


# --------------------------------------------------------------------------
# 4. generic structural fixes
# --------------------------------------------------------------------------

def code_mask(text):
    """True for characters that are code (not comment); strings count as code."""
    mask = [True] * len(text)
    i, n, in_str = 0, len(text), False
    while i < n:
        ch = text[i]
        if in_str:
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True; i += 1; continue
        if text.startswith('--', i):
            j = i + 2
            while j < n and text[j] != '\n' and not text.startswith('--', j):
                j += 1
            end = j + 2 if text.startswith('--', j) else j
            for k in range(i, min(end, n)):
                mask[k] = False
            i = end
            continue
        i += 1
    return mask


def generic_fixes(outdir):
    for f in PROGRESS.each(sorted(os.listdir(outdir))):
        if not f.endswith('.my'):
            continue
        mod = f[:-3]
        p = os.path.join(outdir, f)
        text = read(p)
        orig = text

        # 4a. "SYNTAX BITS" with no named bits -> OCTET STRING (same wire encoding)
        def bare_bits(m):
            log(mod, 'patched',
                'SYNTAX of {name} is BITS with no named bits. BITS is encoded as OCTET STRING '
                'on the wire, so replaced with OCTET STRING (judgment call)', name=m.group(1))
            return m.group(0).replace('BITS', 'OCTET STRING', 1)
        text = re.sub(r'^([a-z][A-Za-z0-9-]*)\s+OBJECT-TYPE\s*\n\s*SYNTAX\s+BITS[ \t]*(?=\n\s*(?:MAX-ACCESS|ACCESS|UNITS))',
                      bare_bits, text, flags=re.M)

        # 4b. duplicate labels inside one enumeration / BITS list (code only, not comments)
        mask = code_mask(text)
        edits = []
        for blk in re.finditer(r'SYNTAX\s+(?:INTEGER|BITS)\s*\{([^}]*)\}', text):
            if not mask[blk.start()]:
                continue
            seen = {}
            for lm in re.finditer(r'\b([a-z][A-Za-z0-9-]*)\s*\(\s*(-?\d+)\s*\)', blk.group(1)):
                pos = blk.start(1) + lm.start()
                if not mask[pos]:
                    continue
                name, num = lm.group(1), lm.group(2)
                if name in seen:
                    new = f'{name}{num}'
                    edits.append((pos, pos + len(name), new))
                    log(mod, 'patched',
                        'Duplicate enum label "{name}" ({first} and {second}). Renamed the latter to "{new}"',
                        name=name, first=seen[name], second=num, new=new)
                else:
                    seen[name] = num
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]

        # 4c. same name defined twice: deprecated copy of a group -> comment it out
        tc = smiscan.strip_comments(text)
        names = re.findall(r'^([a-z][A-Za-z0-9-]*)\s+(?:OBJECT-GROUP|NOTIFICATION-GROUP)\b', tc, re.M)
        for name in sorted({n for n in names if names.count(n) > 1}):
            blocks = list(re.finditer(r'^' + re.escape(name) + r'\s+(?:OBJECT-GROUP|NOTIFICATION-GROUP)\b.*?::=\s*\{[^}]*\}',
                                      text, re.M | re.S))
            dep = [b for b in blocks if re.search(r'STATUS\s+deprecated', b.group(0))]
            if len(blocks) == 2 and len(dep) == 1:
                b = dep[0]
                commented = '\n'.join('-- ' + l for l in b.group(0).split('\n'))
                text = text[:b.start()] + '-- (duplicate definition commented out by fix script)\n' + commented + text[b.end():]
                log(mod, 'patched',
                    '{name} was defined twice with the same OID. Commented out the deprecated one '
                    'and kept the current one', name=name)

        # 4c2. trailing comma before a closing brace (code only, not comments)
        mask = code_mask(text)
        edits = []
        for tm in re.finditer(r'([A-Za-z0-9)-]+)(\s*),(\s*)\}', text):
            comma = tm.start(3) - 1
            brace = tm.end() - 1
            if mask[comma] and mask[brace] and all(mask[k] or text[k].isspace() for k in range(comma, brace)):
                edits.append((comma, comma + 1))
                log(mod, 'patched', 'Extra comma after "{name}", just before "}}"', name=tm.group(1))
        for a, b in sorted(edits, reverse=True):
            text = text[:a] + text[b:]

        # 4d. AGENT-CAPABILITIES statement with the same name as the MODULE-IDENTITY
        tc = smiscan.strip_comments(text)
        mi = re.search(r'^\s*([a-z][A-Za-z0-9-]*)\s+MODULE-IDENTITY\b', tc, re.M)
        if mi:
            name = mi.group(1)
            m2 = re.search(r'^(' + re.escape(name) + r')(\s+AGENT-CAPABILITIES\b)', text, re.M)
            if m2:
                text = text[:m2.start()] + name + 'Stmt' + m2.group(2) + text[m2.end():]
                log(mod, 'patched',
                    'The AGENT-CAPABILITIES statement had the same name as the MODULE-IDENTITY, "{name}". '
                    'Renamed the AGENT-CAPABILITIES one to "{name}Stmt" (OID unchanged)', name=name)

        if text != orig:
            write(p, text)


# --------------------------------------------------------------------------
# 5. add IMPORTS for symbols that are used but neither defined nor imported
# --------------------------------------------------------------------------

PREFERRED = {
    # well-known homes of commonly used symbols
    **{s: 'SNMPv2-SMI' for s in ('Integer32', 'Unsigned32', 'Counter32', 'Counter64', 'Gauge32',
                                 'TimeTicks', 'IpAddress', 'Opaque', 'enterprises', 'mib-2',
                                 'transmission', 'experimental')},
    **{s: 'SNMPv2-TC' for s in ('DisplayString', 'PhysAddress', 'MacAddress', 'TruthValue', 'TestAndIncr',
                                'AutonomousType', 'VariablePointer', 'RowPointer', 'RowStatus', 'TimeStamp',
                                'TimeInterval', 'DateAndTime', 'StorageType', 'TDomain', 'TAddress')},
    'SnmpAdminString': 'SNMP-FRAMEWORK-MIB',
    'InterfaceIndex': 'IF-MIB', 'InterfaceIndexOrZero': 'IF-MIB', 'ifIndex': 'IF-MIB',
    **{s: 'INET-ADDRESS-MIB' for s in ('InetAddress', 'InetAddressType', 'InetPortNumber',
                                       'InetAddressPrefixLength', 'InetVersion', 'InetZoneIndex')},
    'ciscoAgentCapability': 'CISCO-SMI', 'ciscoMgmt': 'CISCO-SMI', 'ciscoExperiment': 'CISCO-SMI',
    'Unsigned64': 'CISCO-TC',
    'AtmVcIdentifier': 'ATM-TC-MIB', 'AtmVpIdentifier': 'ATM-TC-MIB',
}


def insert_import(text, sym, mod):
    mask = code_mask(text)
    m = None
    for mm in re.finditer(r'\bIMPORTS\b', text):
        if mask[mm.start()]:
            m = mm
            break
    if not m:
        mi = re.search(r'DEFINITIONS\s*::=\s*BEGIN\s*\n', text)
        return text[:mi.end()] + f'\nIMPORTS\n        {sym}\n                FROM {mod};\n' + text[mi.end():]
    semi = next(i for i in range(m.end(), len(text)) if text[i] == ';' and mask[i])
    region = text[m.end():semi]
    for fm in re.finditer(r'\bFROM\s+' + re.escape(mod) + r'\b', region):
        pos = m.end() + fm.start()
        if not mask[pos]:
            continue
        k = pos - 1
        while k > m.end() and (text[k].isspace() or not mask[k]):
            k -= 1
        return text[:k + 1] + f', {sym}' + text[k + 1:]
    k = semi - 1
    while k > m.end() and (text[k].isspace() or not mask[k]):
        k -= 1
    return text[:k + 1] + f'\n        {sym}\n                FROM {mod}' + text[k + 1:]


def fix_imports(outdir):
    mods = {}
    for f in PROGRESS.each(sorted(os.listdir(outdir)), ' (reading)'):
        if f.endswith('.my'):
            info = smiscan.scan(read(os.path.join(outdir, f)))
            if info['module']:
                mods[info['module']] = info
    definers = {}
    for m, i in mods.items():
        for d in i['defs']:
            definers.setdefault(d, []).append(m)
    for name, info in sorted(mods.items()):
        known = info['defs'] | set(info['imports'])
        missing = sorted(r for r in info['refs'] if r not in known)
        if not missing:
            continue
        p = os.path.join(outdir, name + '.my')
        text = read(p)
        for sym in missing:
            cands = definers.get(sym, [])
            pick = PREFERRED.get(sym) if PREFERRED.get(sym) in mods else None
            if not pick:
                already = [c for c in cands if c in set(info['imports'].values())]
                plain = [c for c in cands if not c.endswith('CAPABILITY') and not c.endswith('-v1')]
                if len(cands) == 1:
                    pick = cands[0]
                elif len(already) == 1:
                    pick = already[0]
                elif len(plain) == 1:
                    pick = plain[0]
                elif len([c for c in plain if re.search(r'-TC(-MIB)?$', c)]) == 1:
                    pick = [c for c in plain if re.search(r'-TC(-MIB)?$', c)][0]
            if pick:
                text = insert_import(text, sym, pick)
                if len(cands) > 1:
                    log(name, 'import-added',
                        '{sym} is used but was not imported. Added "FROM {pick}" (also defined in: {others})',
                        sym=sym, pick=pick, others=', '.join(c for c in cands if c != pick))
                else:
                    log(name, 'import-added', '{sym} is used but was not imported. Added "FROM {pick}"',
                        sym=sym, pick=pick)
            else:
                log(name, 'import-unresolved',
                    '{sym} is used but not imported, and no single module to import it from was found. '
                    'Candidates: {cands}', sym=sym, cands=str(cands) if cands else Msg('none'))
        write(p, text)


# --------------------------------------------------------------------------
# 6. change log
# --------------------------------------------------------------------------

# kind, title
KIND_TITLES = [
    ('unresolved-dependency', 'Unresolved dependencies (modules not found)'),
    ('import-unresolved', 'Unresolved imports'),
    ('patch-not-applied', 'Fixes not applied'),
    ('duplicate-module', 'Duplicate module definitions (one kept)'),
    ('renamed', 'Renamed files'),
    ('added-dependency', 'Dependencies added from outside v2/'),
    ('added-old', 'OLD-CISCO-* modules added from v1/'),
    ('patched', 'Fixes to MIB text'),
    ('import-added', 'Added IMPORTS'),
    ('patch-skipped', 'Skipped fixes'),
]


def write_changes_md(path, ja=False):
    lines = [Msg('# Changes').render(ja), '',
             Msg('Every change fix_cisco_mibs.py made to the original cisco-mibs/v2.').render(ja),
             Msg('Items marked "judgment call" are fixes whose intent could not be determined '
                 'from the original MIB alone.').render(ja), '']
    for kind, title in KIND_TITLES:
        items = [c for c in CHANGES if c['kind'] == kind]
        if not items:
            continue
        lines += [Msg('## {title} ({n})', title=Msg(title), n=len(items)).render(ja), '']
        for c in sorted(items, key=lambda c: c['module']):
            lines.append(f"- **{c['module']}**: {c['detail_ja' if ja else 'detail']}")
        lines.append('')
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(lines))


def main():
    global PROGRESS
    ap = argparse.ArgumentParser(
        description="Turn Cisco's public MIBs (v2/) into a self-contained set that loads cleanly.")
    ap.add_argument('repo', metavar='CISCO_MIBS_REPO',
                    help='a clone of https://github.com/cisco/cisco-mibs (never modified)')
    ap.add_argument('outdir', metavar='OUT_DIR',
                    help='created by this script (aborts if it exists)')
    ap.add_argument('extra', nargs='*', metavar='EXTRA_MIB_DIR',
                    help="where to look for standard MIBs that v2/ imports but Cisco "
                         "does not ship, e.g. Net-SNMP's mibs/")
    ap.add_argument('-q', '--quiet', action='store_true',
                    help='do not show progress on stderr')
    args = ap.parse_args()
    repo, outdir, extra = args.repo, args.outdir, args.extra
    if not os.path.isdir(os.path.join(repo, 'v2')):
        sys.exit(f'{repo}/v2 not found. Give a clone of https://github.com/cisco/cisco-mibs')
    if os.path.exists(outdir):
        sys.exit(f'{outdir} already exists. Will not overwrite')
    mibdir = os.path.join(outdir, 'mibs')
    os.makedirs(mibdir)
    PROGRESS = Steps(8, quiet=args.quiet)
    PROGRESS.step('selecting modules from v2/')
    select_modules(os.path.join(repo, 'v2'), mibdir)
    PROGRESS.step('adding OLD-CISCO-* modules from v1/')
    add_old_cisco_modules(os.path.join(repo, 'v1'), mibdir)
    PROGRESS.step('adding missing dependencies')
    add_missing_dependencies(mibdir, [os.path.join(repo, 'v1')] + extra)
    PROGRESS.step('applying specific patches')
    specific_patches(mibdir)
    PROGRESS.step('applying generic fixes')
    generic_fixes(mibdir)
    PROGRESS.step('fixing IMPORTS')
    fix_imports(mibdir)
    PROGRESS.step('checking for unresolved dependencies')
    report_unresolved_dependencies(mibdir)
    PROGRESS.step('writing change logs')
    with open(os.path.join(outdir, 'changes.json'), 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(CHANGES, fh, indent=1, ensure_ascii=False)
    write_changes_md(os.path.join(outdir, 'CHANGES.md'))
    write_changes_md(os.path.join(outdir, 'CHANGES.ja.md'), ja=True)
    PROGRESS.clear()
    kinds = {}
    for c in CHANGES:
        kinds[c['kind']] = kinds.get(c['kind'], 0) + 1
    print(json.dumps(kinds, indent=1))


if __name__ == '__main__':
    main()
