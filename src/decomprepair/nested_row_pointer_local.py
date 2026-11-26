"""A row pointer read from a table of pointers, held in a local on the line before its row is indexed.

`row = &o->rows[TABLE[GLOBAL][o->kind * 2]];` with `extern u8 *TABLE[];` reads the inner index's byte first and the table's
slot after it, or keeps the slot's address in `$at`. The target loads the row pointer first and the index byte after it
(`lui $v1; addu $v1,$v1,$v0; lw $v1; lbu $v0,...; sll; addu $v0,$v0,$v1`), which is what the original wrote as two
statements:

    tbl = TABLE[GLOBAL];  row = &o->rows[tbl[o->kind * 2]];

The case (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`, N64): a 131-instruction distance-to-waypoint routine was at 90
(registers and two reordered rows) written with the nested subscript and 0 with the row pointer in a local; no family of
the library made the step. Which compiler pass orders the two loads is not read from its source.

One child per statement and table: `extern T *NAME[...];`, a statement without a call or a control keyword that reads
`NAME[I][...]`, where `I` holds no call, assignment or step. The read of `NAME[I]` moves only to the line before, so
the child is the same program. A candidate for the exact judge, never a verdict.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'nested_row_pointer_local'
FAMILIES = (FAMILY,)
LIMIT = 6
IDENT = r'[A-Za-z_]\w*'
TABLE = re.compile(rf'\bextern\s+(?P<type>(?:const\s+|unsigned\s+|signed\s+|struct\s+)*{IDENT})\s*\*\s*'
                   rf'(?P<name>{IDENT})\s*\[[^\]\[;]*\]\s*;')
CONTROL = re.compile(r'\b(?:if|for|while|switch|case|default|do|else|goto|return)\b')
CALL = re.compile(rf'\b(?!sizeof\b){IDENT}\s*\(')
EFFECT = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)')


def variants(source, name, header=''):
    clean = _blank(source)
    span = find(source, name)
    if not span:
        return []
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    tables = {hit['name']: re.sub(r'\s+', ' ', hit['type']) for text in (_blank(header or ''), clean[:start])
              for hit in TABLE.finditer(text)}
    result = []
    for table, element in tables.items():
        for use in re.finditer(rf'(?<![\w.>&]){table}\s*\[', clean[opening:end]):
            at = opening + use.start()
            bracket = opening + use.end() - 1
            past = close(clean, bracket, '[', ']')
            if past is None or not clean[past:end].lstrip().startswith('['):
                continue
            stop = past - 1
            index = clean[bracket + 1:stop]
            if CALL.search(index) or EFFECT.search(index):
                continue
            first = max(clean.rfind(mark, opening, at) for mark in ';{}') + 1
            last = clean.find(';', stop, end)
            if last < 0:
                continue
            statement = clean[first:last]
            if CONTROL.search(statement) or CALL.search(statement) or '{' in statement or ':' in statement:
                continue
            local = f'{table}_row'
            if re.search(rf'\b{local}\b', clean):
                continue
            first += len(clean[first:]) - len(clean[first:].lstrip())
            read = source[at:stop + 1]
            line = source[first:last].replace(read, local)
            body = f'{source[opening + 1:first]}{local} = {read}; {line}{source[last:]}'
            text = f'{source[:opening + 1]} {element} *{local};{body}'
            if text not in result:
                result.append(text)
    return [(FAMILY, text) for text in result[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 71}  # the registry: no caller wiring (registry.py)
