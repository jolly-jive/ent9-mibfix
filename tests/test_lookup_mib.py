# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""Checks lookup_mib.py against OUT_DIR/mibs from fix_cisco_mibs.py at out/mibs.

Skips when out/mibs is missing. Run: python3 -m unittest discover tests
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
sys.path.insert(0, TOP)
import extract_mibs  # noqa: E402
import lookup_mib  # noqa: E402

MIBDIR = os.path.join(TOP, 'out', 'mibs')
FAN_STATE = (1, 3, 6, 1, 4, 1, 9, 9, 13, 1, 4, 1, 3)


@unittest.skipUnless(os.path.isdir(MIBDIR), 'needs out/mibs')
class LookupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mods = extract_mibs.load_modules([MIBDIR])
        cls.lookup = lookup_mib.Lookup(mods, extract_mibs.OidIndex(mods))

    def names(self, query):
        return [(oid, mod, name, oid[len(prefix):])
                for oid, prefix, (mod, name, _) in self.lookup.find(query)]

    def test_numeric_with_instance(self):
        self.assertEqual(self.names('.1.3.6.1.4.1.9.9.13.1.4.1.3.1'),
                         [(FAN_STATE + (1,), 'CISCO-ENVMON-MIB', 'ciscoEnvMonFanState', (1,))])

    def test_name(self):
        self.assertEqual(self.names('ciscoEnvMonFanState'),
                         [(FAN_STATE, 'CISCO-ENVMON-MIB', 'ciscoEnvMonFanState', ())])

    def test_name_in_several_modules(self):
        mods = {mod for _, mod, _, _ in self.names('ifDescr.1')}
        self.assertTrue({'IF-MIB', 'RFC1213-MIB'} <= mods)

    def test_module_qualified(self):
        self.assertEqual(self.names('SNMPv2-SMI::enterprises.9.9.13'),
                         [((1, 3, 6, 1, 4, 1, 9, 9, 13), 'CISCO-ENVMON-MIB', 'ciscoEnvMonMIB', ())])

    def test_unknown(self):
        self.assertEqual(self.lookup.find('noSuchObjectName'), [])
        self.assertEqual(self.lookup.find('NO-SUCH-MIB::ifDescr'), [])
        self.assertEqual(self.lookup.find('IF-MIB::sysDescr'), [])
        self.assertEqual(self.lookup.find('not an oid'), [])

    def test_definition(self):
        path = os.path.join(MIBDIR, 'CISCO-ENVMON-MIB.my')
        text = lookup_mib.definition(path, 'ciscoEnvMonFanState', 'OBJECT-TYPE')
        self.assertTrue(text.startswith('ciscoEnvMonFanState OBJECT-TYPE'))
        self.assertIn('SYNTAX     CiscoEnvMonState', text)
        self.assertTrue(text.endswith('::= { ciscoEnvMonFanStatusEntry 3 }'))


if __name__ == '__main__':
    unittest.main()
