# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""Checks smiscan.read on files that are not plain MIBs.

Needs nothing outside the repository. Run: python3 -m unittest discover tests
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import smiscan  # noqa: E402

MIB = b'A-MIB DEFINITIONS ::= BEGIN\nEND\n'


class ReadTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def put(self, data):
        p = os.path.join(self.dir, 'f')
        with open(p, 'wb') as fh:
            fh.write(data)
        return p

    def test_plain(self):
        self.assertEqual(smiscan.read(self.put(MIB + b'-- caf\xe9\n')),
                         MIB.decode() + '-- caf\xe9\n')

    def test_newlines_like_text_mode(self):
        self.assertEqual(smiscan.read(self.put(b'a\r\nb\rc\n')), 'a\nb\nc\n')

    def test_binary_is_not_a_mib(self):
        # e.g. the .tar.gz files in cisco-mibs/v1 and v2
        self.assertEqual(smiscan.read(self.put(b'\x1f\x8b\x08\x00' + MIB)), '')

    def test_too_large_is_not_a_mib(self):
        p = self.put(MIB)
        with mock.patch.object(smiscan, 'MAX_SIZE', len(MIB) - 1):
            self.assertEqual(smiscan.read(p), '')
        with mock.patch.object(smiscan, 'MAX_SIZE', len(MIB)):
            self.assertEqual(smiscan.read(p), MIB.decode())


if __name__ == '__main__':
    unittest.main()
