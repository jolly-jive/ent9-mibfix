# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""Checks the steps of fix_cisco_mibs.py on small made-up MIBs.

Needs nothing outside the repository. Run: python3 -m unittest discover tests
"""
import filecmp
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
sys.path.insert(0, TOP)
import fix_cisco_mibs as fix  # noqa: E402
import smiscan  # noqa: E402


def imports_of(text):
    return smiscan.parse_imports(smiscan.clean(text))


def module(name, body='', lu=None):
    head = '%s DEFINITIONS ::= BEGIN\n' % name
    if lu:
        head += ('x MODULE-IDENTITY\n    LAST-UPDATED "%s"\n    ::= { iso 1 }\n' % lu)
    return head + body + 'END\n'


class TempDirTest(unittest.TestCase):
    """A fresh directory in self.dir and an empty change log for each test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        del fix.CHANGES[:]

    def put(self, rel, text):
        p = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='latin-1', newline='\n') as fh:
            fh.write(text)
        return p

    def get(self, rel):
        return smiscan.read(os.path.join(self.dir, rel))

    def kinds(self):
        return sorted((c['module'], c['kind']) for c in fix.CHANGES)


class HeaderInfoTest(unittest.TestCase):
    def test_four_digit_year(self):
        self.assertEqual(fix.header_info(module('A-MIB', lu='202001020304Z')),
                         ('A-MIB', '202001020304'))

    def test_two_digit_year(self):
        self.assertEqual(fix.header_info(module('A-MIB', lu='9901020304Z'))[1], '199901020304')
        self.assertEqual(fix.header_info(module('A-MIB', lu='0901020304Z'))[1], '200901020304')

    def test_commented_out_date(self):
        text = module('A-MIB', '-- LAST-UPDATED "203001010000Z"\n')
        self.assertEqual(fix.header_info(text), ('A-MIB', ''))


class CodeMaskTest(unittest.TestCase):
    CASES = [
        'a -- comment\nb',
        'a -- inline -- b',
        'a "string -- not a comment" b',
        'a -- "quote in a comment\nb "s"',
        'a "multi\nline -- string" -- c\nd',
        'a ---- b',
        'a -- unterminated',
        '"unterminated string -- x',
    ]

    def test_same_as_strip_comments(self):
        for text in self.CASES:
            with self.subTest(text):
                mask = fix.code_mask(text)
                code = ''.join(ch for ch, m in zip(text, mask) if m)
                self.assertEqual(code, smiscan.strip_comments(text))


IMPORTS_TEXT = '''X-MIB DEFINITIONS ::= BEGIN
-- IMPORTS in a comment; FROM SNMPv2-TC
IMPORTS
        DisplayString
                FROM SNMPv2-TC
        OBJECT-TYPE
                FROM SNMPv2-SMI  -- was FROM IF-MIB
        ;
END
'''


class InsertImportTest(unittest.TestCase):
    def test_existing_module(self):
        text = fix.insert_import(IMPORTS_TEXT, 'TruthValue', 'SNMPv2-TC')
        self.assertIn('DisplayString, TruthValue\n', text)
        self.assertEqual(imports_of(text), {'DisplayString': 'SNMPv2-TC', 'TruthValue': 'SNMPv2-TC',
                                            'OBJECT-TYPE': 'SNMPv2-SMI'})
        self.assertIn('-- IMPORTS in a comment; FROM SNMPv2-TC\n', text)

    def test_new_module(self):
        text = fix.insert_import(IMPORTS_TEXT, 'ifIndex', 'IF-MIB')
        self.assertEqual(imports_of(text)['ifIndex'], 'IF-MIB')
        self.assertIn('-- was FROM IF-MIB', text)
        self.assertEqual(text.replace('\n        ifIndex\n                FROM IF-MIB', ''),
                         IMPORTS_TEXT)

    def test_no_imports(self):
        text = fix.insert_import(module('Y-MIB', 'y OBJECT IDENTIFIER ::= { iso 1 }\n'),
                                 'Integer32', 'SNMPv2-SMI')
        self.assertEqual(imports_of(text), {'Integer32': 'SNMPv2-SMI'})


