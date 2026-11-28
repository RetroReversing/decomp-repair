"""Flatten an inverted outer if around a complete inner if/else.

A KMC MIPS O1 state machine scored 550 until its nested error check was
written as an equal-case-first if/else-if ladder; that child scored 415.
Every condition is still evaluated once and the inner arm blocks stay intact.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'flatten_inverted_if_ladder'
LIMIT = 12


def _block(clean, after, limit):
    hit = re.match(r'\s*{', clean[after:limit])
    if not hit:
        return None
    opening = after + hit.end() - 1
    end = close(clean, opening, '{', '}')
    return (opening, end) if end and end <= limit else None


def variants(source, name, header=''):
    part = view(source, name)
    context = source + '\n' + header
    if not part or re.search(r'\b__(?:LINE|COUNTER)__\b', context):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')\b', context))
    clean = part.clean
    result = []
    pattern = rf'\bif\s*\(\s*([^(){{}};]+?)\s*!=\s*({NUMBER})\s*\)'
    for hit in re.finditer(pattern, clean[part.opening:part.end]):
        start, after = part.opening + hit.start(), part.opening + hit.end()
        outer = _block(clean, after, part.end)
        if not outer:
            continue
        inner = re.match(r'\s*if\s*\(', clean[outer[0] + 1:outer[1] - 1])
        if not inner:
            continue
        paren = outer[0] + 1 + inner.end() - 1
        inner_cond = close(clean, paren)
        inner_yes = _block(clean, inner_cond, outer[1] - 1) if inner_cond else None
        if not inner_yes:
            continue
        els = re.match(r'\s*else\b', clean[inner_yes[1]:outer[1] - 1])
        inner_no = _block(clean, inner_yes[1] + els.end(), outer[1] - 1) if els else None
        if not inner_no or clean[inner_no[1]:outer[1] - 1].strip():
            continue
        outer_else = re.match(r'\s*else\b', clean[outer[1]:part.end])
        outer_no = _block(clean, outer[1] + outer_else.end(), part.end) if outer_else else None
        if not outer_no:
            continue
        # No macro can inject a label or control flow into the three moved blocks.
        affected = clean[start:outer_no[1]]
        if set(re.findall(IDENT, affected)) & macros or re.search(r'(?m)^\s*#|\b(?:goto|case|default)\b|(?<![\w?:])' + IDENT + r'\s*:(?!:)', affected):
            continue
        lhs = source[part.opening + hit.start(1):part.opening + hit.end(1)].strip()
        rhs = source[part.opening + hit.start(2):part.opening + hit.end(2)]
        cond = source[paren + 1:inner_cond - 1]
        text = (f'if ({lhs} == {rhs}) ' + source[outer_no[0]:outer_no[1]]
                + f' else if ({cond}) ' + source[inner_yes[0]:inner_yes[1]]
                + ' else ' + source[inner_no[0]:inner_no[1]])
        result.append((FAMILY, edit(source, [(start, outer_no[1], text)])))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
