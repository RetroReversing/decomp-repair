"""Try paired orders for independent float captures and stores on the same base."""

import re
from itertools import permutations

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'measured_staged_float_order'
_FLOAT = r'(?:f32|float)'
_ADDRESS = rf'\({_FLOAT}\s*\*\)\s*\(\(\(char\s*\*\)\s*(?P<base>{IDENT})\)\s*\+\s*(?P<offset>0x[\da-fA-F]+)\)'
_HELPER = re.compile(
    rf'\b(?:inline\s+static|static\s+inline)\s+{_FLOAT}\s+({IDENT})\s*'
    rf'\(\s*{_FLOAT}\s*\*\s*({IDENT})\s*,\s*{_FLOAT}\s+({IDENT})\s*\)\s*'
    r'\{\s*return\s+\*\s*\2\s*\+\s*\3\s*;\s*\}'
)
_CAPTURE = re.compile(
    rf'(?m)^[ \t]*(?P<local>{IDENT})\s*=\s*(?P<helper>{IDENT})\s*\({_ADDRESS},'
    rf'\s*(?P<delta>{IDENT}(?:\.{IDENT})?)\s*\)\s*;[ \t]*\n'
)
_STORE = re.compile(rf'(?m)^[ \t]*\*\({_ADDRESS}\)\s*=\s*(?P<local>{IDENT})\s*;[ \t]*\n')
_DECL = re.compile(rf'(?m)^[ \t]*(?:(?:extern|register)\s+)?{_FLOAT}\s+({IDENT})\s*;')
_ASM_STORE = re.compile(r'swc1 \$f\d+, (0x[\da-f]+)\((\$\w+)\)')


def _staged_block(part, start, helpers):
    captures, stores = [], []
    pos = start
    while (hit := _CAPTURE.match(part.clean, pos, part.end)) and len(captures) <= 8:
        captures.append(hit)
        pos = hit.end()
    while (hit := _STORE.match(part.clean, pos, part.end)) and len(stores) <= 8:
        stores.append(hit)
        pos = hit.end()
    if not 3 <= len(captures) == len(stores) <= 8:
        return None
    if any(hit['helper'] not in helpers for hit in captures):
        return None
    captured = {(hit['local'], hit['base'], int(hit['offset'], 16)) for hit in captures}
    stored = {(hit['local'], hit['base'], int(hit['offset'], 16)) for hit in stores}
    if (captured != stored or len({base for _, base, _ in captured}) != 1
            or len({local for local, _, _ in captured}) != len(captures)
            or len({offset for _, _, offset in captured}) != len(captures)
            or any(offset % 4 for _, _, offset in captured)):
        return None
    return captures, stores


def variants(source, name, rows, header=''):
    mismatched = set()
    for kind, target, candidate in rows:
        if kind == ' ':
            continue
        a, b = _ASM_STORE.fullmatch(target), _ASM_STORE.fullmatch(candidate)
        if a and b and a[2] == b[2] and a[1] != b[1]:
            mismatched.update((int(a[1], 16), int(b[1], 16)))
    part = view(source, name) if mismatched else None
    if not part:
        return []
    helpers = {match[1] for match in _HELPER.finditer(part.clean, 0, part.opening)}
    if not helpers:
        return []
    combined = _blank(header) + '\n' + part.clean
    declarations = [match[1] for match in _DECL.finditer(combined)]
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})', combined))
    if macros & {'f32', 'float', 'char'} or re.search(r'\btypedef\s+[^;]*\bvolatile\b[^;]*\bf32\s*;', combined):
        return []
    signature = part.clean[part.clean.rfind('}', 0, part.opening) + 1:part.opening]
    for first in _CAPTURE.finditer(part.clean, part.opening, part.end):
        if not re.search(rf'[(,]\s*(?:void|char|{_FLOAT})\s*\*\s*{first["base"]}\s*[,)]', signature):
            continue
        block = _staged_block(part, first.start(), helpers)
        if block is None:
            continue
        captures, stores = block
        capture_prefix, store_prefix = captures[:3], stores[:3]
        local_names = {m['local'] for m in captures}
        deltas = {m['delta'] for m in capture_prefix}
        if (not mismatched.intersection(int(m['offset'], 16) for m in store_prefix)
                or any(declarations.count(var) != 1 for var in local_names | deltas)
                or local_names & deltas
                or macros & (local_names | deltas | helpers | {first['base']})):
            continue
        # Only the first three captures and stores are permuted. Their fields
        # are disjoint and their deltas are ordinary scalars, so no load crosses
        # a store and none of the captures reads a result of another capture.
        result = []
        for capture_order in ((0, 1, 2), (0, 2, 1)):
            for store_order in permutations(range(3)):
                if (capture_order, store_order) == ((0, 1, 2), (0, 1, 2)):
                    continue
                changes = [
                    (group[0].start(), group[-1].end(),
                     ''.join(source[group[i].start():group[i].end()] for i in order))
                    for group, order in ((capture_prefix, capture_order), (store_prefix, store_order))
                ]
                result.append((FAMILY, edit(source, changes)))
        return result
    return []
