"""A narrowing cast on a store, done through a narrow local first.

`locals.a = (s16) (s32) x; locals.b = (s16) (s32) y;` converts each float to an int, narrows it and stores the
halfword. GCC 2.7.2's first scheduler gives each of those chains a priority from the instructions after it, and the
chain whose value a later call also takes (`(s32) z` as an argument) is longer by one move, so it is scheduled
first: the three loads and conversions come in the order the call wants, not the order the stores were written in.
When the target has them in the stores' order, with the narrowed values in separate registers and all the stores after
the conversions (`trunc.w.s; mfc1 $v0` ... `mfc1 $v1` ... `sh $v0; sh $v1`), the game's stores were of narrow locals:

    s16 a;  a = (s16) (s32) x;  locals.a = a;

A local of the narrow type makes the narrowing a move to a user variable. It is one more instruction in each chain
before the store, and the chains of the stores that go through a local come out ahead of the one that goes straight
to the call's argument.

For each run of two or more consecutive stores `lvalue = (narrow) expression;` where the lvalue is memory (a field, a
pointer deref or an index), the variants stage the whole run, its first store and its last store through fresh locals
of the cast's type, declared at the top of the function. A single such store, staged, is a fourth. At most eight.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'staged_narrow_store'
FAMILIES = (FAMILY,)
LIMIT = 8
_NARROW = r'(?:s16|u16|s8|u8|short|signed\s+short|unsigned\s+short|char|signed\s+char|unsigned\s+char)'
_STORE = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<lhs>[^;{}=\n]*(?:\.|->|\*|\[)[^;{}=\n]*?)[ \t]*=(?!=)[ \t]*'
    r'\(\s*(?P<type>' + _NARROW + r')\s*\)\s*(?P<expr>[^;{}\n]+);[ \t]*$')


def _runs(clean, base, end):
    runs, current = [], []
    last = None
    for hit in _STORE.finditer(clean, base, end):
        if last is not None and clean[last:hit.start()].strip() == '':
            current.append(hit)
        else:
            if current:
                runs.append(current)
            current = [hit]
        last = hit.end()
    if current:
        runs.append(current)
    return runs


def _staged(source, hits, number, kind):
    names = [f'__repair_narrow_{number + i}' for i in range(len(hits))]
    edits = []
    for hit, local in zip(hits, names):
        edits.append((hit.start(), hit.end(), f'{hit["indent"]}{local} = ({hit["type"]}) {hit["expr"]};\n{hit["indent"]}{hit["lhs"].strip()} = {local};'))
    return edits, [(local, hit['type']) for hit, local in zip(hits, names)]


def variants(source, name):
    part = view(source, name)
    if not part or '__repair_narrow_' in source:
        return []
    clean, base, end = part.clean, part.opening + 1, part.end
    runs = _runs(clean, base, end)
    result = []
    if not runs:
        return []
    newline = source.find('\n', part.opening)
    # (a brace followed by code on its line takes the declarations right after it, space separated)
    tidy = newline >= 0 and not source[part.opening + 1:newline].strip()
    opening, separator = (newline + 1, '\n') if tidy else (part.opening + 1, ' ')
    for hits in runs:
        choices = [hits] + ([hits[:1], hits[-1:]] if len(hits) > 1 else [])
        for chosen in choices:
            edits, declared = _staged(source, chosen, 0, '')
            declarations = ''.join(f'    {kind} {local};{separator}' if separator == '\n' else f' {kind} {local};' for local, kind in declared)
            text = edit(source, edits + [(opening, opening, declarations)])
            if text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result[:LIMIT]
