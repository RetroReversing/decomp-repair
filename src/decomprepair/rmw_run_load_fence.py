"""rmw_run_load_fence: three field updates in a row, one value read early and the next read held behind a scope.

KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) target shape, three bytes of one record each lowered by a constant with
only two registers: `lbu v0,X; lbu v1,Y; addiu v0; sb v0,X; lbu v0,Z; addiu v1; sb v1,Y; addiu v0; sb v0,Z`. Written as
three compound updates the first scheduler reads all three bytes first (three registers: they cannot alias). The source
that gives the target reads Y before X is updated, and reads Z at the start of a one-shot scope that also stores Y:

    y = rec[Y];
    rec[X] -= K;
    do { z = rec[Z]; rec[Y] = y - K; } while (0);
    rec[Z] = z - K;

The scope's loop note makes the insn after it depend on every insn before it (`sched_analyze`, the
`NOTE_INSN_LOOP_BEG/END` case of sched.c, read from the source), so Z's read stays behind X's store; inside the scope the
second scheduler moves Y's add into the load's delay slot. The register outcome is measured on one 39-instruction
function (saved best 60 -> 0); grids of every order of three compound updates, and of one-shot scopes around single
statements, stayed above 0.

The shape: a run of exactly three updates `L = L op K` of distinct, non-overlapping fields at constant offsets from one
base (or three distinct globals), written as compound assignments, as `L = (T) (L - K);`, or split through a temporary
used nowhere else (`t = L; ... L = (T) (t - K);`), with or without `do { } while (0);` or a bare block around some of
them. One child
per choice of which update is whole, which is read early and which is read inside the scope (six).
"""
import re
from itertools import permutations

from .integer_repair_support import edit, view

FAMILY = 'rmw_run_load_fence'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
_TYPE = r'(?:[su](?:8|16|32)|(?:unsigned\s+|signed\s+)?(?:char|short|int))'
_SIZES = {'u8': 1, 's8': 1, 'char': 1, 'u16': 2, 's16': 2, 'short': 2, 'u32': 4, 's32': 4, 'int': 4}
_MEMBER = re.compile(rf'M2C_FIELD\(\s*(?P<base>{_ID})\s*,\s*(?P<type>{_TYPE})\s*\*\s*,\s*(?P<off>{_NUM})\s*\)')
_DEREF = re.compile(
    rf'\*\s*\(\s*(?P<type>{_TYPE})\s*\*\s*\)\s*\(\s*\(\s*(?:char|s8|u8)\s*\*\s*\)\s*\(?\s*(?P<base>{_ID})\s*\)?'
    rf'\s*\+\s*(?P<off>{_NUM})\s*\)')
_OPEN = re.compile(r'(?:do\s*)?\{\s*')  # a one-shot scope or a bare block: neither changes what the statements do
_CLOSE = re.compile(r'\}(?:\s*while\s*\(\s*0\s*\)\s*;)?\s*')
_STATEMENT = re.compile(r'(?P<lhs>[^;{}=]+?)\s*(?P<op>[-+|&^]?)=(?!=)\s*(?P<rhs>[^;{}]+);\s*')


def _number(text):
    return int(text.rstrip('uUlL'), 0)


def _squash(text):
    return re.sub(r'\s+', '', text)


def _bare(text):
    """`text` without the parentheses that wrap all of it, as `(*(u8 *)(...))` is spelled."""
    text = text.strip()
    while text.startswith('(') and text.endswith(')'):
        depth = 0
        for at, char in enumerate(text):
            depth += (char == '(') - (char == ')')
            if not depth:
                break
        if at != len(text) - 1:
            return text
        text = text[1:-1].strip()
    return text


def _place(text, source, header):
    """(key, base, offset, type) of an lvalue the rewrite can prove apart from its neighbours, else None."""
    text = _bare(text)
    hit = _MEMBER.fullmatch(text) or _DEREF.fullmatch(text)
    if hit:
        kind = ' '.join(hit['type'].split())
        if kind.split()[-1] not in _SIZES:
            return None
        return _squash(text), hit['base'], _number(hit['off']), kind
    if re.fullmatch(_ID, text):
        found = re.search(rf'\bextern\s+(?P<type>{_TYPE})\s+{text}\s*;', (header or '') + '\n' + source)
        if found:
            return text, '&' + text, 0, ' '.join(found['type'].split())
    return None


def _value(rhs):
    """`(T) (A op K)` or `A op K` as (A, op, K)."""
    text = rhs.strip()
    cast = re.fullmatch(rf'\(\s*{_TYPE}\s*\)\s*\((.*)\)', text, re.S)
    if cast:
        text = cast[1].strip()
    hit = re.fullmatch(rf'(?P<a>.+?)\s*(?P<op>[-+|&^])\s*(?P<k>-?{_NUM})', text, re.S)
    return (hit['a'].strip(), hit['op'], hit['k']) if hit else None


