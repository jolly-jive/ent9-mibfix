# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""Runs extract_mibs.py and lookup_mib.py as commands on small made-up MIBs.

Checks what users see: the files or matches on stdout, the summary and
warnings on stderr, and the exit status. Needs nothing outside the
repository (--verify itself is checked in test_extract_mibs.py, with
snmptranslate). Run: python3 -m unittest discover tests
"""
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

TOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MIBS = {
    'SNMPv2-SMI': '''SNMPv2-SMI DEFINITIONS ::= BEGIN
enterprises OBJECT IDENTIFIER ::= { iso 3 6 1 4 1 }
END
''',
    'CISCO-SMI': '''CISCO-SMI DEFINITIONS ::= BEGIN
IMPORTS enterprises FROM SNMPv2-SMI;
cisco OBJECT IDENTIFIER ::= { enterprises 9 }
END
''',
    # imports from SNMPv2-TC, which is not in the directory
    'X-TC-MIB': '''X-TC-MIB DEFINITIONS ::= BEGIN
IMPORTS TEXTUAL-CONVENTION FROM SNMPv2-TC;
XState ::= TEXTUAL-CONVENTION
    STATUS current
    DESCRIPTION "x"
    SYNTAX INTEGER { up(1), down(2) }
END
''',
    'X-OBJ-MIB': '''X-OBJ-MIB DEFINITIONS ::= BEGIN
IMPORTS OBJECT-TYPE FROM SNMPv2-SMI
        cisco FROM CISCO-SMI
        XState FROM X-TC-MIB;
xRoot OBJECT IDENTIFIER ::= { cisco 99 }
xState OBJECT-TYPE
    SYNTAX XState
    MAX-ACCESS read-only
    STATUS current
    DESCRIPTION "The state."
    ::= { xRoot 1 }
xName OBJECT-TYPE
    SYNTAX OCTET STRING
    MAX-ACCESS read-only
    STATUS current
    DESCRIPTION "The name."
    ::= { xRoot 2 }
END
''',
    # defines no walked object, but a notification that carries one
    'X-TRAP-MIB': '''X-TRAP-MIB DEFINITIONS ::= BEGIN
IMPORTS NOTIFICATION-TYPE FROM SNMPv2-SMI
        cisco FROM CISCO-SMI
        xState FROM X-OBJ-MIB;
xTraps OBJECT IDENTIFIER ::= { cisco 98 }
xStateChange NOTIFICATION-TYPE
    OBJECTS { xState }
    STATUS current
    DESCRIPTION "x"
    ::= { xTraps 0 1 }
END
''',
    # unrelated to the walk; defines a second xName
    'X-OTHER-MIB': '''X-OTHER-MIB DEFINITIONS ::= BEGIN
IMPORTS OBJECT-TYPE FROM SNMPv2-SMI
        cisco FROM CISCO-SMI;
xName OBJECT-TYPE
    SYNTAX OCTET STRING
    MAX-ACCESS read-only
    STATUS current
    DESCRIPTION "Another name."
    ::= { cisco 50 1 }
END
''',
}

WALK = '''.1.3.6.1.2.1.1.1.0 = STRING: "outside the default prefixes"
.1.3.6.1.4.1.9.99.1.0 = INTEGER: up(1)
.1.3.6.1.4.1.9.99.2.0 = Hex-STRING: 00 01
02 03
.1.3.6.1.4.1.9.77.1.0 = INTEGER: 5
SNMPv2-SMI::enterprises.9.1 = INTEGER: 1
'''


class CliTest(unittest.TestCase):
    """A MIB directory, an --exclude-dir with SNMPv2-SMI, and a private cache."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.mibs = os.path.join(self.tmp, 'mibs')
        self.system = os.path.join(self.tmp, 'system')
        os.mkdir(self.mibs)
        os.mkdir(self.system)
        for name, text in MIBS.items():
            with open(os.path.join(self.mibs, name + '.my'), 'w', newline='\n') as fh:
                fh.write(text)
        with open(os.path.join(self.system, 'SNMPv2-SMI.txt'), 'w', newline='\n') as fh:
            fh.write(MIBS['SNMPv2-SMI'])
        # keep the user's cache out of it
        self.env = dict(os.environ, XDG_CACHE_HOME=os.path.join(self.tmp, 'cache'))

    def path(self, *names):
        return [os.path.join(self.mibs, n + '.my') for n in names]

    def run_tool(self, tool, *args, stdin='', env=None):
        proc = subprocess.run([sys.executable, os.path.join(TOP, tool), '-q'] + list(args),
                              input=stdin.encode('utf-8'), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env or self.env)
        return (proc.returncode, proc.stdout.decode('utf-8').splitlines(),
                proc.stderr.decode('utf-8'))


