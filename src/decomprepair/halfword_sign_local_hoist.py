"""A halfword counter's sign-extended copy, taken in a word local right after the counter is read.

A timer or frame counter read as `u16 t = FIELD(p, u16 *, 0xC);`, stored back incremented, then tested against
constants after other work (`if ((s16) t == 0xF) ...  if ((s16) t == 0x1E) ...`) comes back from m2c with the
narrowing at each test, or (after `narrow_temp` repairs) as one `n = (s16) t;` just before the first test. The game
took the sign-extended copy at once, into a word local held in a saved register over the calls between
(`sll 16; sra 16` next to the load, `s3` live across both tests). Measured on a KMC GCC 2.7.2 (`-G0 -mips3 -mgp32
-mfp32 -O2`) 40-instruction N64 object update (285 -> 0 together with its `s16` second counter and callee argument
form, which other families supply): the `(s16)` copy set two statements before its first test.

Two shapes, one child each per placement (right after the counter's assignment, and after the statement that follows it):
- `copy`: a statement `n = (s16) t;` already in the body, `n` an integer local not used between the new place and the
  old one, `t` not assigned between them: it moves.
- `named`: two or more `(s16) t` in the body (no existing copy): a new `s32 t_s16;` is set at the new place and replaces
  them, when `t` is assigned once and never taken by address.
A candidate; the exact judge decides.
"""
import re

from .arm_block_support import statements
from .integer_repair_support import IDENT, edit, view

COPY = 'halfword_sign_copy_hoist'
NAMED = 'halfword_sign_named_copy'
FAMILIES = (COPY, NAMED)

NARROW = re.compile(rf'\(s16\)\s*(?P<t>{IDENT})\b')
COPY_STATEMENT = re.compile(rf'\A(?P<n>{IDENT})\s*=\s*\(s16\)\s*(?P<t>{IDENT})\s*;\Z')


def _assigns(text, name):
    return re.search(rf'(?<![\w.>&]){name}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{name}\b|\b{name}\s*(?:\+\+|--)', text)


def _line_start(source, at):
    return source.rfind('\n', 0, at) + 1


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    units = statements(clean, part.opening + 1, part.end - 1)
    out = []

    def add(family, text):
        if text != source and (family, text) not in out:
            out.append((family, text))

    def places(assign):
        found = [units[assign][1]]
        after = assign + 1
        if after < len(units) and '{' not in clean[units[after][0]:units[after][1]]:
            found.append(units[after][1])
        return found

    nl = clean.find('\n', part.opening) + 1
    head = re.match(r'[ \t]*', source[nl:])[0] or '    '
    for at, (start, end) in enumerate(units):
        copy = COPY_STATEMENT.match(clean[start:end])
        if not copy:
            continue
        t, n = copy['t'], copy['n']
        assign = [i for i in range(at) if re.match(rf'{t}\s*=(?!=)', clean[units[i][0]:units[i][1]])]
        if len(assign) != 1:
            continue
        for place in places(assign[0]):
            if place >= start:
                continue
            between = clean[place:start]
            if re.search(rf'\b{n}\b', between) or _assigns(between, t) or re.search(rf'&\s*{t}\b', clean[part.opening:part.end]):
                continue
            line = _line_start(source, start)
            indent = re.match(r'[ \t]*', source[line:])[0]
            row_end = source.find('\n', end) + 1 or len(source)
            add(COPY, edit(source, [(line, row_end, ''), (place, place, f'\n{indent}{n} = (s16) {t};')]))
    if out:
        return out
    uses = {}
    for hit in NARROW.finditer(clean, part.opening, part.end):
        uses.setdefault(hit['t'], []).append(hit)
    for t, hits in uses.items():
        if len(hits) < 2 or re.search(rf'&\s*{t}\b', clean[part.opening:part.end]):
            continue
        assign = [i for i, (a, b) in enumerate(units) if re.match(rf'{t}\s*=(?!=)', clean[a:b])]
        if len(assign) != 1 or any(_assigns(clean[units[i][0]:units[i][1]], t) for i in range(assign[0] + 1, len(units))):
            continue
        fresh = f'{t}_s16'
        if re.search(rf'\b{fresh}\b', clean):
            continue
        for place in places(assign[0]):
            if any(h.start() < place for h in hits):
                continue
            indent = re.match(r'[ \t]*', source[_line_start(source, units[assign[0]][0]):])[0]
            edits = [(h.start(), h.end(), fresh) for h in hits]
            edits += [(place, place, f'\n{indent}{fresh} = (s16) {t};'), (nl, nl, f'{head}s32 {fresh};\n')]
            add(NAMED, edit(source, edits))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
