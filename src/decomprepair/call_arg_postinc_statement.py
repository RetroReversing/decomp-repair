"""A counter post-incremented inside a call's argument (`f(K + n++, ..);`), written with the increment as the
statement after the call (`f(K + n, ..); n++;`).

On a 629-instruction N64 level loader (SN64 GCC 2.8.1, `sn-n64-281 -G0 -mips3 -O2 ... -mfp32`) a loop calls
`func(0xA9 + n++, i + base1, e->kind)` with `n` spilled to the stack. The target computes the second argument and steps
the loop counter first, then reloads `n`, loads the byte, adds and stores `n` back in the call's delay slot. With the
increment inside the argument, the front end evaluates that argument into a pseudo of its own before the increment
(an argument with side effects is precomputed), and the first scheduler launched the add, the increment and the
store of `n` ahead of the other arguments; after reload the byte load could no longer pass the spilled counter's
store. Written as a plain argument with `n++;` after the call, the add goes straight into `$a0` and the arguments come
in the target's order: 615 -> 220 (twelve rows of scheduler order gone). It is the same program: the counter is a
plain local that no other argument reads and the callee cannot see.

call_arg_postinc_statement
    A call statement (`f(..);` or `x = f(..);`) one of whose arguments contains `v++` or `v--` for an integer local
    or parameter `v` that is not address-taken and appears nowhere else in the call: `v++` becomes `v` and `v++;`
    follows the statement on its own line. One child per site, and one with every site.

Hypothesis from that match (calls.c precomputes an argument with side effects; sched.c's birthing priority); the exact
judge decides.
"""
import re

from .integer_repair_support import IDENT, INTEGER, _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'call_arg_postinc_statement'
FAMILIES = (FAMILY,)
LIMIT = 8
_KEYWORDS = {'if', 'else', 'for', 'while', 'do', 'return', 'switch', 'case', 'sizeof', 'goto', 'break', 'continue'}
_CALL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?:(?P<dest>{IDENT})\s*=\s*)?(?P<callee>{IDENT})\s*\(')


def _integer_locals(clean, part):
    head = clean[:part.opening]
    params = head[head.rfind('(') + 1:]
    names = set()
    for text in (params, clean[part.opening:part.end]):
        for hit in re.finditer(rf'(?:^|[;{{}},(])\s*(?:register\s+)?{INTEGER}\s+({IDENT})\s*(?=[;=,)])', text):
            names.add(hit[1])
    return names


def _sites(source, part):
    clean = part.clean
    integers = _integer_locals(clean, part)
    sites = []
    for call in _CALL.finditer(clean, part.opening + 1, part.end):
        if call['callee'] in _KEYWORDS:
            continue
        opening = call.end() - 1
        after = close(clean, opening)
        if not after or not re.match(r'\s*;', clean[after:part.end]):
            continue
        end = after + len(re.match(r'\s*;', clean[after:])[0])
        args = clean[opening + 1:after - 1]
        found = [hit for hit in re.finditer(rf'(?<![\w.>])({IDENT})\s*(\+\+|--)', args)]
        for hit in found:
            counter = hit[1]
            if counter not in integers or counter == call['dest'] or _address_taken(part.body, counter):
                continue
            if len(re.findall(rf'(?<![\w.]){re.escape(counter)}\b', args)) != 1:
                continue
            start = opening + 1 + hit.start()
            sites.append((start, opening + 1 + hit.end(), counter, hit[2], end, call['indent']))
    return sites


def _child(source, chosen):
    edits = []
    for start, stop, counter, step, end, indent in chosen:
        edits.append((start, stop, counter))
        edits.append((end, end, f'\n{indent}{counter}{step};'))
    return edit(source, edits)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(source, part)[:LIMIT]
    out = [(FAMILY, _child(source, [site])) for site in sites]
    if len(sites) > 1:
        out.append((FAMILY, _child(source, sites)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