def _statement(match, source, header, loads):
    """('load', temp, place) or ('update', place, op, K, temp or None), else None."""
    lhs, op, rhs = match['lhs'].strip(), match['op'], match['rhs'].strip()
    if not op and re.fullmatch(_ID, lhs):
        place = _place(rhs, source, header)
        if place and not _place(lhs, source, header):
            return 'load', lhs, place
    place = _place(lhs, source, header)
    if not place:
        return None
    if op:
        return ('update', place, op, rhs, None) if re.fullmatch(rf'-?{_NUM}', rhs) else None
    value = _value(rhs)
    if not value:
        return None
    first, operator, constant = value
    if first in loads:
        return ('update', place, operator, constant, first) if loads[first][0] == place[0] else None
    other = _place(first, source, header)
    return ('update', place, operator, constant, None) if other and other[0] == place[0] else None


def _runs(source, clean, start, end, header):
    """Maximal runs of loads, updates and one-shot scope braces: [(items, tokens)] with tokens (kind, from, to)."""
    at = start
    while at < end:
        tokens, items, loads = [], [], {}
        while at < end:
            gap = re.compile(r'\s*').match(clean, at).end()
            opening, closing = _OPEN.match(clean, gap), _CLOSE.match(clean, gap)
            if opening or closing:
                found = opening or closing
                tokens.append(('open' if opening else 'close', gap, found.end()))
                at = found.end()
                continue
            found = _STATEMENT.match(clean, gap)
            item = found and _statement(found, source, header, loads)
            if not item:
                break
            if item[0] == 'load':
                loads[item[1]] = item[2]
            items.append(item)
            tokens.append(('statement', gap, found.end()))
            at = found.end()
        if items:
            yield items, tokens
        step = re.compile(r'[;{}]').search(clean, at)
        at = step.end() if step else end


def _span(tokens):
    """The text span of the statements, widened over scope braces until they balance, or None."""
    marks = [i for i, token in enumerate(tokens) if token[0] == 'statement']
    first, last = marks[0], marks[-1]
    while True:
        depth = low = 0
        for kind, _, _ in tokens[first:last + 1]:
            depth += (kind == 'open') - (kind == 'close')
            low = min(low, depth)
        if low < 0:
            at = next((i for i in range(first - 1, -1, -1) if tokens[i][0] == 'open'), None)
            if at is None:
                return None
            first = at
        elif depth > 0:
            at = next((i for i in range(last + 1, len(tokens)) if tokens[i][0] == 'close'), None)
            if at is None:
                return None
            last = at
        else:
            return tokens[first][1], tokens[last][2]


def _updates(items, body):
    """The three independent updates of a run, as [(place, op, K)], or None."""
    updates = [item for item in items if item[0] == 'update']
    loads = [item for item in items if item[0] == 'load']
    if len(updates) != 3 or sorted(item[4] for item in updates if item[4]) != sorted(item[1] for item in loads):
        return None
    for _, temp, _ in loads:
        # its declaration, its load and its one use: anything else would lose its value with the rewrite
        if len(re.findall(rf'\b{temp}\b', body)) != 3:
            return None
    places = [item[1] for item in updates]
    if len({base for _, base, _, _ in places}) != 1:
        if not all(base.startswith('&') for _, base, _, _ in places) or len({key for key, *_ in places}) != 3:
            return None
    else:
        ranges = sorted((off, off + _SIZES[kind.split()[-1]]) for _, _, off, kind in places)
        if any(one[1] > two[0] for one, two in zip(ranges, ranges[1:])):
            return None
    return [(item[1], item[2], item[3]) for item in updates]


def _fresh(clean, base):
    name = base
    while re.search(rf'\b{name}\b', clean):
        name += '_'
    return name


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    if re.search(r'\bvolatile\b|\basm\b', body):
        return []
    out = []
    for items, tokens in _runs(source, clean, part.opening + 1, part.end - 1, header):
        updates = _updates(items, body)
        span = updates and _span(tokens)
        if not span:
            continue
        start, stop = span
        indent = source[source.rfind('\n', 0, start) + 1:start]
        indent = indent if not indent.strip() else '    '
        early, late = _fresh(clean, 'rmw_early'), _fresh(clean, 'rmw_late')
        for whole, first, second in permutations(updates):
            x, y, z = (source_text(source, clean, start, stop, place[0][0]) for place in (whole, first, second))
            lines = [f'{early} = {y};',
                     f'{x} {whole[1]}= {whole[2]};',
                     'do {',
                     f'    {late} = {z};',
                     f'    {y} = ({first[0][3]}) ({early} {first[1]} {first[2]});',
                     '} while (0);',
                     f'{z} = ({second[0][3]}) ({late} {second[1]} {second[2]});']
            text = ('\n' + indent).join(lines)
            if text == source[start:stop].rstrip():
                continue
            text += source[start + len(source[start:stop].rstrip()):stop]
            opening = part.opening + 1
            declare = f'\n    {first[0][3]} {early};\n    {second[0][3]} {late};'
            out.append((FAMILY, edit(source, [(opening, opening, declare), (start, stop, text)])))
    return list(dict.fromkeys(out))


def source_text(source, clean, start, stop, key):
    """The lvalue as the source spells it, found by its whitespace-free form."""
    pattern = re.compile(r'\s*'.join(re.escape(c) for c in key))
    found = pattern.search(clean, start, stop)
    return source[found.start():found.end()] if found else key


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 60}  # the registry: no caller wiring (registry.py)
