# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""Lightweight SMI scanner: module name, imports, local definitions, and referenced symbols.

Not a full ASN.1 parser. It is good enough to find symbols that a MIB module
uses (SYNTAX types, OID parents, INDEX/AUGMENTS objects, OBJECTS/NOTIFICATIONS
lists) but neither defines nor imports.
"""
import re

ASN1_BUILTIN = {
    'INTEGER', 'OCTET', 'STRING', 'OBJECT', 'IDENTIFIER', 'BITS', 'SEQUENCE',
    'OF', 'SIZE', 'NULL', 'CHOICE', 'IMPLICIT', 'BEGIN', 'END', 'MAX', 'MIN',
    'iso', 'ccitt', 'joint-iso-ccitt',
}
# Macro names / keywords that can appear where we look for type names
KEYWORDS = {
    'OBJECT-TYPE', 'MODULE-IDENTITY', 'OBJECT-IDENTITY', 'NOTIFICATION-TYPE',
    'TRAP-TYPE', 'OBJECT-GROUP', 'NOTIFICATION-GROUP', 'MODULE-COMPLIANCE',
    'AGENT-CAPABILITIES', 'TEXTUAL-CONVENTION', 'MACRO', 'DEFINITIONS',
    'IMPORTS', 'EXPORTS', 'FROM', 'SYNTAX', 'ACCESS', 'MAX-ACCESS', 'STATUS',
}
DEF_MACROS = (
    'OBJECT-TYPE', 'MODULE-IDENTITY', 'OBJECT-IDENTITY', 'NOTIFICATION-TYPE',
    'TRAP-TYPE', 'OBJECT-GROUP', 'NOTIFICATION-GROUP', 'MODULE-COMPLIANCE',
    'AGENT-CAPABILITIES',
)


def strip_comments(text):
    """Remove ASN.1 comments ("--" to "--" or end of line), keeping strings.

    Strings may span lines; comments may not. Quotes inside comments are ignored.
    """
    res, i, n, in_str = [], 0, len(text), False
    while i < n:
        ch = text[i]
        if in_str:
            res.append(ch)
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            res.append(ch); i += 1
            continue
        if text.startswith('--', i):
            j = i + 2
            while j < n and text[j] != '\n' and not text.startswith('--', j):
                j += 1
            i = j + 2 if text.startswith('--', j) else j
            continue
        res.append(ch); i += 1
    return ''.join(res)


def strip_strings(text):
    return re.sub(r'"[^"]*"', '""', text)


def clean(text):
    return strip_strings(strip_comments(text))


MOD_RE = re.compile(r'([A-Za-z][A-Za-z0-9-]*)\s+(?:\{[^}]*\}\s*)?DEFINITIONS\s*(?:[A-Z ]*)::=\s*BEGIN')


def module_name(text_clean):
    m = MOD_RE.search(text_clean)
    return m.group(1) if m else None


def parse_imports(text_clean):
    """Return dict symbol -> module, plus (start, end) span of the IMPORTS body."""
    m = re.search(r'\bIMPORTS\b(.*?);', text_clean, re.S)
    if not m:
        return {}, None
    body = m.group(1)
    imports = {}
    pending = []
    for tok in re.findall(r'[A-Za-z][A-Za-z0-9-]*|,', body):
        if tok == ',':
            continue
        if tok == 'FROM':
            pending.append('__FROM__')
            continue
        if pending and pending[-1] == '__FROM__':
            pending.pop()
            for s in pending:
                imports[s] = tok
            pending = []
            continue
        pending.append(tok)
    return imports, m.span(1)


def local_defs(text_clean):
    defs = set()
    for m in re.finditer(r'^\s*([a-z][A-Za-z0-9-]*)\s+(' + '|'.join(DEF_MACROS) + r')\b', text_clean, re.M):
        defs.add(m.group(1))
    for m in re.finditer(r'(?<![A-Za-z0-9-])([a-z][A-Za-z0-9-]*)\s+OBJECT\s+IDENTIFIER\s*::=', text_clean):
        defs.add(m.group(1))
    for m in re.finditer(r'^\s*([A-Z][A-Za-z0-9-]*)\s*::=', text_clean, re.M):
        defs.add(m.group(1))
    return defs


OID_HEAD_RE = re.compile(
    r'^\s*([a-z][A-Za-z0-9-]*)\s+(' + '|'.join(DEF_MACROS) + r')\b'
    r'|(?<![A-Za-z0-9-])([a-z][A-Za-z0-9-]*)\s+OBJECT\s+IDENTIFIER\s*(?=::=)', re.M)
OID_VALUE_RE = re.compile(r'::=\s*\{([^}]*)\}')
TRAP_RE = re.compile(r'\bENTERPRISE\s+([a-z][A-Za-z0-9-]*).*?::=\s*(\d+)', re.S)
NOTIF_OBJECTS_RE = re.compile(r'\b(?:OBJECTS|VARIABLES)\s*\{([^}]*)\}')
OID_COMP_RE = re.compile(r'([A-Za-z][A-Za-z0-9-]*)(?:\s*\(\s*(\d+)\s*\))?|(\d+)')


def oid_assignments(text_clean):
    """Yield (name, macro, components) for each OID value assignment.

    components is the parsed { ... } value: the first may be a parent name,
    the rest are numbers. A TRAP-TYPE gets the OID SNMPv2 gives it
    (RFC 3584): { ENTERPRISE 0 value }.
    """
    heads = list(OID_HEAD_RE.finditer(text_clean))
    for i, m in enumerate(heads):
        name = m.group(1) or m.group(3)
        macro = m.group(2) or 'OBJECT IDENTIFIER'
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text_clean)
        if macro == 'TRAP-TYPE':
            t = TRAP_RE.search(text_clean, m.end(), end)
            if t:
                yield name, macro, [t.group(1), 0, int(t.group(2))]
            continue
        v = OID_VALUE_RE.search(text_clean, m.end(), end)
        if not v:
            continue
        comps = []
        for word, num, bare in OID_COMP_RE.findall(v.group(1)):
            if bare:
                comps.append(int(bare))
            elif num:
                comps.append(int(num))
            elif not comps:
                comps.append(word)
            else:
                comps = None  # a name after the first position: not supported
                break
        if comps:
            yield name, macro, comps


def notification_objects(text_clean):
    """Yield (name, [objects]) for each NOTIFICATION-TYPE (OBJECTS) and
    TRAP-TYPE (VARIABLES) that lists objects."""
    heads = list(OID_HEAD_RE.finditer(text_clean))
    for i, m in enumerate(heads):
        if m.group(2) not in ('NOTIFICATION-TYPE', 'TRAP-TYPE'):
            continue
        end = text_clean.find('::=', m.end())
        if end < 0:
            continue
        v = NOTIF_OBJECTS_RE.search(text_clean, m.end(), end)
        if v:
            objs = _ids(v.group(1))
            if objs:
                yield m.group(1), objs


def _ids(s):
    return re.findall(r'[A-Za-z][A-Za-z0-9-]*', s)


def references(text_clean):
    """Symbols referenced by this module that must be resolvable."""
    body = text_clean
    im = re.search(r'\bIMPORTS\b.*?;', body, re.S)
    if im:
        body = body[:im.start()] + body[im.end():]
    refs = set()
    # Types after SYNTAX / in SEQUENCE bodies / TC definitions / WRITE-SYNTAX
    for m in re.finditer(r'\b(?:SYNTAX|WRITE-SYNTAX)\s+(?:SEQUENCE\s+OF\s+)?([A-Z][A-Za-z0-9-]*)', body):
        refs.add(m.group(1))
    for m in re.finditer(r'::=\s*SEQUENCE\s*\{(.*?)\}', body, re.S):
        for line in m.group(1).split(','):
            ids = _ids(line)
            if len(ids) >= 2 and ids[1][0].isupper():
                refs.add(ids[1])
    for m in re.finditer(r'^\s*[A-Z][A-Za-z0-9-]*\s*::=\s*([A-Z][A-Za-z0-9-]*)', body, re.M):
        refs.add(m.group(1))
    # OID parents
    for m in re.finditer(r'::=\s*\{\s*([a-z][A-Za-z0-9-]*)\s', body):
        refs.add(m.group(1))
    # INDEX / AUGMENTS / OBJECTS / NOTIFICATIONS / VARIABLES lists
    for kw in ('INDEX', 'AUGMENTS', 'OBJECTS', 'NOTIFICATIONS', 'VARIABLES'):
        for m in re.finditer(r'\b' + kw + r'\s*\{([^}]*)\}', body):
            for s in _ids(m.group(1)):
                if s != 'IMPLIED':
                    refs.add(s)
    refs -= ASN1_BUILTIN
    refs -= KEYWORDS
    return refs


def scan(text):
    tc = clean(text)
    mod = module_name(tc)
    imports, span = parse_imports(tc)
    return {
        'module': mod,
        'imports': imports,
        'defs': local_defs(tc),
        'refs': references(tc),
        'has_imports': span is not None,
    }
