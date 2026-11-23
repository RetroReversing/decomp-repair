"""A call that indexes one table twice, with the table's base and a narrow index load staged in locals before it.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) probe handler, 240 -> 200 -> 180 on the exact judge. One call
passed two entries of one table, `unlink(a, tab[words[k].link], tab[*(s8 *)(rec + 0x182)])`. Written in the call, the
signed byte load is part of an address sum that local allocation places after the other index, and the table's base
address (a hoisted symbol the allocator reloads) takes `$a2`, one of the call's own argument registers; the target loads
the byte first, holds the base in `$t0`, and has the two sums in the other order.

call_index_load_stage
    `f(a, T[x], T[*(s8 *)(p + K)])` becomes `idx = *(s8 *)(p + K); f(a, T[x], T[idx]);` for a plain call statement
    with an array subscript that is nothing but one dereference of a cast pointer. The local is an `s32`, the value the
    load had in the subscript. One child per such call.
call_table_base_local
    `f(a, T[x], T[y])` becomes `base = T; f(a, base[x], base[y]);` for a plain call statement that subscripts one
    `extern` array twice (the base's pointer type is the array's element type plus a star). The assignment goes in
    front of the call's own staged index when the call has one, so the base is read first.
call_table_stage
    both at once: the base and the staged index in front of the call, base first.

No argument of the call may have a call, `++`, `--` or assignment in it (the staged reads move in front of all of
them). The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .call_global_stage import _IMPURE, plain_calls
from .integer_repair_support import IDENT, edit, view

FAMILY_INDEX = 'call_index_load_stage'
FAMILY_BASE = 'call_table_base_local'
FAMILY_BOTH = 'call_table_stage'
FAMILIES = (FAMILY_INDEX, FAMILY_BASE, FAMILY_BOTH)
LIMIT = 6
_ARRAY = re.compile(rf'\bextern\s+(?P<type>{IDENT}(?:\s+{IDENT})*?\s*\**)\s*(?P<name>{IDENT})\s*\[[^\]]*\]\s*;')
_LOAD = re.compile(rf'(?<![\w.>])(?P<table>{IDENT})\s*\[\s*(?P<load>\*\s*\(\s*\(?\s*(?:s8|u8|s16|u16)\s*\*\s*\)?[^\[\];]*\))\s*\]')


def _tables(source, header):
    found = {}
    for text in (header, source):
        for hit in _ARRAY.finditer(text):
            kind = re.sub(r'\s+', ' ', hit['type']).strip()
            if not re.search(r'\bvolatile\b', kind):
                found[hit['name']] = kind
    return found


def _balanced(text):
    depth = 0
    for char in text:
        depth += char == '('
        depth -= char == ')'
        if depth < 0:
            return False
    return depth == 0


def _calls(part, tables):
    """[(statement start, arg spans, callee, table name or None, load span or None)] for the calls that qualify."""
    found = []
    for start, end, callee, spans in plain_calls(part, tables):
        text = part.clean[start:end]
        if any(_IMPURE.search(part.clean[a:b]) for a, b in spans):
            continue
        counts = {name: len(re.findall(rf'(?<![\w.>]){name}\s*\[', text)) for name in tables}
        twice = [name for name, n in counts.items() if n >= 2]
        loads = [m for m in _LOAD.finditer(part.clean, start, end) if m['table'] in tables and _balanced(m['load'])]
        found.append((start, end, callee, twice[0] if len(twice) == 1 else None, loads[0] if len(loads) == 1 else None))
    return found


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    tables = _tables(source, header)
    calls = [c for c in _calls(part, tables) if c[3] or c[4]][:LIMIT]
    taken = set(re.findall(IDENT, source + header))
    children = []

    def build(call, base, index):
        start, end, callee, table, load = call
        changes, declared, lines = [], [], ''
        first = source.rfind('\n', 0, start) + 1
        alone = not source[first:start].strip()
        indent = source[first:start] if alone else ''
        tail = '\n' if alone else ' '
        if base:
            fresh = f'{table}_base'
            if fresh in taken:
                return None
            declared.append(f'\n  {tables[table]} *{fresh};')
            lines += f'{indent}{fresh} = {table};{tail}'
            for hit in re.finditer(rf'(?<![\w.>]){table}(?=\s*\[)', part.clean[start:end]):
                changes.append((start + hit.start(), start + hit.end(), fresh))
        if index:
            fresh = f'{callee}_index_stage'
            if fresh in taken:
                return None
            declared.append(f'\n  s32 {fresh};')
            lines += f'{indent}{fresh} = {load["load"]};{tail}'
            changes.append((load.start('load'), load.end('load'), fresh))
        changes.append((first if alone else start,) * 2 + (lines,))
        changes.append((part.opening + 1, part.opening + 1, ''.join(declared)))
        return edit(source, changes)

    for call in calls:
        for family, base, index in ((FAMILY_INDEX, False, True), (FAMILY_BASE, True, False), (FAMILY_BOTH, True, True)):
            if (base and not call[3]) or (index and not call[4]):
                continue
            if family == FAMILY_BOTH and not (call[3] and call[4]):
                continue
            text = build(call, base, index)
            if text:
                children.append((family, text))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
