"""A run of member stores to one record written in the order the record declares its members.

On a 773-instruction N64 drop-shadow renderer (SN64 GCC 2.8.1, `sn-n64-281 -G0 -mips3 -O2 -mgas -meb -mcpu=VR4300
-mhard-float -mfp32`) each vertex was filled with ten stores through `VERTS[buf][base + k]` written in m2c's order
(`ob[0]`, `ob[1]`, `flag`, `ob[2]`, `tc[0]`, `cn[0]`, `tc[1]`, `cn[1..3]`). The scheduler keeps independent stores close to
their source order, and the target's order is the struct's own (`ob[0..2]`, `flag`, `tc[0..1]`, `cn[0..3]`): 1020 -> 0
once the stores followed the declaration (an exhaustive grid of the three groups' orders found the same order best). The
game's code fills a record member by member, top to bottom, more often than m2c's instruction order suggests.

member_store_declaration_order
    Three or more consecutive statements `BASE.m = v;` / `BASE->m = v;` (an optional constant subscript after `m`) with
    the same BASE text, whose members all belong to exactly one struct declared in the source or header, and whose
    values read none of those members, call nothing and change nothing: the run sorted by the members' declaration
    order (then by subscript). One child per run that moves, and one with every run.

Hypothesis from that match; the exact judge decides.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, view

FAMILY = 'member_store_declaration_order'
FAMILIES = (FAMILY,)
LIMIT = 6
_STORE = re.compile(rf'^(?P<indent>[ \t]*)(?P<base>[^;=\n]*?)(?P<op>\.|->)\s*(?P<m>{IDENT})\s*(?:\[\s*(?P<sub>\d+|0[xX][0-9A-Fa-f]+)\s*\])?'
                    r'\s*=(?!=)\s*(?P<v>[^;\n]*);[ \t]*$')
_STRUCT = re.compile(r'\b(?:typedef\s+)?struct\s*\w*\s*{(?P<body>[^{}]*)}\s*(?P<name>\w*)\s*;')



def _layouts(text):
    out = []
    for hit in _STRUCT.finditer(text):
        members = []
        for decl in hit['body'].split(';'):
            if not decl.strip() or '(' in decl:
                continue
            pieces = re.sub(r'\[[^\]]*\]', '', decl).split(',')
            for piece in pieces:
                names = re.findall(IDENT, piece)
                if names:
                    members.append(names[-1])
        if members:
            out.append(members)
    return out


def _key(layouts, members):
    found = [layout for layout in layouts if all(m in layout for m in members)]
    if len(found) != 1:
        return None
    return {m: i for i, m in enumerate(found[0])}


def _runs(lines, start, stop):
    run = []
    for number in range(start, stop):
        hit = _STORE.match(lines[number])
        if hit and run and hit['base'].strip() == run[-1][1]['base'].strip():
            run.append((number, hit))
            continue
        if len(run) >= 3:
            yield run
        run = [(number, hit)] if hit else []
    if len(run) >= 3:
        yield run


def _sorted(run, order):
    members = {hit['m'] for _, hit in run}
    for _, hit in run:
        value = hit['v']
        if (re.search(rf'\b{IDENT}\s*\(', value) or re.search(r'\+\+|--', value)
                or re.search(r'(?<![=!<>])=(?!=)', value)):
            return None
        if any(re.search(rf'(?:\.|->)\s*{re.escape(m)}\b', value) for m in members):
            return None

    def rank(item):
        hit = item[1]
        return order[hit['m']], int(hit['sub'], 0) if hit['sub'] else -1
    ordered = sorted(run, key=rank)
    return None if [n for n, _ in ordered] == [n for n, _ in run] else ordered


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    layouts = _layouts(_blank(header or '') + '\n' + part.clean[:part.opening])
    if not layouts:
        return []
    lines = source.split('\n')
    first = source.count('\n', 0, part.opening) + 1
    last = source.count('\n', 0, part.end)
    clean_lines = part.clean.split('\n')
    moves = []
    for run in _runs(clean_lines, first, last):
        order = _key(layouts, [hit['m'] for _, hit in run])
        if order is None:
            continue
        ordered = _sorted(run, order)
        if ordered:
            moves.append(([n for n, _ in run], [n for n, _ in ordered]))
    out = []
    def apply(chosen):
        new = list(lines)
        for slots, ordered in chosen:
            texts = [lines[n] for n in ordered]
            for slot, text in zip(slots, texts):
                new[slot] = text
        return '\n'.join(new)
    for move in moves[:LIMIT]:
        out.append((FAMILY, apply([move])))
    if len(moves) > 1:
        out.append((FAMILY, apply(moves[:LIMIT])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
