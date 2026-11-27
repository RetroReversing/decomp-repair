"""A squared distance written as one expression, written back as the in-place steps the source took.

A nearest-object search written by m2c squares each difference into the sum in one go, and shifts the squared range into
a fresh local::

    best = ((u32) (range * range)) >> 12;
    ...
    dx = self->x - other->x;
    dy = self->y - other->y;
    dist = (((u32) (dx * dx)) >> 12) + (((u32) (dy * dy)) >> 12);

The game's code updated the locals themselves, so each product and its shift share one register::

    best = range * range; best >>= 12;
    ...
    dist = self->x - other->x; dist *= dist; dist >>= 12;
    dy = self->y - other->y;
    dy *= dy; dist += ((u32) dy) >> 12;

On a 70-instruction N64 search loop (SN GCC 2.8.1 -O2) the unfenced rewrite of a clean 330 saved source with all three
was exact: `mflo $t0; srl $t0, $t0, 12` and no saved registers, where the one-expression form took two (a stack frame).
The single edits alone scored no better than 105 together without the fences open, so they are offered as one child.

`variants` writes the sum as steps (the second difference squared in place), optionally with the first difference's
local folded into the sum's (placed right after its definition, before the second difference is loaded) and with the
range's own two steps, from the source as it stands and with its `do { } while (0)` fences opened. A difference local
that also holds a flag (its other assignments are literals) is allowed: the fold leaves it holding only the flag, which
changes what a path that never set the flag reads. A candidate rewrite; the judge decides.
"""
import re

from . import scaffold_strip
from .integer_repair_support import edit, view

FAMILY = 'square_sum_steps'
FAMILIES = (FAMILY,)
LIMIT = 8

_IDENT = r'[A-Za-z_]\w*'
_STATEMENT = re.compile(rf'(?<![\w.>])({_IDENT})[ \t]*=(?!=)[ \t]*([^;{{}}=]+);')
_CAST = re.compile(r'\(\s*(?:u32|unsigned\s+int|unsigned)\s*\)\s*')
_SQUARE = re.compile(rf'({_IDENT})\s*\*\s*\1$')
_SHIFT = re.compile(r'0[xX][0-9a-fA-F]+|\d+')


def _strip(text):
    """`text` without the parentheses that wrap all of it."""
    text = text.strip()
    while text.startswith('(') and text.endswith(')'):
        depth = 0
        for index, char in enumerate(text):
            depth += (char == '(') - (char == ')')
            if not depth:
                break
        if index != len(text) - 1:
            break
        text = text[1:-1].strip()
    return text


def _top(text, operator):
    """`text` cut at `operator` outside every parenthesis."""
    depth, last, out, index = 0, 0, [], 0
    while index < len(text):
        depth += (text[index] == '(') - (text[index] == ')')
        if not depth and text.startswith(operator, index):
            out.append(text[last:index])
            index += len(operator)
            last = index
            continue
        index += 1
    out.append(text[last:])
    return out


def _term(text):
    """(squared name, shift) for `((u32) (v * v)) >> k`, else None."""
    parts = _top(_strip(text), '>>')
    if len(parts) != 2 or not _SHIFT.fullmatch(parts[1].strip()):
        return None
    left = _strip(parts[0])
    cast = _CAST.match(left)
    if not cast:
        return None
    square = _SQUARE.fullmatch(_strip(left[cast.end():]))
    return (square.group(1), parts[1].strip()) if square else None


def _declared(clean, lo, hi, var, unsigned=False):
    kinds = r'(?:u32|unsigned\s+int|unsigned)' if unsigned else r'(?:s32|u32|unsigned\s+int|unsigned|int|long)'
    return re.search(rf'(?m)(?:^|[;{{])[ \t]*{kinds}\s+{var}\s*;', clean[lo:hi]) is not None


def _blocks(clean, lo, position):
    """The braces open at `position`, outermost first."""
    opened = []
    for index in range(lo, position):
        if clean[index] == '{':
            opened.append(index)
        elif clean[index] == '}' and opened:
            opened.pop()
    return opened


