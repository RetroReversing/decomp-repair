"""A cursor m2c rotated out of an index expression, written back as the expression where it is read.

The compiler copies a loop's first address computation into the bottom of the loop (the branch's delay slot) when the
loop body begins with `base + i`. m2c writes that rotation out as a local of its own: `cursor = base;` above the loop,
`cursor` read at the top of the body, and `cursor = base + i;` after the counter's step. Compiled as written, the
cursor is a second variable: the compiler adds a `move` and gives it another register (210 -> 0 on a 97-instruction
N64 search loop, KMC gcc 2.7.2 -O1, from the machine draft's chain).

For a local set exactly twice, `v = b;` and `v = b + i;`, with `b` never assigned, `i` set once to 0 and otherwise only
stepped, and every read of `v` before the first step of `i`, the child writes `(b + i)` at each read and drops both
assignments. The counter is 0 where `v = b` ran, so the program is the same. Proposals only; the compiler and the byte
judge decide."""
import re

from .integer_repair_support import IDENT, _address_taken, edit, view

FAMILY = 'rotated_cursor_inline'
FAMILIES = (FAMILY,)
SET = r'(?<![\w.>]){}\s*(?P<op>(?:[-+*/%&|^]|<<|>>)?=)(?!=)\s*(?P<value>[^;{{}}]*);'


def _assignments(body, name):
    return list(re.finditer(SET.format(re.escape(name)), body))


def _stepped(body, name):
    return list(re.finditer(rf'(?:\+\+|--)\s*{re.escape(name)}\b|(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)', body))


def _declared(clean, name):
    """The type words of `name`'s one declaration (a local or a parameter), spaces removed."""
    found = re.findall(rf'(?:^|[(,;{{])\s*((?:(?:const|struct|unsigned|signed)\s+)*{IDENT}(?:\s*\*)*)\s*(?<=[\s*])'
                       rf'{re.escape(name)}\s*(?=[;,)])', clean)
    types = [re.sub(r'\s+', '', t) for t in found if t.strip() != 'return']
    return types[0] if len(types) == 1 else None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body, base_at = part.body, part.opening + 1
    start = part.clean.rfind(name, 0, part.opening)
    signature = part.clean[part.clean.find('(', start):part.opening]
    result = []
    for first in re.finditer(rf'(?<![\w.>])(?P<v>{IDENT})\s*=(?!=)\s*(?P<b>{IDENT})\s*;', body):
        cursor, base = first['v'], first['b']
        sets = _assignments(body, cursor)
        if len(sets) != 2 or _stepped(body, cursor) or _address_taken(body, cursor):
            continue
        last = next((s for s in sets if s.start() != first.start()), None)
        index = last and last['op'] == '=' and re.fullmatch(rf'{re.escape(base)}\s*\+\s*(?P<i>{IDENT})\s*', last['value'])
        if not index or last.start() < first.start():
            continue
        counter = index['i']
        if counter in (cursor, base) or _assignments(body, base) or _stepped(body, base) or _address_taken(body, base):
            continue
        plain = [s for s in _assignments(body, counter) if s['op'] == '=']
        steps = sorted([s.start() for s in _assignments(body, counter) if s['op'] == '+=']
                       + [s.start() for s in _stepped(body, counter)])
        if (len(plain) != 1 or plain[0]['value'].strip() != '0' or plain[0].start() > first.start() or not steps
                or steps[0] < first.end() or steps[-1] > last.start() or _address_taken(body, counter)):
            continue
        locals_text = signature + '{' + body
        kind = _declared(locals_text, cursor)
        if not kind or kind != _declared(locals_text, base):
            continue
        declaration = re.search(rf'(?m)^[ \t]*(?:(?:const|struct|unsigned|signed)\s+)*{IDENT}(?:[ \t]*\*)*[ \t]*(?<=[ \t*])'
                                rf'{re.escape(cursor)}[ \t]*;[ \t]*\n', body)
        skip = [first.span(), last.span()] + ([declaration.span()] if declaration else [])
        reads = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(cursor)}\b', body)
                 if not any(a <= m.start() < b for a, b in skip)]
        if not declaration or not reads or any(m.start() < first.end() or m.start() > steps[0] for m in reads):
            continue
        edits = [(base_at + a, base_at + b, '') for a, b in skip]
        edits += [(base_at + m.start(), base_at + m.end(), f'({base} + {counter})') for m in reads]
        child = edit(source, edits)
        if (FAMILY, child) not in result:
            result.append((FAMILY, child))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
