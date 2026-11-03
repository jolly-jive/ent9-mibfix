# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""Checks that every message fix_cisco_mibs.py logs has a Japanese version.

A missing key in messages.ja.json would otherwise stop fix_cisco_mibs.py with
a KeyError minutes into a run. Needs nothing outside the repository.

Run: python3 -m unittest discover tests
"""
import ast
import json
import os
import string
import unittest

TOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(TOP, 'fix_cisco_mibs.py')

# position of the message text among the arguments of each function
TEXT_ARG = {'Msg': 0, 'log': 2, 'patch': 4}


def texts(node, assigned):
    """The message strings an argument can be, or None if it can't be told."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        a, b = texts(node.body, assigned), texts(node.orelse, assigned)
        return None if a is None or b is None else a + b
    if isinstance(node, ast.Name) and node.id in assigned:
        out = []
        for value in assigned[node.id]:
            t = texts(value, assigned)
            if t is None:
                return None
            out += t
        return out
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
            and node.value.id in assigned:
        out = []
        for d in assigned[node.value.id]:
            if not isinstance(d, ast.Dict):
                return None
            for v in d.values:
                t = texts(v, assigned)
                if t is None:
                    return None
                out += t
        return out
    return None


def own_nodes(scope):
    """The nodes of scope, without those of the functions defined in it."""
    todo = list(ast.iter_child_nodes(scope))
    while todo:
        node = todo.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Lambda)):
            todo.extend(ast.iter_child_nodes(node))


class MessagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(TOP, 'messages.ja.json'), encoding='utf-8') as fh:
            cls.ja = json.load(fh)
        with open(SOURCE, encoding='utf-8') as fh:
            cls.tree = ast.parse(fh.read())

    def messages(self):
        """(line, text) of every message the source can log."""
        module_level = {}
        for node in self.tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        module_level.setdefault(t.id, []).append(node.value)
        found = []
        for func in [self.tree] + [n for n in ast.walk(self.tree)
                                   if isinstance(n, ast.FunctionDef)]:
            assigned = {k: list(v) for k, v in module_level.items()}
            # a parameter passed on (as in log() and patch()) is checked at their callers
            params = {a.arg for a in func.args.args} if isinstance(func, ast.FunctionDef) else set()
            for node in own_nodes(func):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            assigned.setdefault(t.id, []).append(node.value)
                # for a, b in TABLE: a and b take the items of TABLE's tuples
                elif isinstance(node, ast.For) and isinstance(node.target, ast.Tuple) \
                        and isinstance(node.iter, ast.Name) and node.iter.id in assigned:
                    for table in assigned[node.iter.id]:
                        for row in getattr(table, 'elts', []):
                            for t, v in zip(node.target.elts, getattr(row, 'elts', [])):
                                if isinstance(t, ast.Name):
                                    assigned.setdefault(t.id, []).append(v)
            for node in own_nodes(func):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, 'id', None)
                if name not in TEXT_ARG:
                    continue
                pos = TEXT_ARG[name]
                arg = node.args[pos] if len(node.args) > pos else None
                if arg is None or isinstance(arg, ast.Name) and arg.id in params:
                    continue
                t = texts(arg, assigned)
                self.assertIsNotNone(t, 'line %d: cannot tell the message text of %s(); '
                                     'write it as a string literal or update this test'
                                     % (node.lineno, name))
                found += [(node.lineno, s) for s in t]
        return found

    def test_every_message_is_translated(self):
        messages = self.messages()
        self.assertGreater(len(messages), 30)
        missing = sorted({(line, text) for line, text in messages if text not in self.ja})
        self.assertEqual(missing, [], 'add these to messages.ja.json')

    def test_placeholders_match(self):
        def fields(s):
            return sorted({f for _, f, _, _ in string.Formatter().parse(s) if f})
        for en, ja in self.ja.items():
            with self.subTest(en):
                self.assertEqual(fields(en), fields(ja))


if __name__ == '__main__':
    unittest.main()
