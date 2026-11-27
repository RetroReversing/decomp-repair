"""Copy a labelled store out of a nested if arm and jump to its existing continuation.

In one GCC 2.7.2 KMC function, a guarded jump into a byte-zero store inside an earlier if arm inhibited the target's
branch layout. Copying the store and jumping past the common enclosing if improved the O2 score 46,980 -> 46,375
and O1 diagnostic 2,285 -> 1,800. The same function's other jump had to remain shared; each jump is tried alone.
"""
import re

from .csource import find
from .integer_repair_support import view
from .join_tail_arm_split_repairs import _blocks
from .shared_float_equality_ladder import _MACRO

FAMILY = 'copy_nested_goto_tail'
FAMILIES = (FAMILY,)
_LABEL = re.compile(r'(?m)^\s*(?P<label>(?!case\b|default\b)[A-Za-z_]\w*)\s*:\s*'
                    r'(?P<store>M2C_FIELD\(\s*[A-Za-z_]\w*\s*,\s*u8\s*\*\s*,\s*'
                    r'(?:0[xX][0-9a-fA-F]+|\d+)\s*\)\s*=\s*0[Uu]?\s*;)')


def variants(source, name, header=''):
    part, span = view(source, name), find(source, name)
    if not part or not span or not _MACRO.search(source + '\n' + (header or '')):
        return []
    closing = part.clean.rfind('}', part.opening, part.end)
    blocks = _blocks(part.clean, part.opening + 1, closing)
    if not blocks:
        return []
    out = []
    for hit in _LABEL.finditer(part.clean, part.opening + 1, part.end):
        label = hit['label']
        base = re.search(r'M2C_FIELD\(\s*([A-Za-z_]\w*)', hit['store'])[1]
        signature = part.clean[span[0]:part.opening]
        if not re.search(r'\b[A-Za-z_]\w*\s*\*+\s*' + re.escape(base) + r'\b', signature):
            continue
        if re.search(r'\b[A-Za-z_]\w*\s+\**\s*' + re.escape(base) + r'\s*(?:[;=,\[])', part.clean[part.opening:part.end]):
            continue
        if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+' + re.escape(base) + r'\b', source + '\n' + (header or '')):
            continue
        if re.search(r'/[*/]|#', source[hit.start():hit.end()]):
            continue
        holders = sorted((b for b in blocks if b[0] <= hit.start('label') < b[1]), key=lambda b: b[1] - b[0])
        if not holders or part.clean[hit.end():holders[0][1]].strip():
            continue
        jumps = list(re.finditer(r'\bgoto\s+' + re.escape(label) + r'\s*;', part.clean[span[0]:part.end]))
        for jump in jumps:
            at, end = span[0] + jump.start(), span[0] + jump.end()
            common = next(((lo, hi, start, stop) for lo, hi, items in holders for start, stop in items
                           if start <= hit.start('label') < stop and start <= at < stop
                           and re.match(r'if\b', part.clean[start:stop])), None)
            if not common:
                continue
            _, _, start, stop = common
            safe = True
            for lo, hi, items in holders:
                if not (start < lo and hi < stop):
                    continue
                parent = next(((a, b) for block_lo, block_hi, entries in holders for a, b in entries
                               if block_lo <= lo - 1 and hi < block_hi and a <= lo - 1 and hi < b), None)
                if not parent or not re.match(r'if\b', part.clean[parent[0]:parent[1]]):
                    safe = False
                    break
                containing = next(((a, b) for a, b in items if a <= hit.start('label') < b), None)
                if lo != holders[0][0] and containing and part.clean[containing[1]:hi].strip():
                    safe = False
                    break
            if not safe:
                continue
            join = 'decomp_tail_join'
            while re.search(r'\b' + join + r'\b', part.clean[span[0]:part.end]):
                join += '_'
            store = source[hit.start('store'):hit.end('store')]
            replacement = store + ' goto ' + join + ';'
            out.append((FAMILY, source[:at] + replacement + source[end:stop] + '\n' + join + ': ;' + source[stop:]))
            if len(out) >= 8:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
