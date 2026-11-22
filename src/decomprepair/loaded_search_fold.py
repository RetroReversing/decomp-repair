"""A table search that carries each entry's loaded id in a local, written as the direct reads it came from.

m2c, and the repairs that unwrap its gotos, leave a search over a table of (id, offset) records as

    id = *entry;
    do {
        entry += 4;
        if (key == id) { found = ...; goto done; }
        id = *entry;
        map += 8;
    } while (id != sentinel);

The local `id` is a second pseudo that lives across the step, so the compiler keeps the key and the id in the
registers the other way round from a loop that reads the entry where it compares it, and the extra copy shows as
register differences on every pass. Written as `do { if (*entry == key) { ... } entry += 4; map += 8; } while
(*entry != sentinel);` the same loop reads the entry in both tests. A KMC 2.7.2 function (a record search ahead of an
edge-linking loop): 155 -> 140 as the direct reads, 135 with the entry on the left of `==` as the target compares it.
Both operand orders are offered, since the compiler's choice is the one thing the source order does decide.

Only when the body that runs on a hit names neither the entry pointer nor the carried id, so it cannot see the step
that now follows the test.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'loaded_search_fold'
FAMILIES = (FAMILY,)

SHAPE = re.compile(
    rf'(?P<lead>[ \t]*)(?P<id>{IDENT})[ \t]*=[ \t]*\*[ \t]*(?P<ptr>{IDENT})[ \t]*;[ \t]*\n'
    rf'(?P<pre>(?:[ \t]*{IDENT}[ \t]*=[^;{{}}\n]*;[ \t]*\n)*)'
    rf'(?P<lead2>[ \t]*)do[ \t]*\n?[ \t]*\{{[ \t]*\n'
    rf'[ \t]*(?P=ptr)[ \t]*\+=[ \t]*(?P<step>[^;\n]+);[ \t]*\n'
    rf'[ \t]*if[ \t]*\((?P<key>{IDENT})[ \t]*==[ \t]*(?P=id)\)[ \t]*\n?[ \t]*\{{')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    text = part.clean
    out = []
    for hit in SHAPE.finditer(text, part.opening, part.end):
        body_open = hit.end()-1
        body_close = close(text, body_open, '{', '}')
        if not body_close:
            continue
        body = text[body_open:body_close]
        ident, pointer = hit['id'], hit['ptr']
        if re.search(rf'\b(?:{re.escape(ident)}|{re.escape(pointer)})\b', body):
            continue
        # after the hit's block: `id = *ptr;`, the other steps, then the loop test on the carried id
        tail = re.compile(
            rf'\s*{re.escape(ident)}[ \t]*=[ \t]*\*[ \t]*{re.escape(pointer)}[ \t]*;[ \t]*\n'
            rf'(?P<steps>(?:[ \t]*{IDENT}[ \t]*(?:\+=|-=)[^;{{}}\n]*;[ \t]*\n)*)'
            rf'[ \t]*\}}[ \t]*\n?[ \t]*while[ \t]*\([ \t]*{re.escape(ident)}[ \t]*(?P<op>!=|==|<|>|<=|>=)[ \t]*(?P<limit>{IDENT}|-?\d+)[ \t]*\)[ \t]*;')
        end = tail.match(text, body_close)
        if not end:
            continue
        key, step, op, limit = hit['key'], hit['step'].strip(), end['op'], end['limit']
        indent = hit['lead2']
        steps = ''.join(f'{indent}  {line.strip()}\n' for line in end['steps'].splitlines() if line.strip())
        pre = hit['pre']
        for first in (f'*{pointer} == {key}', f'{key} == *{pointer}'):
            replacement = (
                f'{pre}{indent}do\n{indent}{{\n{indent}  if ({first})\n{indent}  '
                + source[body_open:body_close].replace('\n', '\n  ').rstrip()
                + f'\n{indent}  {pointer} += {step};\n{steps}{indent}}}\n{indent}while (*{pointer} {op} {limit});')
            out.append((FAMILY, edit(source, [(hit.start(), end.end(), replacement)])))
    return out
