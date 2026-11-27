"""A narrow read the target loads with the other sign: `lh` where the source casts to `u16` (or `lhu` for `s16`).

`*(u16 *)(base + idx * 0x270) == 1` compiles to `lhu`, `*(s16 *)(...) == 1` to `lh` (SN GCC 2.7.2 -O1, measured by
compiling both; likewise `lbu`/`lb`, and an ordering compare adds `sltu` against `slt`). m2c and the first draft pick
the sign from the one use they saw, so a record's halfword compared with a small constant can stay one opcode off while
every other instruction matches. The target's loads say which it was: for a width whose loads in the target are all of
one sign, every read of the other sign in a compare (`*(T *)(...)` or `M2C_FIELD(b, T *, off)` next to `==`, `!=`, `<`,
`>`, `<=` or `>=`) is changed to the target's type, all together, then one each (the first 6). A function whose target
loads that width both ways gets only the per-read children, both directions. Measured on a one-function matching case
(an SN GCC 2.7.2 -O1 halfword compared with 1): `lhu` against the target's `lh`, exact once the cast was `s16`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'compare_load_sign'
FAMILIES = (FAMILY,)
LIMIT = 6

SIGNED = {'u8': 's8', 'u16': 's16'}
UNSIGNED = {'s8': 'u8', 's16': 'u16'}
WIDTH = {'s8': 'b', 'u8': 'b', 's16': 'h', 'u16': 'h'}
OPS = re.compile(r'\b(lbu|lb|lhu|lh)\s+\$\w+\s*,')
COMPARE = r'(?:==|!=|<=|>=|<|>)'
READ = re.compile(r'\*\s*\(\s*(?P<type>[su](?:8|16))\s*\*\s*\)|\bM2C_FIELD\s*\(')


def _signs(asm):
    found = {'b': set(), 'h': set()}
    for op in OPS.findall(asm):
        found[op[1]].add('u' if op.endswith('u') else 's')
    return found


def _read_end(clean, m):
    """Where the read that starts at `m` ends (just past its operand), and the type's span."""
    if m['type']:
        at = m.end()
        while at < len(clean) and clean[at].isspace():
            at += 1
        if clean[at:at + 1] == '(':
            end = close(clean, at)
            return (end or None), (m.start('type'), m.end('type'))
        m2 = re.compile(r'[\w.>-]+(?:\[[^\]]*\])?').match(clean, at)
        return (m2.end() if m2 else None), (m.start('type'), m.end('type'))
    stop = close(clean, m.end() - 1)
    typed = stop and re.search(r',\s*(?P<type>[su](?:8|16))\s*\*\s*,', clean[m.end():stop])
    if not typed:
        return None, None
    return stop, (m.end() + typed.start('type'), m.end() + typed.end('type'))


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    signs = _signs(asm)
    clean = _blank(source)
    body_start, body_end = span
    sites = []  # (start, end, new type, certain)
    for m in READ.finditer(clean, body_start, body_end):
        end, where = _read_end(clean, m)
        if not end:
            continue
        kind = clean[where[0]:where[1]]
        before = clean[max(body_start, m.start() - 6):m.start()]
        after = clean[end:end + 6]
        if not (re.match(r'\s*' + COMPARE, after) or re.search(COMPARE + r'\s*\(?\s*$', before)):
            continue
        have = signs[WIDTH[kind]]
        if not have:
            continue
        flip = SIGNED[kind] if kind in SIGNED else UNSIGNED[kind]
        if kind in SIGNED and 'u' not in have and 's' in have:
            sites.append((where[0], where[1], flip, True))
        elif kind in UNSIGNED and 's' not in have and 'u' in have:
            sites.append((where[0], where[1], flip, True))
        elif len(have) == 2:
            sites.append((where[0], where[1], flip, False))
    if not sites:
        return []

    def apply(chosen):
        text = source
        for a, b, new, _ in sorted(chosen, reverse=True):
            text = text[:a] + new + text[b:]
        return text
    certain = [s for s in sites if s[3]]
    result = [apply(certain)] if certain else []
    if len(sites) > 1 or not certain:
        result += [apply([s]) for s in sites[:LIMIT]]
    return [(FAMILY, text) for text in dict.fromkeys(result) if text != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
