"""Offer a target-evidenced upper guard around a no-default integer switch.

A MIPS target compared a selector against 20 before a switch whose only cases
were 7, 10 and 16. Restoring that redundant guard changed one KMC GCC 2.7.2
candidate from 4125 to 3925. All explicit case values must fall below the
observed bound; values outside it still do nothing. Nested switches are allowed,
but computed selectors, volatile code, gotos and dangling else are not.
"""
import re

from .case_temporary_repairs import DECLARATION, _depth_at, _groups, _switches
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'target_switch_upper_guard'
FAMILIES = (FAMILY,)
LIMIT = 32


def _bounds(asm):
    lines = [re.sub(r'/\*.*?\*/', '', line).strip() for line in (asm or '').splitlines()]
    found = []
    for a, b in zip(lines, lines[1:]):
        m = re.search(r'\bsltiu?\s+(\$\w+)\s*,\s*\$\w+\s*,\s*(0x[\da-fA-F]+|\d+)\b', a)
        if m and re.search(r'\bb(?:eq|ne)z\s+' + re.escape(m[1]) + r'\s*,', b):
            value = int(m[2], 0)
            if 0 < value <= 32767 and value not in found:
                found.append(value)
    return found


def variants(source, name, asm, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', clean[opening:end]):
        return []
    bounds = _bounds(asm)
    types = ('s8', 'u8', 's16', 'u16', 's32', 'u32', 'int', 'unsigned', 'unsigned int', 'signed int')
    declarations = {}
    counts = {}
    for decl in DECLARATION.finditer(clean, opening + 1, end):
        counts[decl['name']] = counts.get(decl['name'], 0) + 1
        if not _depth_at(clean, opening + 1, decl.start()) and decl['type'].strip() in types:
            declarations.setdefault(decl['name'], []).append(decl['type'].strip())
    macros = source + '\n' + (header or '')
    switches = _switches(clean, opening, end)
    result = []
    for match in re.finditer(r'\bswitch\s*\(\s*([A-Za-z_]\w*)\s*\)\s*\{', clean[opening:end]):
        selector = match[1]
        if len(declarations.get(selector, [])) != 1 or counts.get(selector) != 1:
            continue
        typ = declarations[selector][0]
        if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+(?:' + re.escape(selector) + '|' + re.escape(typ) + r')\b', macros):
            continue
        if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b' + re.escape(typ) + r'\s*;', macros):
            continue
        start = opening + match.start()
        body = (opening + match.end() - 1, None)
        body = next((item for item in switches if item[0] == body[0]), None)
        if not body:
            continue
        before = clean[opening:start].rstrip()
        after = clean[body[1] + 1:end].lstrip()
        if not before or before[-1] not in '{;}:':
            continue
        if re.match(r'else\b', after):
            continue
        groups = _groups(clean, body, [s for s in switches if body[0] < s[0] and s[1] < body[1]])
        if not groups:
            continue
        values = []
        for label, _, _ in groups:
            m = re.fullmatch(r'case\s+(0x[\da-fA-F]+|\d+)', label)
            if not m:
                break
            values.append(int(m[1], 0))
        else:
            for bound in bounds:
                if max(values) >= bound:
                    continue
                child = source[:start] + f'if ({match[1]} < 0x{bound:X}) ' + source[start:]
                result.append((FAMILY, child))
                if len(result) >= LIMIT:
                    return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',), 'order': 40}