# patch() logs its description, so it must be one that has a Japanese version
DESC = 'Typo in a SEQUENCE OF type name (Boradcast)'


class PatchTest(TempDirTest):
    def test_applied(self):
        self.put('A-MIB.my', 'x x x')
        fix.patch(self.dir, 'A-MIB', 'x', 'y', DESC)
        self.assertEqual(self.get('A-MIB.my'), 'y x x')
        self.assertEqual(self.kinds(), [('A-MIB', 'patched')])
        self.assertEqual(fix.CHANGES[0]['detail'], DESC)

    def test_count_zero_replaces_all(self):
        self.put('A-MIB.my', 'x x x')
        fix.patch(self.dir, 'A-MIB', 'x', 'y', DESC, count=0)
        self.assertEqual(self.get('A-MIB.my'), 'y y y')
        self.put('B-MIB.my', 'x x x')
        fix.patch(self.dir, 'B-MIB', r'(x)', r'\1z', DESC, count=0, regex=True)
        self.assertEqual(self.get('B-MIB.my'), 'xz xz xz')

    def test_regex_once(self):
        self.put('A-MIB.my', 'x1 x2')
        fix.patch(self.dir, 'A-MIB', r'x(\d)', r'y\1', DESC, regex=True)
        self.assertEqual(self.get('A-MIB.my'), 'y1 x2')

    def test_not_applied_and_skipped(self):
        self.put('A-MIB.my', 'abc')
        fix.patch(self.dir, 'A-MIB', 'x', 'y', DESC)
        fix.patch(self.dir, 'NO-MIB', 'x', 'y', DESC)
        self.assertEqual(self.get('A-MIB.my'), 'abc')
        self.assertEqual(self.kinds(), [('A-MIB', 'patch-not-applied'), ('NO-MIB', 'patch-skipped')])


GENERIC_TEXT = '''TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
        MODULE-IDENTITY, OBJECT-TYPE, enterprises
                FROM SNMPv2-SMI
        OBJECT-GROUP, AGENT-CAPABILITIES
                FROM SNMPv2-CONF;

testMIB MODULE-IDENTITY
    LAST-UPDATED "202001010000Z"
    ORGANIZATION ""
    CONTACT-INFO ""
    DESCRIPTION ""
    ::= { enterprises 99999 }

testBits OBJECT-TYPE
    SYNTAX BITS
    MAX-ACCESS read-only
    STATUS current
    DESCRIPTION "x"
    ::= { testMIB 1 }

testState OBJECT-TYPE
    SYNTAX INTEGER { up(1), down(2), up(3) }
    MAX-ACCESS read-only
    STATUS current
    DESCRIPTION "x"
    -- SYNTAX INTEGER { a(1), a(2) }  OBJECTS { a, }
    INDEX { testBits, testState, }
    ::= { testMIB 2 }

testGroup OBJECT-GROUP
    OBJECTS { testBits }
    STATUS deprecated
    DESCRIPTION "old"
    ::= { testMIB 3 }

testGroup OBJECT-GROUP
    OBJECTS { testBits, testState }
    STATUS current
    DESCRIPTION "new"
    ::= { testMIB 3 }

testMIB AGENT-CAPABILITIES
    PRODUCT-RELEASE "1"
    STATUS current
    DESCRIPTION "x"
    ::= { testMIB 4 }
END
'''


class GenericFixesTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.put('TEST-MIB.my', GENERIC_TEXT)
        self.put('CLEAN-MIB.my', module('CLEAN-MIB'))
        fix.generic_fixes(self.dir)
        self.text = self.get('TEST-MIB.my')

    def test_bare_bits(self):
        self.assertIn('testBits OBJECT-TYPE\n    SYNTAX OCTET STRING\n', self.text)

    def test_duplicate_enum_label(self):
        self.assertIn('{ up(1), down(2), up3(3) }', self.text)
        self.assertIn('-- SYNTAX INTEGER { a(1), a(2) }', self.text)

    def test_deprecated_duplicate_group(self):
        self.assertIn('-- testGroup OBJECT-GROUP\n--     OBJECTS { testBits }\n--     STATUS deprecated',
                      self.text)
        self.assertEqual(self.text.count('\ntestGroup OBJECT-GROUP'), 1)

    def test_trailing_comma(self):
        self.assertIn('INDEX { testBits, testState }', self.text)
        self.assertIn('OBJECTS { a, }', self.text)

    def test_capabilities_named_like_module_identity(self):
        self.assertIn('\ntestMIBStmt AGENT-CAPABILITIES', self.text)
        self.assertIn('\ntestMIB MODULE-IDENTITY', self.text)

    def test_log_and_untouched_files(self):
        self.assertEqual(self.kinds(), [('TEST-MIB', 'patched')] * 5)
        self.assertEqual(self.get('CLEAN-MIB.my'), module('CLEAN-MIB'))


class SelectModulesTest(TempDirTest):
    def test_select(self):
        new = module('A-MIB', lu='202001010000Z')
        self.put('v2/A-MIB.my', new)
        self.put('v2/A-MIB-old.my', module('A-MIB', lu='201901010000Z'))
        self.put('v2/B-MIB.txt', module('B-MIB'))
        self.put('v2/weird.my', module('C-MIB'))
        self.put('v2/README', module('D-MIB'))
        os.mkdir(os.path.join(self.dir, 'out'))
        fix.select_modules(os.path.join(self.dir, 'v2'), os.path.join(self.dir, 'out'))
        self.assertEqual(sorted(os.listdir(os.path.join(self.dir, 'out'))),
                         ['A-MIB.my', 'B-MIB.my', 'C-MIB.my'])
        self.assertEqual(self.get('out/A-MIB.my'), new)
        self.assertEqual(self.kinds(), [('A-MIB', 'duplicate-module'),
                                        ('B-MIB', 'renamed'), ('C-MIB', 'renamed')])
        self.assertIn('Kept A-MIB.my (202001010000)', fix.CHANGES[0]['detail'])


class DependenciesTest(TempDirTest):
    def test_add_and_report(self):
        self.put('out/A-MIB.my', module('A-MIB', 'IMPORTS b FROM B-MIB;\n'))
        b1 = self.put('s1/B-MIB.txt', module('B-MIB', 'IMPORTS c FROM C-MIB;\n'))
        self.put('s2/B-MIB.my', module('B-MIB', 'IMPORTS c FROM D-MIB;\n', lu='203001010000Z'))
        out = os.path.join(self.dir, 'out')
        fix.add_missing_dependencies(out, [os.path.join(self.dir, 's1'), os.path.join(self.dir, 's2')])
        fix.report_unresolved_dependencies(out)
        # the first directory wins, even over a newer copy
        self.assertEqual(self.get('out/B-MIB.my'), smiscan.read(b1))
        self.assertEqual(self.kinds(), [('B-MIB', 'added-dependency'), ('C-MIB', 'unresolved-dependency')])
        self.assertIn('Added from s1/B-MIB.txt', fix.CHANGES[0]['detail'])
        self.assertEqual(fix.CHANGES[1]['detail'], 'Imported by B-MIB, but not found')


