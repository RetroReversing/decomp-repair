"""A field's old value saved elsewhere through temporaries and the field then advanced, written `G = F; F += K;`.

The shape (SN64 GCC 2.8.1, `-G0 -mips3 -O2`; a 46-instruction N64 object update, 10 -> 0): a previous-value field gets
the current one, which is then stepped. The search's saved best spelled it through two locals

    t = M2C_FIELD(p, s32 *, 0x1C);
    u = t;
    t = t + 0x800;
    M2C_FIELD(p, s32 *, 0x40) = u;
    M2C_FIELD(p, s32 *, 0x1C) = t;

and the compiler loads into one register and copies into the other the opposite way round from the target (two
register rows). `M2C_FIELD(p, s32 *, 0x40) = M2C_FIELD(p, s32 *, 0x1C); M2C_FIELD(p, s32 *, 0x1C) += 0x800;` is exact.
No single rewrite of the locals reached it there (353 children and 90 merges of the whole library, none below 10).
That the temporaries cse makes for the plain form are what gets the target's registers is a hypothesis; the judge
decides each child.

`variants` finds a straight run of statements that starts `t = F;` (`t` a 32-bit integer local, `F` an object in
memory), only copies `t` between such locals, steps one copy of it once (`x = x + K`, `x += K`, or in the store itself),
stores the old value to one other lvalue `G`, and ends by storing the stepped value to `F` (`F = x;`, `F = x + K;`,
`F += K;`). It writes `G = F; F += K;` (or `-=`) and drops the locals' declarations.

Faithful and bounded: the locals are used nowhere outside the run; `G` is stored before `F` (the order of the two
stores is kept); neither `F` nor `G` calls anything, has a side effect, mentions one of the locals or is `volatile`;
`F` does not mention a `G` that is a plain name; the step is a number or a name other than `G`; a cast type written on
`F` or `G` is an integer of at most 32 bits.
"""
import re

from .increment_old_value_copy import WIDE, _assignment, _segments, _strip
from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, locals_for, refs, view

FAMILY = 'old_value_save_compound'
FAMILIES = (FAMILY,)
LIMIT = 8
AHEAD = 6  # statements after the load
STEP = rf'(?:{NUMBER}|{IDENT})'
COMPOUND = re.compile(r'(?P<left>.+?)\s*(?P<op>[+-])=(?!=)\s*(?P<right>.+)', re.S)
FIELD_TYPE = re.compile(r'^M2C_FIELD\s*\([^,]*(?:\([^()]*\)[^,]*)*,\s*(?P<type>[^,]*?)\s*\*\s*,')
DEREF_TYPE = re.compile(r'^\*\s*\(\s*(?P<type>[A-Za-z_][\w\s]*?)\s*\*\s*\)')


def _flat(text):
    return re.sub(r'\s+', '', text)


def _memory(text, part):
    """Whether `text` is an lvalue in memory that can be read again: no call, side effect or volatile access."""
    if not text or re.search(r'\+\+|--(?!>)|=|\?|\bvolatile\b', text):
        return False
    for call in re.finditer(rf'\b({IDENT})\s*\(', text):
        if call[1] not in ('M2C_FIELD', 'sizeof'):
            return False
    cast = FIELD_TYPE.match(text) or DEREF_TYPE.match(text)
    if cast and not re.fullmatch(rf'{INTEGER}|signed|unsigned(?:\s+long)?|long', cast['type']):
        return False
    if re.fullmatch(IDENT, text):  # a global: nothing in this function declares it
        whole = part.clean[:part.end]
        return not re.search(rf'\b(?!return\b){IDENT}[\s*]+{text}\s*(?=[;,)\[=])', whole[whole.rfind('}', 0, part.opening) + 1:])
    return bool(re.match(r'M2C_FIELD\s*\(|\*', text) or re.search(r'->|\[|\.', text))


def _operand(text, values):
    """(local, operator, step) for `x` or `x + K` where `x` holds the value, else None."""
    text = _strip(text)
    if text in values:
        return text, None, None
    hit = re.fullmatch(rf'({IDENT})\s*([+-])\s*({STEP})', text)
    if hit and hit[1] in values:
        return hit[1], hit[2], hit[3]
    hit = re.fullmatch(rf'({STEP})\s*\+\s*({IDENT})', text)
    if hit and hit[2] in values:
        return hit[2], '+', hit[1]
    return None


