"""A display command's colour word computed into a local before the cursor is read.

Game code that builds a display command often has the value as an expression of loads (the actor's colour times a
table's, shifted and masked) and writes it as `*cursor++ = ...`. gcc 2.7.2 orders the loads by the statement order of
the source: the value written inside `g = cursor++; g->w1 = EXPR;` is loaded after the cursor was read and advanced,
the original's was loaded before, and the target's schedule (the multiplies, with their long latency, ahead of the cursor
load) only appears with the value in a local that is computed first.

On an 842-instruction N64 lit-actor drawer (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`, scoring 2) the two colour
words of its default arms went 6442 -> 4792 with `{ u32 col = EXPR; g = cursor; ...; g->w1 = col; }` (each alone 6382 and
5682), and the cursor load, the advance and the first word moved to where the target has them. A third arm of the same
function whose colour words were loaded after the cursor in the target stayed as it was: the family offers one value
at a time and the judge decides.

`display_value_stage` offers, for a read of a global cursor into a local followed (in the same straight-line run, before
any call or control statement) by a store through that local whose value contains a load or a multiply, the function
with the value computed first in a block-scoped `u32`: `{ u32 stage = VALUE; <the run, the store reading stage> }`.
The store may be a raw word store, a store through a one-member record, or a `CursorRecord` member. Each staged child is
followed by the same with that command's words written as `CursorRecord` members (the cursor family's rewrite for a
group of one command), because neither half alone helped on the function above.
"""
import re

from . import display_cursor_record_repairs
from .display_cursor_record_repairs import NUMBER, RECORD, _records, _statements, _store
from .integer_repair_support import IDENT, edit, view

FAMILY = 'display_value_stage'
FAMILIES = (FAMILY,)
LIMIT = 8
LOCAL = 'stage'
POINTER = re.compile(rf'(?m)^[ \t]*extern\s+(?:void|char|s8|u8|s32|u32|int|unsigned|{RECORD})\s*\*\s*(?:volatile\s+)?(?P<name>{IDENT})\s*;')
RECORD_STORE = re.compile(rf'\(\(\s*{IDENT}\s*\*\s*\)\s*(?P<p>{IDENT})\s*\)\s*\[\s*(?:{NUMBER})\s*\]\s*\.\s*w[01]\s*=(?!=)\s*(?P<v>[^;]+?)\s*;\Z')
HEAVY = re.compile(r'\*\s*\(|[A-Za-z_]\w*\s*\*\s*[A-Za-z_(]|<<')
STOP = re.compile(r'[{}]|\b(?:if|else|while|for|goto|return|switch|case|break)\b|:|\b[A-Za-z_]\w*\s*\(')


def _value_store(text, records):
    if (m := RECORD_STORE.match(text)) is not None:
        return m['p'], m['v']
    if (found := _store(text, records)) is not None:
        return found[0], found[2]
    return None


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    spans = _statements(clean, part.opening + 1, part.end - 1)
    records = _records(clean[:part.opening])
    result = []
    for pointer in POINTER.finditer(clean[:part.opening]):
        cursor = pointer['name']
        read = re.compile(rf'(?P<x>{IDENT})\s*=\s*{re.escape(cursor)}\s*;\Z')
        write = re.compile(rf'{re.escape(cursor)}\s*=')
        for i, (a, b) in enumerate(spans):
            hit = read.match(clean[a:b])
            if not hit:
                continue
            run = [(i, a, b)]
            for j in range(i + 1, len(spans)):
                c, d = spans[j]
                text = clean[c:d]
                if STOP.search(text) and not write.match(text) and not _value_store(text, records):
                    break
                if clean[b:c].count('{') or clean[b:c].count('}'):
                    break
                run.append((j, c, d))
                b = d
            for j, c, d in run[1:]:
                stored = _value_store(clean[c:d], records)
                if not stored or stored[0] != hit['x'] or not HEAVY.search(stored[1]):
                    continue
                local = next(LOCAL if k == 0 else f'{LOCAL}_{k + 1}' for k in range(99)
                             if not re.search(rf'\b{LOCAL if k == 0 else f"{LOCAL}_{k + 1}"}\b', clean))
                value_start = clean.index(stored[1], c)
                value = source[value_start:value_start + len(stored[1])]
                last = max(k for k in range(len(run)) if run[k][0] == j)
                end = run[last][2]
                edits = [(a, a, f'{{ u32 {local} = {value};\n    '), (value_start, value_start + len(stored[1]), local),
                         (end, end, ' }')]
                staged = edit(source, edits)
                result.append((FAMILY, staged))
                # a command that is the only one of its group also needs its words as members, or the value alone does
                # not help (6442 -> 7412 as members alone, 6382 staged with them, 4792 with both arms of the function)
                for family, text in display_cursor_record_repairs.variants(staged, name, header, 1, {hit['x']}):
                    if family == display_cursor_record_repairs.FAMILY:
                        result.append((FAMILY, text))
    return result[:LIMIT]
