"""Recover a relocated cursor advance and the order of a guard's equal initializers."""

import re

from .integer_repair_support import IDENT, edit, view
from .loaded_byte_repairs import declarators

FAMILY = 'measured_cursor_publish'
ZERO_FAMILY = 'measured_equal_zero_initializers'
REG = r'\$\w+'
IMM = r'(?:0[xX][0-9a-fA-F]+|0|[1-9][0-9]*)'
ADVANCE = re.compile(rf'addiu (?P<reg>{REG}), (?P=reg), (?P<step>{IMM})')
SYMBOL_STORE = re.compile(rf'sw (?P<reg>{REG}), %lo\((?P<global>{IDENT})\)\(\$at\)')
ZERO = re.compile(r'move (\$a[123]), \$zero')
PUBLISH = re.compile(
    rf'(?<=[;{{}}])\s*(?P<global>{IDENT})\s*=\s*(?P<cursor>{IDENT})\s*;'
    rf'\s*{IDENT}\s*=\s*{IDENT}\s*;\s*(?P=cursor)\s*\+=\s*(?P<step>{IMM})\s*;'
    rf'\s*{IDENT}\s*\([^;{{}}]*\)\s*;'
)
INITIALIZERS = re.compile(
    rf'(?<=[;{{}}])\s*(?P<outer>{IDENT})\s*=\s*0\s*;'
    rf'\s*if\s*\(\s*{IDENT}\s*&\s*{IMM}\s*\)\s*{{\s*(?P<inner>{IDENT})\s*=\s*0\s*;'
    rf'(?:\s*{IDENT}\s*=\s*{IMM}\s*;){{0,3}}\s*goto\s+(?P<label>{IDENT})\s*;\s*}}'
    rf'\s*if\s*\(\s*{IDENT}\s*&\s*{IMM}\s*\)\s*{{\s*return\s*;\s*}}\s*{{'
)
SCALAR = r'(?:s32|u32|int|unsigned\s+int)'


def _cursor_sites(rows):
    """A missing increment beside the same relocation and store in both builds."""
    for first, high, store in zip(rows, rows[1:], rows[2:]):
        advance = ADVANCE.fullmatch(first[1])
        wanted, actual = (SYMBOL_STORE.fullmatch(op) for op in store[1:])
        if (first[2] or not advance or not wanted or not actual
                or advance['reg'] != wanted['reg'] or wanted['global'] != actual['global']
                or high[1] != high[2] or high[1] != f'lui $at, %hi({wanted["global"]})'):
            continue
        yield wanted['global'], int(advance['step'], 0)


def _publish(source, part, rows):
    sites = set(_cursor_sites(rows))
    if not sites:
        return []
    result = []
    for m in PUBLISH.finditer(part.clean, part.opening + 1, part.end):
        symbol, cursor, step = m['global'], m['cursor'], m['step']
        if (symbol, int(step, 0)) not in sites or not int(step, 0):
            continue
        if not re.search(rf'(?m)^\s*extern\s+void\s*\*\s*(?:volatile\s+)?{symbol}\s*;', part.clean[:part.opening]):
            continue
        if (len(declarators(part.clean, symbol)) != 1 or len(declarators(part.clean, cursor)) != 1
                or not re.search(rf'(?<=[;{{}}])\s*void\s*\*\s*{cursor}\s*;', part.clean[part.opening:m.start()])):
            continue
        result.append((FAMILY, edit(source, [(*m.span('cursor'), f'{cursor} + {step}')])))
    return result[:4]


def _zero_orders(source, part, rows):
    pairs = [(a[1], b[1]) for _, target, candidate in rows
             if (a := ZERO.fullmatch(target)) and (b := ZERO.fullmatch(candidate)) and a[1] != b[1]]
    if not any((b, a) in pairs for a, b in pairs):
        return []
    result = []
    for m in INITIALIZERS.finditer(part.clean, part.opening + 1, part.end):
        outer, inner, label = m['outer'], m['inner'], m['label']
        if outer == inner:
            continue
        any_ref = re.compile(rf'\b(?:{outer}|{inner})\b')
        guard = part.clean[m.start():m.end()]
        if len(any_ref.findall(guard)) != 2:
            continue
        before = part.clean[part.opening:m.start()]
        if not all(re.search(rf'(?<=[;{{}}])\s*(?:register\s+)?{SCALAR}\s+{name}\s*;', before)
                   for name in (outer, inner)) or re.search(rf'&\s*\(*\s*(?:{outer}|{inner})\b', part.body):
            continue
        reset = part.clean[m.end():part.end].partition(label + ':')[0]
        if re.search(r'[{}]|\b(?:goto|return|if|switch|for|while)\b', reset):
            continue
        # The false path either returns or overwrites both locals before their first uses.
        assigns = re.findall(rf'\b({outer}|{inner})\s*=\s*{IMM}\s*;', reset)
        if set(assigns) != {outer, inner} or len(assigns) != len(any_ref.findall(reset)):
            continue
        result.append((ZERO_FAMILY, edit(source, [(*m.span('outer'), inner), (*m.span('inner'), outer)])))
    return result[:4]


_WORD_STORE = re.compile(rf'sw (?P<value>{REG}), (?P<offset>{IMM})?\((?P<base>{REG})\)')

def _raw_word(suffix):
    return (
        rf'\(\s*\*\s*\(\s*s32\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*'
        rf'\(\s*(?P<base{suffix}>{IDENT})\s*\)\s*\+\s*(?P<offset{suffix}>{IMM})'
        rf'\s*\)\s*\)\s*=\s*(?P<value{suffix}>{IMM})\s*;'
    )


def _word_store_orders(source, part, rows):
    """Two nonvolatile, disjoint word stores with literal right-hand sides."""
    reversed_offsets = set()
    for left, right in zip(rows, rows[1:]):
        if left[1] != right[2] or right[1] != left[2]:
            continue
        first, second = (_WORD_STORE.fullmatch(row[1]) for row in (left, right))
        if (first and second and first['base'] == second['base']
                and first['value'] != '$zero' and second['value'] == '$zero'):
            reversed_offsets.add((int(first['offset'] or '0', 0), int(second['offset'] or '0', 0)))
    if not reversed_offsets:
        return []
    first, second = _raw_word(0), _raw_word(1)
    choices = []
    for match in re.finditer(rf'(?<=[;{{}}])\s*(?P<first>{first})\s*(?P<second>{second})',
                             part.clean, re.M):
        if not part.opening < match.start() < match.end() <= part.end:
            continue
        if (match['base0'] != match['base1'] or int(match['value0'], 0) != 0 or int(match['value1'], 0) == 0):
            continue
        base = match['base0']
        if (len(declarators(part.clean, base)) != 1 or not re.search(
                rf'\bvoid\s*\*\s*{base}\s*;', part.clean[part.opening:match.start()])):
            continue
        offsets = int(match['offset1'], 0), int(match['offset0'], 0)
        if offsets not in reversed_offsets or abs(offsets[0] - offsets[1]) < 4 or any(offset % 4 for offset in offsets):
            continue
        start, end = match.span('first')
        other_start, other_end = match.span('second')
        gap = source[end:other_start]
        if not gap.isspace():
            continue
        choices.append(('measured_adjacent_word_store_order',
                        edit(source, [(start, other_end, source[other_start:other_end] + gap + source[start:end])])))
    return choices if len(choices) == 1 else []


def variants(source, name, rows):
    """Try the independently evidenced cursor and initialization repairs."""
    if not rows or not (part := view(source, name)):
        return []
    return _publish(source, part, rows) + _zero_orders(source, part, rows) + _word_store_orders(source, part, rows)
