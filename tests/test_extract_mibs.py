# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""Checks extract_mibs.py against real walks with --verify's code.

Needs OUT_DIR/mibs from fix_cisco_mibs.py at out/mibs, walks in samples/
(see below) and snmptranslate. Skips when any of them is missing.

samples/*.md: one file per device, with the snmpwalk -On output in the first
```text block after a line containing "with -On".

Run: python3 -m unittest discover tests
"""
import codecs
import glob
import io
import os
import shutil
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
sys.path.insert(0, TOP)
import extract_mibs  # noqa: E402

MIBDIR = os.path.join(TOP, 'out', 'mibs')
SAMPLES = sorted(glob.glob(os.path.join(TOP, 'samples', '*.md')))
PREFIXES = [extract_mibs.parse_prefix(p) for p in extract_mibs.DEFAULT_PREFIXES]


def walk_text(md):
    """The snmpwalk -On block of a samples/*.md file."""
    lines, state = [], 0
    with open(md, encoding='utf-8') as fh:
        for line in fh:
            if state == 0 and 'with -On' in line:
                state = 1
            elif state == 1 and line.startswith('```text'):
                state = 2
            elif state == 2 and line.startswith('```'):
                break
            elif state == 2:
                lines.append(line)
    return ''.join(lines)


@unittest.skipUnless(os.path.isdir(MIBDIR) and SAMPLES and shutil.which('snmptranslate'),
                     'needs out/mibs, samples/*.md and snmptranslate')
class VerifyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        proc = extract_mibs.start_tree([MIBDIR], ['ALL'])
        cls.mods = extract_mibs.load_modules([MIBDIR])
        cls.index = extract_mibs.OidIndex(cls.mods)
        cls.reference = extract_mibs.finish_tree(proc)

    def extract(self, md):
        oids, _ = extract_mibs.read_walk(io.StringIO(walk_text(md)))
        targets = sorted({o for o in oids if any(o[:len(p)] == p for p in PREFIXES)})
        direct, unresolved = extract_mibs.extract(self.index, targets)
        needed, _, _ = extract_mibs.dependencies(self.mods, direct, set())
        return targets, unresolved, needed

    def verify(self, targets, unresolved, needed):
        files = sorted(self.mods[m]['path'] for m in needed)
        return extract_mibs.verify(files, needed, targets, unresolved, [], self.reference)

    def test_samples_have_no_gaps(self):
        for md in SAMPLES:
            with self.subTest(os.path.basename(md)):
                gaps, warnings, _ = self.verify(*self.extract(md))
                self.assertEqual(gaps, {})
                self.assertEqual(warnings, [])

    def test_missing_module_is_found(self):
        for md in SAMPLES:
            targets, unresolved, needed = self.extract(md)
            if 'CISCO-ENVMON-MIB' in needed:
                break
        else:
            self.skipTest('no sample uses CISCO-ENVMON-MIB')
        gaps, warnings, _ = self.verify(targets, unresolved, needed - {'CISCO-ENVMON-MIB'})
        self.assertIn('ciscoEnvMonFanState', {want for want, _ in gaps})
        self.assertTrue(any('CISCO-ENVMON-MIB' in w for w in warnings))

    def test_index_miss_is_found(self):
        # pretend our index knew only the first 7 arcs of an object it found
        for md in SAMPLES:
            targets, unresolved, needed = self.extract(md)
            if needed:
                break
        else:
            self.skipTest('no sample has a known OID')
        # an object only one module defines, so dropping that module leaves a gap
        oid = next(o for o in targets
                   if o not in unresolved and len(self.index.match(o)[1]) == 1)
        owner = self.index.match(oid)[1][0][0]
        gaps, _, _ = self.verify([oid], {oid: 7}, needed - {owner})
        self.assertEqual(sum(gaps.values()), 1)


class InputTest(unittest.TestCase):
    WALK = ('.1.3.6.1.4.1.9.2.1.1.0 = STRING: "x"\r\n'
            '1.3.6.1.4.1.9.9.13.1.3.1.3.1 = Hex-STRING: 00 01\r\n'
            '02 03\r\n'
            'SNMPv2-SMI::enterprises.9.1 = INTEGER: 1\r\n')
    WANT = ([(1, 3, 6, 1, 4, 1, 9, 2, 1, 1, 0),
             (1, 3, 6, 1, 4, 1, 9, 9, 13, 1, 3, 1, 3, 1)], 1)

    def check(self, data):
        self.assertEqual(extract_mibs.read_walk(
            io.StringIO(extract_mibs.decode_input(data), newline=None)), self.WANT)

    def test_plain(self):
        self.check(self.WALK.encode('ascii'))

    def test_utf8_bom(self):
        self.check(self.WALK.encode('utf-8-sig'))

    def test_utf16_bom(self):
        # what Windows PowerShell 5.1 writes for "snmpwalk ... > walk.txt"
        self.check(self.WALK.encode('utf-16'))
        self.check(codecs.BOM_UTF16_BE + self.WALK.encode('utf-16-be'))


def fake_mods(imports):
    """{module: [imported modules]} -> the shape load_modules returns."""
    return {m: {'imports': {'%s-%d' % (d, i): d for i, d in enumerate(deps)}, 'path': m}
            for m, deps in imports.items()}


class LoadOrderTest(unittest.TestCase):
    def test_imports_first_ties_by_name(self):
        mods = fake_mods({'SMI': [], 'TC': ['SMI'], 'B-MIB': ['TC', 'SMI'],
                          'A-MIB': ['SMI', 'B-MIB'], 'C-MIB': ['SMI']})
        self.assertEqual(extract_mibs.load_order(mods, set(mods)),
                         (['SMI', 'C-MIB', 'TC', 'B-MIB', 'A-MIB'], []))

    def test_only_needed_modules(self):
        mods = fake_mods({'SMI': [], 'TC': ['SMI'], 'A-MIB': ['TC', 'SMI']})
        self.assertEqual(extract_mibs.load_order(mods, {'A-MIB', 'TC'}),
                         (['TC', 'A-MIB'], []))

    def test_cycle_kept_together(self):
        mods = fake_mods({'SMI': [], 'Y': ['SMI', 'X'], 'X': ['SMI', 'Y'],
                          'A': ['SMI'], 'Z': ['X']})
        self.assertEqual(extract_mibs.load_order(mods, set(mods)),
                         (['SMI', 'A', 'X', 'Y', 'Z'], [['X', 'Y']]))

    @unittest.skipUnless(os.path.isdir(MIBDIR), 'needs out/mibs')
    def test_all_mibs(self):
        mods = extract_mibs.load_modules([MIBDIR])
        order, cycles = extract_mibs.load_order(mods, set(mods))
        self.assertEqual(sorted(order), sorted(mods))
        self.assertEqual(cycles, [['CISCO-LWAPP-AP-MIB', 'CISCO-LWAPP-DOT11-MIB']])
        in_cycle = {m for g in cycles for m in g}
        pos = {m: i for i, m in enumerate(order)}
        for m in order:
            for d in set(mods[m]['imports'].values()):
                if d in pos and not (m in in_cycle and d in in_cycle):
                    self.assertLess(pos[d], pos[m], '%s imports %s' % (m, d))


if __name__ == '__main__':
    unittest.main()
