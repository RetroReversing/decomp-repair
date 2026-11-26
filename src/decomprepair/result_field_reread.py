"""A call's result kept in a local only to store it in a field and pass it on, written through the field.

m2c names a result and stores it where the game stored it:

    m = spawnTrackMarker(slot);  p->marker = m;  initObject(m, 0x30, 0x1B);

gcc 2.7.2 keeps `m` in a saved register for the whole span (a pseudo of its own, with a copy to `$a0` for the call and a
reference count that outranks the neighbours'), where the game's code has the result only in `$v0` (`move $a0,$v0`; the
store in the call's delay slot) and reads the field again where it needs the pointer later. Written through the field
(`p->marker = spawnTrackMarker(slot); initObject(p->marker, 0x30, 0x1B);`) a 795-instruction N64 object spawner went
4030 -> 3660 (two such spans, the registers of everything after them). The reading is a hypothesis from global.c; the judge
decides.

The shape: three consecutive statements `V = call(...);`, `<lvalue> = V;` and a call statement whose first argument is `V`,
for a local `V` that is next mentioned (after those three) by an assignment, never read, and appears nowhere in the
lvalue or the first call. One child rewrites one span; with several, one more rewrites them all.
"""
import re

from .arm_block_support import IDENT, brace_pairs, local_declaration, mentions, statements
from .integer_repair_support import edit, view

FAMILY = 'result_field_reread'
FAMILIES = (FAMILY,)

FIRST = re.compile(rf'(?P<var>{IDENT})\s*=(?!=)\s*(?P<call>{IDENT}\s*\([^;{{}}]*\))\s*;')
SECOND = re.compile(rf'(?P<lvalue>[^;{{}}=]+?)\s*=(?!=)\s*(?P<var>{IDENT})\s*;')
THIRD = re.compile(rf'(?P<callee>{IDENT})\s*\(\s*(?P<var>{IDENT})\s*(?P<rest>[,)][^;{{}}]*)\)\s*;')


def _plain_lvalue(text):
    """An lvalue with no side effects: members, indexes, dereferences, casts, and macro (all-capital) calls."""
    if re.search(r'\+\+|--|[^=!<>]=[^=]', text):
        return False
    return all(m[1].isupper() or m[1] == 'F' for m in re.finditer(rf'(?<![\w.>])({IDENT})\s*\(', text)
               if m[1] not in ('sizeof',)) and not re.fullmatch(IDENT, text.strip())


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return []
    spans = []
    for block_open, block_close in sorted(pairs.items()):
        units = statements(clean, block_open + 1, block_close)
        for index in range(len(units) - 2):
            a, b, c = list(units[index:index + 3])
            first = FIRST.fullmatch(clean[a[0]:a[1]].strip())
            second = SECOND.fullmatch(clean[b[0]:b[1]].strip())
            third = THIRD.fullmatch(clean[c[0]:c[1]].strip())
            if not (first and second and third):
                continue
            var = first['var']
            if second['var'] != var or third['var'] != var or not local_declaration(clean, part.opening, var):
                continue
            if (mentions(second['lvalue'], var) or mentions(first['call'], var) or not _plain_lvalue(second['lvalue'])
                    or re.search(rf'&\s*{re.escape(var)}\b', clean[part.opening:part.end])):
                continue
            later = clean[c[1]:part.end]
            nxt = mentions(later, var)
            if nxt and not re.match(rf'{re.escape(var)}\s*=(?!=)', later[nxt[0]:]):
                continue
            spans.append((a, b, c, first, second, third))
    out = []

    def edits_for(span):
        a, b, c, first, second, third = span
        lvalue = second['lvalue'].strip()
        text_a = clean[a[0]:a[1]]
        start_a = a[0] + text_a.index(first['var'])
        edits = [(start_a, a[0] + text_a.rindex(';') + 1, f"{lvalue} = {first['call']};")]
        line_b = clean.rfind('\n', 0, b[0]) + 1
        end_b = clean.find('\n', b[1]) + 1
        edits.append((line_b if not clean[line_b:b[0]].strip() else b[0], end_b if not clean[b[1]:end_b].strip() else b[1], ''))
        text_c = clean[c[0]:c[1]]
        at = c[0] + text_c.index('(') + 1
        at += len(text_c[text_c.index('(') + 1:]) - len(text_c[text_c.index('(') + 1:].lstrip())
        edits.append((at, at + len(third['var']), lvalue))
        return edits

    for span in spans:
        text = edit(source, edits_for(span))
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
    if len(spans) > 1:
        text = edit(source, [e for span in spans for e in edits_for(span)])
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 85}  # the registry: no caller wiring (registry.py)
