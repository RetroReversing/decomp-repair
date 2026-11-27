"""Recover a guarded selector switch with its no-op controller cases.

A MIPS handler's compare tree was written as a low nested switch and two high
if arms, omitting no-op values. The target compares against 20, 28 and 92;
reconstructing one switch with no-op cases 20..27 and 93 changed an isolated
KMC score from 1665 to 675, with other edits retained. The extra cases do
nothing, and target comparisons guide their proposal rather than prove source.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'target_guarded_switch_cases'
FAMILIES = (FAMILY,)


def _witness(asm):
    lines = re.sub(r'/\*.*?\*/', '', asm or '')
    return all(re.search(r'\bsltiu?\s+\$\w+\s*,\s*\$\w+\s*,\s*(?:0x' + hex(n)[2:] + '|' + str(n) + r')\b', lines, re.I)
               for n in (20, 28, 92))


def _block(clean, opening, end):
    if opening >= end or clean[opening] != '{':
        return None
    finish = close(clean, opening, '{', '}')
    return finish if finish and finish <= end else None


def variants(source, name, asm, header=''):
    part = view(source, name)
    if not part or not _witness(asm) or re.search(r'\b(?:goto|volatile|asm|__asm__)\b', part.clean[part.opening:part.end]):
        return []
    pattern = re.compile(r'\bif\s*\(\s*(?P<var>' + IDENT + r')\s*<\s*(?:0x1[cC]|28)\s*\)\s*\{')
    result = []
    for match in pattern.finditer(part.clean, part.opening + 1, part.end):
        v = re.escape(match['var'])
        context = source + '\n' + (header or '')
        declaration = re.search(r'(?m)^\s*(s32|int|u8|u32)\s+' + v + r'\s*;', part.clean[part.opening:match.start()])
        if not declaration or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+(?:' + v + '|' + declaration[1] + r')\b', context):
            continue
        if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b' + declaration[1] + r'\s*;', context):
            continue
        left_open = match.end() - 1
        left_end = _block(part.clean, left_open, part.end)
        if not left_end:
            continue
        low = re.fullmatch(r'\s*if\s*\(\s*' + v + r'\s*<\s*(?:0x14|20)\s*\)\s*switch\s*\(\s*' + v + r'\s*\)\s*\{(?P<body>.*)\}\s*', part.clean[left_open + 1:left_end - 1], re.S)
        if not low or re.search(r'\bdefault\s*:', low['body']):
            continue
        labels = re.findall(r'\bcase\s+(0[xX][0-9a-fA-F]+|\d+)\s*:', low['body'])
        if {int(label, 0) for label in labels} != {7, 10, 16} or len(labels) != 3:
            continue
        nxt = re.match(r'\s*else\s+if\s*\(\s*' + v + r'\s*!=\s*(?:0x5[bB]|91)\s*\)\s*\{', part.clean[left_end:part.end])
        if not nxt:
            continue
        high_open = left_end + nxt.end() - 1
        high_end = _block(part.clean, high_open, part.end)
        if not high_end:
            continue
        branch = re.fullmatch(r'\s*if\s*\(\s*' + v + r'\s*==\s*(?:0x40|64)\s*\)\s*\{(?P<body>.*)\}\s*', part.clean[high_open + 1:high_end - 1], re.S)
        tail = re.match(r'\s*else\s*\{', part.clean[high_end:part.end])
        if not branch or not tail:
            continue
        last_open = high_end + tail.end() - 1
        last_end = _block(part.clean, last_open, part.end)
        if not last_end:
            continue
        if re.search(r'\b(?:break|continue|case|default)\b', branch['body'] + part.clean[last_open + 1:last_end - 1]):
            continue
        low_base = left_open + 1 + low.start('body')
        low_text = source[low_base:low_base + len(low['body'])]
        branch_base = high_open + 1 + branch.start('body')
        branch_text = source[branch_base:branch_base + len(branch['body'])]
        last_text = source[last_open + 1:last_end - 1]
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, match.start()) + 1:match.start()]).group()
        for include_93 in (False, True):
            labels = ''.join(f'{indent}    case {n}:\n' for n in (list(range(20, 28)) + ([93] if include_93 else [])))
            text = (f'switch ({match["var"]}) {{{low_text}{labels}{indent}        break;\n'
                    f'{indent}    case 0x40: {{{branch_text}{indent}    }} break;\n'
                    f'{indent}    case 0x5B: {{{last_text}{indent}    }} break;\n{indent}}}')
            result.append((FAMILY, edit(source, [(match.start(), last_end, text)])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',), 'order': 40}
