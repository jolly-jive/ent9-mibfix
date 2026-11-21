# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""Tests for tools/check_upstream.py that need no network: the UPSTREAM file,
the kind of an upstream change, and the report. Also checks that the README
names the cisco-mibs commit in UPSTREAM. Run: python3 -m unittest discover tests
"""
import os
import re
import sys
import tempfile
import unittest

TOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TOP, 'tools'))
import check_upstream as cu  # noqa: E402

OLD = 'a' * 40
NEW = 'b' * 40


def info(**kw):
    d = {'old': OLD, 'new': NEW, 'url': 'https://github.com/cisco/cisco-mibs',
         'old_date': '2026-09-29', 'new_date': '2026-10-30',
         'commits': ['bbbbbbb 2026-10-30 cana-oct'],
         'changed': ['M\tv2/CISCO-PRODUCTS-MIB.my'], 'kind': 'cana',
         'fix_old': (0, {'patched': 36}, ['warning: Unresolved dependencies (1): DOCS-PNM-MIB']),
         'fix_new': (0, {'patched': 36}, ['warning: Unresolved dependencies (1): DOCS-PNM-MIB']),
         'output': ([], [], ['mibs/CISCO-PRODUCTS-MIB.my'])}
    d.update(kw)
    return d


class ReadUpstreamTest(unittest.TestCase):
    def write(self, text):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, 'w') as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_repository_file(self):
        pins = cu.read_upstream()
        self.assertEqual(set(pins), {'cisco-mibs', 'net-snmp', 'librenms'})
        for commit, url in pins.values():
            self.assertRegex(commit, '^[0-9a-f]{40}$')
            self.assertTrue(url.startswith('https://github.com/'))

    def test_comments_and_errors(self):
        lines = ''.join('%s %s https://x/%s  # note\n' % (n, OLD, n)
                        for n in ('cisco-mibs', 'net-snmp', 'librenms'))
        self.assertEqual(cu.read_upstream(self.write('# head\n\n' + lines))['net-snmp'],
                         (OLD, 'https://x/net-snmp'))
        with self.assertRaises(cu.Error):
            cu.read_upstream(self.write('cisco-mibs c9ab98c https://x\n'))  # short commit
        with self.assertRaises(cu.Error):
            cu.read_upstream(self.write(lines.splitlines(True)[0]))  # lines missing


class ReadmeTest(unittest.TestCase):
    def test_readme_names_the_pinned_commit(self):
        short = cu.read_upstream()['cisco-mibs'][0][:7]
        for name in ('README.md', 'README.ja.md'):
            with open(os.path.join(TOP, name), encoding='utf-8') as fh:
                found = re.findall(r'(?:commit|コミット) `([0-9a-f]{7,40})`', fh.read())
            self.assertTrue(found, name)
            self.assertEqual(set(found), {short},
                             '%s names other commits than UPSTREAM; update it' % name)


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(cu.classify(['README.md', 'sdwan/x/IF-MIB.mib']), 'none')
        self.assertEqual(cu.classify(['v2/CISCO-PRODUCTS-MIB.my']), 'cana')
        self.assertEqual(cu.classify(['v2/CISCO-PRODUCTS-MIB.my', 'README.md',
                                      'v2/CISCO-ENTITY-VENDORTYPE-OID-MIB.my']), 'cana')
        self.assertEqual(cu.classify(['v2/CISCO-PRODUCTS-MIB.my', 'v2/CISCO-FC-FE-MIB.my']),
                         'mibs')
        self.assertEqual(cu.classify(['v1/CISCO-PRODUCTS-MIB.my']), 'mibs')


class ReportTest(unittest.TestCase):
    def test_title(self):
        self.assertEqual(cu.make_title(NEW, 'cana', False), 'cisco-mibs updated to bbbbbbb [CANA only]')
        self.assertEqual(cu.make_title(NEW, 'mibs', True),
                         'cisco-mibs updated to bbbbbbb [fixes not applied]')
        self.assertEqual(cu.make_title(NEW, 'none', False),
                         'cisco-mibs updated to bbbbbbb [no MIB changes]')

    def test_cana_report(self):
        title, body = cu.make_report(info())
        self.assertEqual(title, 'cisco-mibs updated to bbbbbbb [CANA only]')
        self.assertIn('1 commit(s) after `aaaaaaa`', body)
        self.assertIn('/compare/aaaaaaa...bbbbbbb', body)
        self.assertIn('**CANA only**', body)
        self.assertIn('Warnings: same as', body)
        self.assertIn('changed: mibs/CISCO-PRODUCTS-MIB.my', body)

    def test_patch_missed_report(self):
        title, body = cu.make_report(info(
            kind='mibs', changed=['M\tv2/CISCO-FC-FE-MIB.my', 'A\tsdwan/a/X.mib', 'A\tsdwan/b/Y.mib'],
            fix_new=(1, {'patched': 35, 'patch-not-applied': 1},
                     ['warning: Fixes not applied (1): CISCO-FC-FE-MIB']),
            output=(['mibs/NEW-MIB.my'], [], [])))
        self.assertTrue(title.endswith('[fixes not applied]'))
        self.assertIn('| exit status | 0 | 1 |', body)
        self.assertIn('| patch-not-applied | 0 | 1 |', body)
        self.assertIn('| patched | 36 | 35 |', body)
        self.assertIn('- warning: Unresolved dependencies (1): DOCS-PNM-MIB', body)
        self.assertIn('+ warning: Fixes not applied (1): CISCO-FC-FE-MIB', body)
        self.assertIn('Elsewhere (not read by fix_cisco_mibs.py): `sdwan/` 2.', body)
        self.assertNotIn('sdwan/a', body)
        self.assertIn('added:   mibs/NEW-MIB.my', body)

    def test_upstream_text_stays_in_code_blocks(self):
        # commit subjects come from upstream: no fence breaking, no mentions outside a block
        _, body = cu.make_report(info(commits=['bbbbbbb 2026-10-30 x ```', '```', '@someone hi']))
        self.assertNotIn('\n```\n@someone', body)
        self.assertEqual(body.count('```'), 2 * body.count('```text'))

    def test_long_lists_are_cut(self):
        block = cu.text_block(['f%d' % i for i in range(cu.MAX_LIST + 5)])
        self.assertIn('... 5 more', block)
        self.assertNotIn('f%d' % cu.MAX_LIST, block)


if __name__ == '__main__':
    unittest.main()
