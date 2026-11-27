"""A run of statements that reach one symbol by its address, read through a pointer set just before the run.

m2c writes the stores after a `switch` as `M2C_FIELD(&D, s32 *, 0x14) = 0;`, `... 0x18`, `... 0x1C`. SN GCC 2.8.1 -O2
folds the first offset into the address (`lui; sw %lo(D+0x14); addiu D+0x14; sw 4; sw 8`) where the target has
`lui; addiu %lo(D); sw 0x14; sw 0x18; sw 0x1C`: the base held in a register. The same three stores through a pointer
local of that block were exact (800 -> 0 on a 55-instruction N64 page setup and on its 90-instruction twin-arm neighbour, after `case_label_copies`); one-member
struct casts and `((s32 *) &D)[5]` were not. `symbol_address_local` sets one pointer for every use of a symbol, which
did not reach it: here the switch arms above already matched and only the later run wants its own pointer.

One child per run of two or more neighbouring simple statements of one block that use `&D` through a cast or
`M2C_FIELD`, and one with every such run. The values are unchanged; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'symbol_run_pointer'
FAMILIES = (FAMILY,)
LIMIT = 12
# The address as a value that stays the same through a pointer: `M2C_FIELD(&D, ...)` or `(T *) &D`.
_USE = re.compile(rf'(?:\bM2C_FIELD\s*\(\s*|\*\s*\)\s*)(?P<address>&\s*(?P<symbol>{IDENT}))\b(?!\s*(?:\[|\.|->))')
_CONTROL = re.compile(r'\b(?:if|else|for|while|do|switch|case|default|return|break|continue|goto)\b')
# Labels in front of a statement stay outside the pointer's block.
_LABELS = re.compile(rf'\s*(?:(?:case\b[^:;?]*|default|{IDENT})\s*:(?!:)\s*)*')


def _statements(clean, opening, end):
    """Runs of neighbouring simple statements, each a list of (start, end); braces and control flow end a run."""
    run, start, depth = [], opening + 1, 0
    for index in range(opening + 1, end):
        char = clean[index]
        depth += (char == '(') - (char == ')')
        if depth or char not in ';{}':
            continue
        text = clean[start:index + 1]
        labels = _LABELS.match(text)[0]
        if labels.strip():
            yield run
            run = []
        if char == ';' and not _CONTROL.search(text[len(labels):]):
            run.append((start + len(labels), index + 1))
        else:
            yield run
            run = []
        start = index + 1
    yield run


def _runs(part):
    """(symbol, start, end, address spans) for every run of two or more statements using one symbol's address."""
    for block in _statements(part.clean, part.opening, part.end):
        found = {}
        for number, (start, end) in enumerate(block):
            for use in _USE.finditer(part.clean, start, end):
                found.setdefault(use['symbol'], {}).setdefault(number, []).append(use.span('address'))
        for symbol, uses in found.items():
            numbers = sorted(uses)
            first = 0
            for index in range(1, len(numbers) + 1):
                if index < len(numbers) and numbers[index] == numbers[index - 1] + 1:
                    continue
                group = numbers[first:index]
                first = index
                if len(group) > 1:
                    yield (symbol, block[group[0]][0], block[group[-1]][1],
                           [span for number in group for span in uses[number]])


def _text(source, symbol, start, end, spans):
    local = '__run_' + symbol
    body = source[start:end]
    for a, b in sorted(spans, reverse=True):
        body = body[:a - start] + local + body[b - start:]
    indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:])[0]
    body = body.replace('\n', '\n    ')
    return f'{{\n{indent}    s8 *{local} = (s8 *) &{symbol};\n{indent}    {body}\n{indent}}}'


def _apply(source, runs):
    """The source with these runs wrapped; a run that overlaps a later one already taken is left out."""
    limit = len(source)
    for symbol, start, end, spans in sorted(runs, key=lambda run: run[1], reverse=True):
        if end <= limit:
            source = source[:start] + _text(source, symbol, start, end, spans) + source[end:]
            limit = start
    return source


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b__run_', part.clean):
        return []
    runs = list(_runs(part))
    # The last run first: a block's tail after a join is where the folded address shows.
    out = [(FAMILY, _apply(source, [run])) for run in sorted(runs, key=lambda run: run[1], reverse=True)[:LIMIT]]
    if len(runs) > 1:
        out.append((FAMILY, _apply(source, runs)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
