"""A second call of the same function held in a local of its own, written into the local that held the first result.

m2c names every call result anew (`temp_v0 = make(); if (temp_v0 != NULL) {..} temp_v0_2 = make(); if (temp_v0_2 ..)`),
where the game had one record pointer reused. One variable for both results is one global pseudo that GCC allocates
once, so both calls' results take the same register and the values around the first result are allocated against it;
two variables let each take its own. A 59-instruction N64 effect spawner (SN GCC 2.8.1 `-G0 -mips3 -O2`) matched when
the second record went into the first pointer (45 -> 0, after its store order was fixed). The second name may also hold
an unrelated value earlier (m2c reuses a scratch name), and that earlier use keeps it.

A child renames, for one pair of calls of one function, the second local from its assignment to the call up to its next
assignment (or the end of the function). It is offered only when both locals are declared with the same type, the first
local is not read after the second call, and neither has its address taken. The exact judge decides.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'call_result_one_local'
FAMILIES = (FAMILY,)
LIMIT = 8

_CALL = re.compile(rf'(?<![\w.>])(?P<local>{IDENT})\s*=\s*(?:\([^()]*\*\s*\)\s*)?(?P<callee>{IDENT})\s*\(')


def _declared(body, local):
    found = re.search(rf'(?m)^[ \t]*(?:register\s+)?(?P<type>(?:(?:struct|unsigned|signed|const)\s+)*{IDENT}(?:\s*\*+)?)\s*'
                      rf'(?<![\w]){local}\s*;', body)
    return re.sub(r'\s+', '', found['type']) if found else None


def variants(source, name):
    """Children: one local for the results of two calls of one function."""
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    calls = list(_CALL.finditer(body))
    out = []
    for index, second in enumerate(calls):
        for first in calls[:index]:
            keep, drop = first['local'], second['local']
            if keep == drop or first['callee'] != second['callee']:
                continue
            kind = _declared(body, keep)
            if not kind or kind != _declared(body, drop) or re.search(rf'&\s*(?:{keep}|{drop})\b', body):
                continue
            if re.search(rf'(?<![\w.>]){keep}\b', body[second.start():]):
                continue
            # an assignment to the local itself starts a statement; `*(T *) p = v;` is a store through it
            again = re.compile(rf'(?<=[;{{}}])\s*{drop}\s*=(?!=)').search(body, second.end())
            stop = again.start() if again else len(body)
            edits = [(part.opening + found.start(), part.opening + found.end())
                     for found in re.finditer(rf'(?<![\w.>]){drop}\b', body[:stop]) if found.start() >= second.start()]
            child = source
            for start, end in reversed(edits):
                child = child[:start] + keep + child[end:]
            if (FAMILY, child) not in out:
                out.append((FAMILY, child))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