class FixImportsTest(TempDirTest):
    def test_fix_imports(self):
        self.put('SNMPv2-SMI.my', module('SNMPv2-SMI',
                                         'enterprises OBJECT IDENTIFIER ::= { iso 3 6 1 4 1 }\n'
                                         'Integer32 ::= INTEGER (-2147483648..2147483647)\n'))
        self.put('X-TC-MIB.my', module('X-TC-MIB', 'FooType ::= INTEGER\n'))
        self.put('Y-MIB.my', module('Y-MIB', 'FooType ::= INTEGER\n'))
        self.put('A-MIB.my', module('A-MIB',
                                    'IMPORTS OBJECT-TYPE FROM SNMPv2-SMI;\n'
                                    'aRoot OBJECT IDENTIFIER ::= { enterprises 99999 }\n'
                                    'aValue OBJECT-TYPE\n    SYNTAX Integer32\n    ::= { aRoot 1 }\n'
                                    'aFoo OBJECT-TYPE\n    SYNTAX FooType\n    ::= { aRoot 2 }\n'
                                    'aOther OBJECT-TYPE\n    SYNTAX NoSuchType\n    ::= { aRoot 3 }\n'))
        fix.fix_imports(self.dir)
        self.assertEqual(imports_of(self.get('A-MIB.my')), {
            'OBJECT-TYPE': 'SNMPv2-SMI', 'Integer32': 'SNMPv2-SMI', 'enterprises': 'SNMPv2-SMI',
            'FooType': 'X-TC-MIB'})
        self.assertEqual(self.kinds(), [('A-MIB', 'import-added')] * 3 + [('A-MIB', 'import-unresolved')])
        details = [c['detail'] for c in fix.CHANGES]
        self.assertIn('FooType is used but was not imported. Added "FROM X-TC-MIB" '
                      '(also defined in: Y-MIB)', details)


class RunTest(TempDirTest):
    """The whole script on a tiny cisco-mibs look-alike."""

    def setUp(self):
        super().setUp()
        self.put('repo/v2/A-MIB.my', module('A-MIB', 'IMPORTS enterprises FROM SNMPv2-SMI;\n'
                                                     'aRoot OBJECT IDENTIFIER ::= { enterprises 1 }\n'))
        self.put('repo/v1/OLD-CISCO-X-MIB.my', module('OLD-CISCO-X-MIB'))
        self.put('repo/v1/OTHER-MIB.my', module('OTHER-MIB'))
        self.put('repo/v1/SNMPv2-SMI.my', module('SNMPv2-SMI',
                                                 'enterprises OBJECT IDENTIFIER ::= { iso 3 6 1 4 1 }\n'))
        self.put('repo/v1/CISCO-GENERAL-TRAPS.my', module('CISCOTRAP-MIB',
                                                          'coldStart TRAP-TYPE\n    ENTERPRISE snmp\n'
                                                          '    DESCRIPTION "x"\n    ::= 0\n\n'
                                                          'reload TRAP-TYPE\n    ENTERPRISE cisco\n'
                                                          '    DESCRIPTION "y"\n    ::= 0\n'))
        self.repo = os.path.join(self.dir, 'repo')

    def test_run(self):
        out = os.path.join(self.dir, 'out')
        changes = fix.run(self.repo, out)
        self.assertEqual(sorted(os.listdir(os.path.join(out, 'mibs'))),
                         ['A-MIB.my', 'CISCOTRAP-MIB.my', 'OLD-CISCO-X-MIB.my', 'SNMPv2-SMI.my'])
        kinds = sorted({(c['module'], c['kind']) for c in changes if c['kind'] != 'patch-skipped'})
        self.assertEqual(kinds, [('CISCOTRAP-MIB', 'added-old'), ('CISCOTRAP-MIB', 'patched'),
                                 ('OLD-CISCO-X-MIB', 'added-old'), ('SNMPv2-SMI', 'added-dependency')])
        trap = self.get('out/mibs/CISCOTRAP-MIB.my')
        self.assertIn('-- coldStart TRAP-TYPE\n--     ENTERPRISE snmp', trap)
        self.assertIn('\nreload TRAP-TYPE\n    ENTERPRISE cisco', trap)
        with open(os.path.join(out, 'CHANGES.ja.md'), encoding='utf-8') as fh:
            self.assertIn('## v1 から追加した古いモジュール（2 件）', fh.read())

    def test_same_output_twice(self):
        a, b = os.path.join(self.dir, 'a'), os.path.join(self.dir, 'b')
        first = fix.run(self.repo, a)
        second = fix.run(self.repo, b)
        self.assertEqual(first, second)  # the log does not pile up across runs
        cmp = filecmp.dircmp(a, b)
        self.assertEqual(cmp.diff_files, [])
        self.assertEqual(filecmp.dircmp(os.path.join(a, 'mibs'), os.path.join(b, 'mibs')).diff_files, [])


if __name__ == '__main__':
    unittest.main()