def _run(source, part, segments, index, scalars):
    """(start, stop, G, F, operator, step, locals) for the run that starts at segment `index`, or None."""
    clean = part.clean
    begin, stop, mark = segments[index]
    first = _assignment(clean[begin:stop].strip()) if mark == ';' else None
    if not first or first[0] not in scalars:
        return None
    load = _strip(first[1])
    if not _memory(load, part):
        return None

    def spelled(low, high, side):
        """The source's own spelling of one side of the assignment in clean[low:high]."""
        text = clean[low:high]
        at = text.index(side, text.index('=') + 1 if text.rstrip().endswith(side) else 0)
        return source[low + at:low + at + len(side)]

    values = {first[0]: 'old'}  # local -> which value of the field it holds
    step = None
    saved = None
    for start, end, mark in segments[index + 1:index + 1 + AHEAD]:
        if mark != ';':
            return None
        text = clean[start:end].strip()
        compound = COMPOUND.fullmatch(text)
        if compound:
            left, right = compound['left'].strip(), compound['right'].strip()
            if not re.fullmatch(STEP, right) or step:
                return None
            if left in values:
                step, values[left] = (compound['op'], right), 'new'
                continue
            if _flat(left) == _flat(load) and saved:
                return begin, end, saved, spelled(start, end, left), compound['op'], right, list(values)
            return None
        assigned = _assignment(text)
        if not assigned:
            return None
        left, right = assigned
        operand = _operand(right, values)
        if not operand:
            return None
        var, operator, constant = operand
        if operator and (step or values[var] != 'old'):
            return None
        kind = 'new' if operator else values[var]
        if operator:
            step = (operator, constant)
        if left in scalars:
            values[left] = kind
        elif _flat(left) == _flat(load):
            if kind != 'new' or not saved:
                return None
            return begin, end, saved, spelled(start, end, left), step[0], step[1], list(values)
        elif kind == 'old' and not saved and not operator and _memory(left, part):
            saved = spelled(start, end, left)
        else:
            return None
    return None


def _site(source, part, segments, index, scalars):
    found = _run(source, part, segments, index, scalars)
    if not found:
        return None
    begin, stop, saved, field, operator, step, used = found
    for var in used:
        uses = refs(part, scalars[var])
        if any(not begin <= hit.start() < stop for hit in uses):
            return None
        word = re.compile(rf'(?<![\w.>])(?<!->){re.escape(var)}\b')
        if word.search(saved) or word.search(field) or step == var:
            return None
    name = _flat(saved)
    if name == _flat(field) or step == name:
        return None
    if re.fullmatch(IDENT, name) and re.search(rf'(?<![\w.>]){name}\b', field):
        return None
    indent = part.clean[part.clean.rfind('\n', 0, begin) + 1:begin]
    indent = indent if not indent.strip() else ''
    text = f'{saved} = {field};\n{indent}{field} {operator}= {step};'
    changes = [(begin, stop + 1, text)]
    for var in used:
        decl = scalars[var]
        line = part.clean.rfind('\n', 0, decl.start()) + 1
        after = decl.end()
        if not part.clean[line:decl.start()].strip() and part.clean.startswith('\n', after):
            changes.append((line, after + 1, ''))
    return changes


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto)\b', part.body):
        return []
    scalars = {decl['name']: decl for decl in locals_for(part) if re.fullmatch(WIDE, decl['type'])}
    if not scalars:
        return []
    segments = _segments(part.clean, part.opening + 1, part.end - 1)
    sites = []
    for index in range(len(segments)):
        changes = _site(source, part, segments, index, scalars)
        if changes and not any(changes[0][0] < other[0][1] for other in sites):
            sites.append(changes)
    chosen = ([sites] if len(sites) > 1 else []) + [[site] for site in sites]
    results = []
    for group in chosen[:LIMIT]:
        text = edit(source, sorted({change for site in group for change in site}))
        if text != source and (FAMILY, text) not in results:
            results.append((FAMILY, text))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}  # the registry: no caller wiring (registry.py)
