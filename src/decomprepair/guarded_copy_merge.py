"""The second pointer a draft copies a guarded call result into, written as the first one again.

A saved best can take a call's result, test it, move it into a second local at the top of the guard and clear the first:
`p = alloc(); if (p != NULL) { q = p; p = NULL; ...q->a...; }` (a search's own liveness trick, or m2c's two names for one
register). The two names are two pseudos: the first stays in `$v0` for the test and the second takes the saved register
by a move inside the guard, and the allocator ranks the registers of the whole function around them. A 101-instruction
object constructor (SN N64 GCC `-O2`) whose target moves `$v0` into `$s0` right after the call, with the single pointer
the game wrote, went 285 -> 115 with the merge, one of the five edits of its match. `guarded_call_result_copy` writes the
copy; this takes it out. Not read in the compiler source; the judge decides.

guarded_copy_merge
    `if (P != NULL) { Q = P; [P = NULL;] ...` (also `!= 0` and `if (P)`), where P and Q are locals declared with the same
    pointer type, Q appears nowhere outside the guard's body, and P is set just before the guard and named nowhere else:
    one child drops the copy, the clear and Q's declaration and names P wherever the body named Q.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'guarded_copy_merge'
FAMILIES = (FAMILY,)
LIMIT = 4
_GUARD = re.compile(rf'\bif\s*\(\s*(?P<from>{IDENT})\s*(?:!=\s*(?:NULL|0)\s*)?\)\s*\{{')
_COPY = re.compile(rf'\s*(?P<to>{IDENT})\s*=\s*(?P<from>{IDENT})\s*;')


def _declaration(clean, opening, name):
    found = list(re.finditer(rf'(?m)^[ \t]*(?P<type>[A-Za-z_][\w \t]*?[ \t]*\*+)[ \t]*{name}[ \t]*;[ \t]*\n?',
                             clean[opening:]))
    return found[0] if len(found) == 1 else None


def _line(source, start, end):
    """The whole line of a statement that has one to itself, else the statement."""
    head = source.rfind('\n', 0, start) + 1
    if source[head:start].strip() or source[end:end + 1] != '\n':
        return start, end
    return head, end + 1


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, opening = part.clean, part.opening
    last = clean.rindex('}', opening, part.end)
    out = []
    for guard in _GUARD.finditer(clean, opening, last):
        origin = guard['from']
        copy = _COPY.match(clean, guard.end())
        if not copy or copy['from'] != origin or copy['to'] == origin:
            continue
        other = copy['to']
        end = close(clean, guard.end() - 1, '{', '}')
        if not end:
            continue
        declared = _declaration(clean, opening, origin)
        second = _declaration(clean, opening, other)
        if not declared or not second or ''.join(declared['type'].split()) != ''.join(second['type'].split()):
            continue
        if any(re.search(rf'&\s*{local}\b', clean[opening:last]) for local in (origin, other)):
            continue
        kill = re.compile(rf'\s*{origin}\s*=\s*(?:NULL|0)\s*;').match(clean, copy.end())
        body_start = kill.end() if kill else copy.end()
        mention = rf'(?<![\w.])(?<!->){other}\b'
        declaration_end = opening + second.end()
        if re.search(mention, clean[declaration_end:guard.start()]) or re.search(mention, clean[end:last]):
            continue
        # P is only the value tested and copied: set just before the guard, and named nowhere else, so no path
        # (a loop's back edge, a goto) can read what the clear left in it.
        assigned = re.search(rf'(?<![\w.>]){origin}\s*=(?!=)\s*[^;{{}}]+;\s*$', clean[opening:guard.start()])
        if not assigned:
            continue
        known = {opening + declared.start() + declared[0].rindex(origin), opening + assigned.start(),
                 guard.start('from'), copy.start('from')}
        if kill:
            known.add(kill.start() + kill[0].index(origin))
        if any(use.start() not in known for use in re.compile(rf'(?<![\w.])(?<!->){origin}\b').finditer(clean, opening, last)):
            continue
        edits = [(opening + second.start(), declaration_end, '')]
        lead = copy.start() + len(copy[0]) - len(copy[0].lstrip())
        edits.append((*_line(source, lead, copy.end()), ''))
        if kill:
            lead = kill.start() + len(kill[0]) - len(kill[0].lstrip())
            edits.append((*_line(source, lead, kill.end()), ''))
        edits += [(use.start(), use.end(), origin) for use in re.compile(mention).finditer(clean, body_start, end)]
        out.append((FAMILY, edit(source, edits)))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
