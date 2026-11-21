"""Fold reads through a fixed-offset byte cursor into its parallel base cursor."""

import re

from .csource import _blank, find
from .integer_repair_support import IDENT, View, edit, integer
from .pattern_repairs import close

FAMILY = 'parallel_byte_cursor'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|0|[1-9][0-9]*)'
INIT = re.compile(
    rf'(?<=[;{{}}])\s*(?P<alias>{IDENT})\s*=\s*(?P<base>{IDENT})\s*\+\s*(?P<offset>{NUMBER})\s*;'
    r'\s*do\s*{'
)
STEP = rf'({IDENT})\s*\+=\s*({NUMBER})\s*;'
TAIL = re.compile(rf'(?:\s*{STEP})+\s*$')
BYTE = r'u8|unsigned\s+char'


def _local(part, name, types):
    decl = re.search(rf'(?<=[;{{}}])\s*(?:{types})\s*\*\s*{name}\s*;', part.clean[part.opening:part.end])
    if decl:
        prefix = part.clean[part.opening:part.opening + decl.start()]
        if prefix.count('{') == prefix.count('}') + 1:
            return decl
    return None


def _loop_edits(part, match, header):
    alias, base = match['alias'], match['base']
    if (alias == base or not _local(part, alias, rf'void|{BYTE}') or not _local(part, base, BYTE)
            or re.search(rf'(?m)^\s*#\s*define\s+(?:{alias}|{base})\b', header + '\n' + part.clean)):
        return []
    opening = match.end() - 1
    end = close(part.clean, opening, '{', '}')
    test = end and re.match(r'\s*while\s*\(', part.clean[end:part.end])
    test_end = test and close(part.clean, end + test.end() - 1)
    if not test_end or re.search(rf'\b{base}\b', part.clean[end:test_end]):
        return []
    before = part.clean[part.opening:match.start()]
    outside = before + ' ' + part.clean[test_end:part.end]
    # Outside the walk allow one declaration and one assignment to the base.
    # An enclosing block can otherwise shadow the byte pointer with another type.
    if (len(re.findall(rf'\b{base}\b', outside)) != 2
            or not re.search(rf'(?<=[;{{}}])\s*{base}\s*=(?!=)', before)):
        return []
    body = part.clean[opening + 1:end - 1]
    tail = TAIL.search(body)
    if not tail:
        return []
    inner = body[:tail.start()].rstrip()
    if ((inner and inner[-1] not in ';}') or inner.count('{') != inner.count('}')
            or re.search(rf'#|\b(?:goto|case|default|asm|__asm__)\b|\b{IDENT}\s*:(?!:)', inner)):
        return []
    steps = list(re.finditer(STEP, tail[0]))
    alias_steps = [step for step in steps if step[1] == alias]
    base_steps = [step for step in steps if step[1] == base]
    if len(alias_steps) != 1 or len(base_steps) != 1:
        return []
    stride = integer(base_steps[0][2])
    offset = integer(match['offset'])
    if not 0 < offset < stride or stride != integer(alias_steps[0][2]):
        return []
    # Each cursor is advanced exactly once at the bottom of the loop. Reject any
    # other alias use and allow only dereferences of the base in the loop body.
    reads = list(re.finditer(
        rf'\*\s*\(\s*(?:{BYTE})\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*'
        rf'\(\s*{alias}\s*\)\s*\+\s*(?P<offset>-?{NUMBER})\s*\)',
        body[:tail.start()],
    ))
    if (not reads or len(re.findall(rf'\b{alias}\b', part.body)) != len(reads) + 3
            or len(re.findall(rf'\b{base}\b', body[:tail.start()]))
            != len(re.findall(rf'(?<=[(=,])\s*\*\s*{base}\b(?!\s*\[)', body[:tail.start()]))):
        return []
    edits = []
    for read in reads:
        number = read['offset']
        displacement = -integer(number[1:]) if number.startswith('-') else integer(number)
        index = offset + displacement
        if not 0 <= index < stride:
            return []
        edits.append((opening + 1 + read.start(), opening + 1 + read.end(), f'{base}[{index}]'))
    return edits


def variants(source, name, header=''):
    """Propose only loads within the record shared by the two cursors."""
    span = find(source, name)
    if not span or 'do' not in source[span[0]:span[1]]:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    part = View(source, clean, opening, span[1])
    result = []
    for match in INIT.finditer(part.clean, part.opening + 1, part.end):
        edits = _loop_edits(part, match, header)
        if edits:
            result.append((FAMILY, edit(source, edits)))
    return result[:4]
