"""A small `switch` written as an `if`/`else if` chain that reads its value again at each test.

GCC 2.7.2 loads a `switch`'s value once and compares it in a register. A target that loads the global again before
the second compare (`lbu`, `beqz`, `li 1`, `lui`, `lbu`, `bne`) was written `if (g == 0) { .. } else if (g == 1)
{ .. }`: under KMC GCC 2.7.2 `-G0 -mips3 -mgp32 -mfp32 -O1`, which does not carry the first load across the branch.
A 146-instruction N64 drawing function with a two-case switch on a byte: 415 -> 0.

switch_if_chain
    Each `switch` of two or three single-label cases that all end in `break`, written as the chain (a `default` becomes
    the final `else`); and all of them at once. Only a plain value (a name, a member, an array element) is read twice.
"""
import re

from .c_scan import close
from .csource import _blank, find

FAMILY = 'switch_if_chain'
FAMILIES = (FAMILY,)
LIMIT = 8
CASES = 3
_SWITCH = re.compile(r'\bswitch\s*\(')
_VALUE = re.compile(r'\*?\s*[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*|\s*\[\s*\w+\s*\])*')
_LABEL = re.compile(r'\b(?:case\s+(?P<value>-?\s*(?:0[xX][0-9a-fA-F]+|\d+|[A-Z_][A-Z0-9_]*))|(?P<default>default))\s*:')
_BREAK = re.compile(r'\bbreak\s*;')
_JUMPS = re.compile(r'\b(?:break|case|default|goto)\b|\b[A-Za-z_]\w*\s*:(?!:)\s*[;{]')


def _arms(source, clean, opening, end):
    """[(value or None for default, body text)] of the switch block, or None when a case is not a plain arm."""
    depth, labels = 0, []
    for at in range(opening + 1, end):
        depth += (clean[at] == '{') - (clean[at] == '}')
        hit = _LABEL.match(clean, at) if depth == 0 and not clean[at - 1].isalnum() else None
        if hit:
            labels.append(hit)
    if not labels or clean[opening + 1:labels[0].start()].strip():
        return None
    arms = []
    for index, label in enumerate(labels):
        stop = labels[index + 1].start() if index + 1 < len(labels) else end
        begin = label.end()
        text = clean[begin:stop]
        braced = text.strip().startswith('{') and close(clean, begin + text.index('{')) == begin + len(text.rstrip()) - 1
        if braced:  # `case K: { ...; break; }`
            stop = begin + len(text.rstrip()) - 1
            begin = begin + text.index('{') + 1
        body = clean[begin:stop].rstrip()
        last = list(_BREAK.finditer(body))
        if last and not body[last[-1].end():].strip():
            body = body[:last[-1].start()].rstrip()
        elif index + 1 < len(labels):
            return None  # falls through into the next case
        if _JUMPS.search(body):
            return None
        value = None if label['default'] else label['value']
        arms.append((value, source[begin:begin + len(body)].strip()))
    cases = [arm for arm in arms if arm[0] is not None]
    if not 2 <= len(cases) <= CASES or any(not text for _, text in cases):
        return None
    if any(value is None for value, _ in arms[:-1]):
        return None  # a default that is not last would change the order of the arms
    return arms


def _sites(source, clean, lo, hi):
    sites = []
    for hit in _SWITCH.finditer(clean, lo, hi):
        shut = close(clean, hit.end() - 1, '(', ')')
        if shut < 0:
            continue
        opening = shut + 1 + len(clean[shut + 1:hi]) - len(clean[shut + 1:hi].lstrip())
        end = close(clean, opening) if clean.startswith('{', opening) else -1
        value = clean[hit.end():shut].strip()
        if end < 0 or not _VALUE.fullmatch(value):
            continue
        arms = _arms(source, clean, opening, end)
        if not arms:
            continue
        value = source[hit.end():shut].strip()
        parts = [f'{{ {text} }}' if case is None else f'if ({value} == {case}) {{ {text} }}' for case, text in arms]
        sites.append((hit.start(), end + 1, ' else '.join(parts)))
    return sites


def _apply(source, sites):
    for start, end, text in reversed(sites):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span or 'switch' not in source:
        return []
    clean = _blank(source)
    sites = _sites(source, clean, span[0], span[1])
    apart = []
    for site in sites:
        if not apart or site[0] >= apart[-1][1]:
            apart.append(site)
    picks = ([apart] if len(apart) > 1 else []) + [[site] for site in sites]
    return [(FAMILY, _apply(source, pick)) for pick in picks[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