def _straight(clean, lo, start, stop):
    """Whether control runs from `start` to `stop` with nothing but statements and bare blocks between."""
    if re.search(r'\b(?:if|else|for|while|do|switch|case|default|goto|return|break|continue)\b|:\s*$',
                 clean[start:stop]):
        return False
    before, after = _blocks(clean, lo, start), _blocks(clean, lo, stop)
    return all(clean[lo:brace].rstrip()[-1:] in ('', '{', '}', ';') for brace in set(before) ^ set(after))


def _definition(clean, lo, hi, var, statement):
    """The one non-literal assignment of `var`, when its only reads are `statement`'s square (literal flags aside)."""
    if not _declared(clean, lo, hi, var):
        return None
    found = [m for m in _STATEMENT.finditer(clean, lo, hi) if m.group(1) == var]
    values = [m for m in found if not _SHIFT.fullmatch(m.group(2).strip())]
    if len(values) != 1 or values[0].end() > statement.start() or re.search(rf'\b{var}\b', values[0].group(2)) or \
            not _straight(clean, lo, values[0].end(), statement.start()):
        return None
    return values[0]


def _reads(clean, lo, hi, var):
    """How often `var` is named outside its declaration and assignments."""
    declared = len(re.findall(rf'(?m)(?:^|[;{{])[ \t]*(?:\w+\s+)+{var}\s*;', clean[lo:hi]))
    assigned = sum(1 for m in _STATEMENT.finditer(clean, lo, hi) if m.group(1) == var)
    return len(re.findall(rf'\b{var}\b', clean[lo:hi])) - declared - assigned


def _children(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(r'\bvolatile\b', clean[lo:hi]):
        return []
    ranges, sums = [], []
    for statement in _STATEMENT.finditer(clean, lo, hi):
        target, value = statement.group(1), statement.group(2)
        if not _declared(clean, lo, hi, target, unsigned=True):
            continue
        term = _term(value)
        if term and term[0] != target:
            ranges.append((statement.start(), statement.end(),
                           f'{target} = {term[0]} * {term[0]}; {target} >>= {term[1]};'))
            continue
        terms = [_term(side) for side in _top(_strip(value), '+')]
        if len(terms) != 2 or not all(terms):
            continue
        (first, shift), (second, other) = terms
        if len({target, first, second}) != 3:
            continue
        defined = _definition(clean, lo, hi, second, statement)
        # the second difference is squared in place, so nothing else may read it
        if not defined or _reads(clean, lo, hi, second) != 2:
            continue
        tail = f'{second} *= {second}; {target} += ((u32) {second}) >> {other};'
        steps = [(statement.start(), statement.end(),
                  f'{target} = {first} * {first}; {target} >>= {shift}; {tail}')]
        folded = None
        held = _definition(clean, lo, hi, first, statement)
        if held and not re.search(rf'\b{target}\b', clean[held.start():statement.start()]):
            literal_flag = any(m.group(1) == first and m.start() != held.start()
                               for m in _STATEMENT.finditer(clean, lo, hi))
            # the square's two reads; a flag's local is also read where the flag is tested
            if _reads(clean, lo, hi, first) == 2 or literal_flag:
                value_text = source[held.start(2):held.end(2)]
                folded = [(held.start(), held.end(),
                           f'{target} = {value_text}; {target} *= {target}; {target} >>= {shift};'),
                          (statement.start(), statement.end(), tail)]
        sums.append((steps, folded))
    out = []
    for steps, folded in sums[:2]:
        chosen = [group for group in (folded, steps) if group]
        if ranges:
            out.extend(edit(source, group + ranges[:1]) for group in chosen)
        out.extend(edit(source, group) for group in chosen)
    return out


def variants(source, name):
    opened = scaffold_strip.unfence(source, name)
    out = []
    for base in (opened, source):
        if base:
            out.extend((FAMILY, child) for child in _children(base, name) if (FAMILY, child) not in out)
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
