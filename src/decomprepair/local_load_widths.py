"""Locals that only ever hold one narrow load, declared at the load's width or as `s32`, and a search's symbol base.

load_width_local
    A local assigned only from narrow reads (`x = *((s8 *) (...));`, all the same type T of s8/u8/s16/u16) is a QI/HI
    pseudo when declared T (the load goes to a temporary and a `move` copies it in, and the store of a sum through it is
    in that width) and an SI pseudo when declared `s32` (the load is the local). Which one the game had decides copies,
    registers and stale frame slots. On a 1300-instruction KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) controller
    routine three such locals took both ways in turn: the index `s32` (610 -> 540), the step and the loop's start `s8`
    (420 -> 290, and with the rest of the match the frame's 8-byte slot). The symbol bases come first, then all the
    narrow locals narrow and all of them wide, then each local at its other width.

symbol_base_inline
    `__base_SYM = SYM;` (a search's cached symbol address in a local) written out: every use of the local reads `SYM`
    again. In a loop the cached base is hoisted into a saved register the target never spends (7645 -> 7550 there).

The exact judge decides every child."""
import re

from .csource import _blank, find

FAMILY_WIDTH = 'load_width_local'
FAMILY_BASE = 'symbol_base_inline'
FAMILIES = (FAMILY_WIDTH, FAMILY_BASE)
LIMIT = 16
IDENT = r'[A-Za-z_]\w*'
_NARROW = ('s8', 'u8', 's16', 'u16')


def _span(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[span[0]:span[1]])
    return (span[0] + head.end() - 1, span[1]) if head else None


def _declaration(var):
    return re.compile(rf'^(?P<i>[ \t]*)(?P<t>[su](?:8|16|32)|int)[ \t]+{re.escape(var)}[ \t]*;', re.M)


def _width_sites(source, span):
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    sites = []
    for decl in re.finditer(rf'^[ \t]*(?P<t>[su](?:8|16|32)|int)[ \t]+(?P<v>{IDENT})[ \t]*;', body, re.M):
        var, declared = decl['v'], decl['t']
        sets = list(re.finditer(rf'(?<![\w.>]){re.escape(var)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)\s*(?P<rhs>[^;]*);', body))
        if not sets or re.search(rf'&\s*{re.escape(var)}\b|\+\+\s*{re.escape(var)}\b|{re.escape(var)}\s*(?:\+\+|--)', body):
            continue
        kinds = set()
        for s in sets:
            if not re.match(rf'(?<![\w.>]){re.escape(var)}\s*=(?!=)', s.group(0)):
                kinds.add(None)
                continue
            m = (re.fullmatch(r'\*\s*\(\s*\(\s*([su](?:8|16))\s*\*\s*\).*\)', s['rhs'].strip(), re.S)
                 or re.fullmatch(r'\(\s*\(\s*Field_([su](?:8|16))\s*\*\s*\).*->\s*v', s['rhs'].strip(), re.S))
            kinds.add(m[1] if m else None)
        if len(kinds) != 1 or None in kinds:
            continue
        load = kinds.pop()
        other = 's32' if declared == load else load
        if declared not in (load, 's32', 'int'):
            other = load
        sites.append((var, declared, other, load))
    return sites


def _retype(source, span, changes):
    for var, new in changes:
        decl = _declaration(var).search(source, span[0])
        if not decl or decl.start() > span[1]:
            continue
        source = source[:decl.start('t')] + new + source[decl.end('t'):]
    return source


def _bases(source, span):
    clean = _blank(source)
    out = []
    for hit in re.finditer(rf'^[ \t]*(?P<v>__base_\w+)\s*=\s*(?P<s>{IDENT})\s*;[ \t]*\n', clean[:span[1]], re.M):
        if hit.start() < span[0]:
            continue
        var, sym = hit['v'], hit['s']
        if len(re.findall(rf'(?<![\w.>]){re.escape(var)}\s*=(?!=)', clean[span[0]:span[1]])) != 1:
            continue
        child = source[:hit.start()] + source[hit.end():]
        child = re.sub(rf'^[ \t]*[\w ]+?\*?[ \t]*\*?{re.escape(var)}[ \t]*;[ \t]*\n', '', child, count=1, flags=re.M)
        child = re.sub(rf'(?<![\w.>]){re.escape(var)}\b', sym, child)
        out.append((FAMILY_BASE, child))
    return out


def variants(source, name):
    span = _span(source, name)
    if not span:
        return []
    out = _bases(source, span)
    sites = _width_sites(source, span)
    if len(sites) > 1:
        out.append((FAMILY_WIDTH, _retype(source, span, [(var, load) for var, _, _, load in sites])))
        out.append((FAMILY_WIDTH, _retype(source, span, [(var, 's32') for var, _, _, _ in sites])))
    for var, _, other, _ in sites:
        out.append((FAMILY_WIDTH, _retype(source, span, [(var, other)])))
    seen, unique = set(), []
    for family, child in out:
        if child != source and child not in seen:
            seen.add(child)
            unique.append((family, child))
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
