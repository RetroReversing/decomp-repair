"""One temporary the draft reuses for unrelated values, the later use renamed to a local of its own.

m2c keeps one name for each register a binary used, so a temporary can carry a shifted operand in one block and a
difference in a loop far below. The compiler sees one pseudo with the uses and the long life of both, and a priority
that moves its register and its neighbours'. Renamed from its second plain assignment to the one after (or the end), the
second value is a pseudo of its own: 605 -> 435 on a 719-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32
-mfp32 -O2`). The opposite of `disjoint_local_merge`, which joins values the draft split. A candidate rewrite; the exact
judge decides.
"""
import re

from .integer_repair_support import locals_for, view
from .line_scan import apply, lines, mentions

FAMILY = 'reused_temp_split'
FAMILIES = (FAMILY,)
LIMIT = 8


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    decls = locals_for(part)
    body = lines(part, source)
    out = []
    for decl in decls:
        local = decl['name']
        sets = [i for i, l in enumerate(body) if re.match(rf'{re.escape(local)} = ', l.stripped)
                and not mentions(l.stripped.split('=', 1)[1], local)]
        if len(sets) < 2:
            continue
        for k in range(1, len(sets)):
            end = sets[k + 1] if k + 1 < len(sets) else len(body)
            fresh = f'{local}_b{k}'
            if re.search(rf'\b{fresh}\b', part.clean):
                continue
            start, stop = body[sets[k]].start, body[end - 1].end if end > sets[k] else body[sets[k]].end
            span = part.clean[start:stop]
            edits = [(start + m.start(), start + m.end(), fresh) for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', span)]
            if not edits:
                continue
            edits.append((decl.end(), decl.end(), '\n' + (re.match(r'[ \t]*', source[source.rfind('\n', 0, decl.start()) + 1:])[0] or '  ')
                          + f'{decl["type"]} {fresh};'))
            out.append((FAMILY, apply(source, edits)))
            if len(out) >= LIMIT:
                return out
    return out