class ExtractTest(CliTest):
    def extract(self, *args, **kw):
        kw.setdefault('stdin', WALK)
        return self.run_tool('extract_mibs.py', self.mibs, *args, **kw)

    def test_files_and_summary(self):
        code, out, err = self.extract()
        self.assertEqual(code, 0, err)
        self.assertEqual(out, self.path('CISCO-SMI', 'SNMPv2-SMI', 'X-OBJ-MIB', 'X-TC-MIB',
                                        'X-TRAP-MIB'))
        self.assertIn('warning: 1 lines have non-numeric OIDs and were ignored', err)
        self.assertIn('4 OIDs read, 3 under 1.3.6.1.4.1.9, 1.3.6.1.4.1.14179', err)
        self.assertIn('1 modules define them; 1 more have notifications that carry them; '
                      '5 files in total with imports', err)
        self.assertIn('warning: imported modules not found: SNMPv2-TC', err)
        self.assertIn('warning: 1 OIDs not defined by any MIB (count by subtree):\n'
                      '       1  cisco.77', err)

    def test_no_notifications(self):
        code, out, _ = self.extract('--no-notifications')
        self.assertEqual(code, 0)
        self.assertNotIn(self.path('X-TRAP-MIB')[0], out)

    def test_load_order(self):
        code, out, _ = self.extract('--load-order')
        self.assertEqual(code, 0)
        self.assertEqual(out, self.path('SNMPv2-SMI', 'CISCO-SMI', 'X-TC-MIB', 'X-OBJ-MIB',
                                        'X-TRAP-MIB'))

    def test_exclude_dir(self):
        code, out, err = self.extract('--exclude-dir', self.system)
        self.assertEqual(code, 0)
        self.assertNotIn(self.path('SNMPv2-SMI')[0], out)
        self.assertEqual(len(out), 4)
        self.assertIn('left out (already in --exclude-dir): SNMPv2-SMI', err)

    def test_prefix(self):
        code, out, err = self.extract('--prefix', '.1.3.6.1.4.1.9.99')
        self.assertEqual(code, 0)
        self.assertIn('2 under 1.3.6.1.4.1.9.99', err)
        self.assertNotIn('not defined by any MIB', err)

    def test_input_file_utf16(self):
        # what Windows PowerShell 5.1 writes for "snmpwalk ... > walk.txt"
        walk = os.path.join(self.tmp, 'walk.txt')
        with open(walk, 'wb') as fh:
            fh.write(WALK.replace('\n', '\r\n').encode('utf-16'))
        code, out, _ = self.extract('--input', walk, stdin='')
        self.assertEqual((code, out), (0, self.extract()[1]))

    def test_archives(self):
        for name in ('set.zip', 'set.tar.gz', 'set.tgz', 'set.tar'):
            with self.subTest(name):
                archive = os.path.join(self.tmp, name)
                code, out, _ = self.extract('--archive', archive)
                self.assertEqual(code, 0)
                want = ['set/' + os.path.basename(p) for p in out]
                if name.endswith('.zip'):
                    with zipfile.ZipFile(archive) as z:
                        self.assertEqual(z.namelist(), want)
                else:
                    with tarfile.open(archive) as t:
                        self.assertEqual(t.getnames(), want)

    def test_errors(self):
        cases = [
            (('--archive', 'set.rar'), WALK, 'error: --archive must end in .zip, .tar.gz, .tgz or .tar'),
            (('--input', os.path.join(self.tmp, 'none.txt')), '', 'error: no such file: '),
            ((), 'SNMPv2-SMI::enterprises.9.1 = INTEGER: 1\n',
             'error: no numeric OIDs in the input; run snmpwalk with -On'),
            ((os.path.join(self.tmp, 'nodir'),), WALK, 'error: not a directory: '),
        ]
        for args, stdin, message in cases:
            with self.subTest(message):
                code, out, err = self.extract(*args, stdin=stdin)
                self.assertEqual((code, out), (1, []))
                self.assertIn(message, err)

    def test_verify_needs_snmptranslate(self):
        env = dict(self.env, PATH=os.path.join(self.tmp, 'empty'))
        code, out, err = self.extract('--verify', env=env)
        self.assertEqual((code, out), (1, []))
        self.assertIn('error: --verify needs snmptranslate (Net-SNMP) in PATH', err)


class LookupTest(CliTest):
    def lookup(self, *args, **kw):
        return self.run_tool('lookup_mib.py', self.mibs, *args, **kw)

    def line(self, oid, name, kind, mod):
        return '\t'.join([oid, name, kind, self.path(mod)[0]])

    def test_queries(self):
        code, out, err = self.lookup('.1.3.6.1.4.1.9.99.1.0', 'xName', 'X-TRAP-MIB::xState',
                                     'cisco.99', 'X-OBJ-MIB::xStateChange')
        self.assertEqual(code, 1)  # the last one is not visible from X-OBJ-MIB
        self.assertEqual(out, [
            self.line('1.3.6.1.4.1.9.99.1.0', 'X-OBJ-MIB::xState.0', 'OBJECT-TYPE', 'X-OBJ-MIB'),
            # a name two modules define: one line each, by OID
            self.line('1.3.6.1.4.1.9.50.1', 'X-OTHER-MIB::xName', 'OBJECT-TYPE', 'X-OTHER-MIB'),
            self.line('1.3.6.1.4.1.9.99.2', 'X-OBJ-MIB::xName', 'OBJECT-TYPE', 'X-OBJ-MIB'),
            # imported into X-TRAP-MIB, defined in X-OBJ-MIB
            self.line('1.3.6.1.4.1.9.99.1', 'X-OBJ-MIB::xState', 'OBJECT-TYPE', 'X-OBJ-MIB'),
            self.line('1.3.6.1.4.1.9.99', 'X-OBJ-MIB::xRoot', 'OBJECT IDENTIFIER', 'X-OBJ-MIB'),
        ])
        self.assertEqual(err, 'not found: X-OBJ-MIB::xStateChange\n')

    def test_stdin_and_input_file(self):
        queries = '# a comment\n\n.1.3.6.1.4.1.9.99.2.0 = STRING: "x"\nxStateChange\n'
        want = [self.line('1.3.6.1.4.1.9.99.2.0', 'X-OBJ-MIB::xName.0', 'OBJECT-TYPE', 'X-OBJ-MIB'),
                self.line('1.3.6.1.4.1.9.98.0.1', 'X-TRAP-MIB::xStateChange', 'NOTIFICATION-TYPE',
                          'X-TRAP-MIB')]
        self.assertEqual(self.lookup(stdin=queries), (0, want, ''))
        path = os.path.join(self.tmp, 'queries.txt')
        with open(path, 'w') as fh:
            fh.write(queries)
        self.assertEqual(self.lookup('--input', path), (0, want, ''))

    def test_deps(self):
        code, out, err = self.lookup('xState', '--deps')
        self.assertEqual(code, 0)
        self.assertEqual(out, self.path('CISCO-SMI', 'SNMPv2-SMI', 'X-OBJ-MIB', 'X-TC-MIB'))
        self.assertIn('warning: imported modules not found: SNMPv2-TC', err)
        code, out, err = self.lookup('xState', '--deps', '--load-order',
                                     '--exclude-dir', self.system)
        self.assertEqual(out, self.path('CISCO-SMI', 'X-TC-MIB', 'X-OBJ-MIB'))
        self.assertIn('left out (already in --exclude-dir): SNMPv2-SMI', err)

    def test_detail(self):
        code, out, _ = self.lookup('xState', '--detail')
        self.assertEqual(code, 0)
        self.assertEqual(out[1:], ['    xState OBJECT-TYPE',
                                   '        SYNTAX XState',
                                   '        MAX-ACCESS read-only',
                                   '        STATUS current',
                                   '        DESCRIPTION "The state."',
                                   '        ::= { xRoot 1 }',
                                   ''])

    def test_errors(self):
        cases = [
            (('xState', '--exclude-dir', self.system), 'error: --exclude-dir needs --deps'),
            (('xState', '--load-order'), 'error: --load-order needs --deps'),
            (('xState', '--input', 'q.txt'), 'error: give QUERY arguments or --input, not both'),
            (('xState', '--deps', '--detail'), 'not allowed with argument'),
        ]
        for args, message in cases:
            with self.subTest(message):
                code, out, err = self.lookup(*args)
                self.assertNotEqual(code, 0)
                self.assertEqual(out, [])
                self.assertIn(message, err)
        code, _, err = self.run_tool('lookup_mib.py', 'xState', self.mibs)
        self.assertEqual(code, 1)
        self.assertIn('error: the first argument must be a MIB directory: xState', err)


if __name__ == '__main__':
    unittest.main()
