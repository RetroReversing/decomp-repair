"""A pointer relayed through two locals across a branchy value: the pointer's entry web, a copy before the value, a second copy after it.

`V = table[i]; if (!V) goto skip; op = V->f; ...; V->g = (u32) (op * K); call(V);` where one local `V` is the table
entry, the null test's operand, the base of the store and the call's argument. KMC GCC 2.7.2 gives that one pseudo the
call argument's register (`$a0`): it prefers `$a0` through the call, so the entry load, the test and the field read all
use `$a0`, and the store and the call share it. The target loads the entry into `$v0`, copies it into `$a0` before the
value's branches (an unsigned float conversion is two arms) and stores and calls through `$a0`: one `move $a0, $v0` in
the branch's delay slot.

Why one copy is not enough, and what is (global.c, hypotheses where marked; the judge decides): `expand_preferences`
walks the insns in order and, at each reg-reg copy whose source dies there, merges the two pseudos' register
preferences. With `P = V;` ahead of the value, `P` is the call argument itself (it carries `$a0`), so the merge hands `$a0`
to `V` and the allocator coalesces them: no copy. Two copies, `Q = V` before the value and `P = Q` after it, are merged in
that order: at the first `Q` has no preference yet, so `V` takes none and falls to the lowest free register (`$v0`); only
then does `Q` take `P`'s `$a0`, and `Q` and `P` coalesce. cse cannot fold the chain because the copies sit on both sides of
the value's join label (a new cse block), and combine cannot fold `P = Q` into the call because `P` is also the store's
base. The value goes into a local of its own so the second copy lands after the branches and before the store.

The case (KMC GCC 2.7.2, `-O2 -G0 -mips3`, a 511-instruction submit function, saved best 25, five register rows): the entry
pointer in `$a0` with the store through a copy in `$a1` became the target's `lw $v0`, `move $a0, $v0`, `sw ..., 0x134($a0)`
(25 -> 0 together with `symbol_offset_base_inline`'s 85 -> 25).

The child (`pointer_relay_copy`, one per store) rewrites the statement pair `V->F = RHS; call(..V..);` (or `H(V)->F = RHS;`
with `H` an identity helper) into `Q = E; T = RHS; V = Q; V->F = T; call(..V..);`, where `E` names the web of `V` from
its last assignment before the store: its mentions in that range are renamed to a new local `E`, when:
- `V` is a pointer local declared in the function and the next statement is a call that mentions `V` as an argument;
- `RHS` has an integer cast or a conditional in it (the value has branches), or calls a helper that does;
- the type of the new value local is the cast's, or the called helper's return type.
"""
import re

from .csource import _blank, find
from .reassigned_local_inline import IDENT

FAMILY = 'pointer_relay_copy'
FAMILIES = (FAMILY,)
LIMIT = 4
INTEGER = r'(?:unsigned\s+)?(?:u8|s8|u16|s16|u32|s32|int|long|short|char)'


def _helper_returns(clean, name):
    """The return type of a helper defined in the source, when it is an integer."""
    hit = re.search(rf'(?:^|[;}}\n])\s*(?:static\s+|inline\s+)*({INTEGER})\s+{re.escape(name)}\s*\(', clean)
    return hit[1] if hit else None


def _value_type(clean, rhs):
    cast = re.match(rf'\s*\(\s*({INTEGER})\s*\)', rhs)
    if cast:
        return cast[1]
    call = re.match(rf'\s*({IDENT})\s*\(', rhs)
    return _helper_returns(clean, call[1]) if call else None


def _branchy(clean, rhs):
    if re.search(rf'\(\s*{INTEGER}\s*\)|\?', rhs):
        return True
    call = re.match(rf'\s*({IDENT})\s*\(', rhs)
    if not call:
        return False
    body = re.search(rf'{re.escape(call[1])}\s*\([^)]*\)\s*\{{([^}}]*)\}}', clean)
    return bool(body and re.search(rf'\(\s*{INTEGER}\s*\)|\?', body[1]))


def variants(source, name):
    clean = _blank(source)
    span = find(source, name)
    if not span:
        return []
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    statement = re.compile(
        rf'(?P<indent>[ \t]*)(?:(?P<h>{IDENT})\s*\(\s*(?P<v1>{IDENT})\s*\)|(?P<v2>{IDENT}))\s*->\s*(?P<field>{IDENT})\s*=\s*'
        rf'(?P<rhs>[^;{{}}]+);[ \t]*\n(?P<call>[ \t]*{IDENT}\s*\([^;{{}}]*\)\s*;)')
    result = []
    for hit in statement.finditer(clean, opening, end):
        var = hit['v1'] or hit['v2']
        if hit['h'] and _helper_returns(clean, hit['h']) is not None:
            continue
        if not re.search(rf'(?<![\w.>]){re.escape(var)}\b', hit['call']):
            continue
        declaration = re.search(rf'(?:^|[;{{}}\n])[ \t]*((?:struct\s+)?{IDENT}(?:\s*\*)+)\s*{re.escape(var)}\s*;', clean[opening:end])
        if not declaration:
            continue
        pointer_type = re.sub(r'\s*\*', ' *', re.sub(r'\s+', ' ', declaration[1]).strip()).replace('* *', '**')
        if not _branchy(clean, hit['rhs']):
            continue
        value_type = _value_type(clean, hit['rhs'])
        if value_type is None:
            continue
        assigned = None
        for found in re.finditer(rf'(?<![\w.>]){re.escape(var)}\s*=(?!=)[^;]*;', clean[opening:hit.start()]):
            assigned = found
        if assigned is None:
            continue
        first = opening + assigned.start()
        entry, relay, value = f'{var}_entry', f'{var}_relay', f'{var}_value'
        if any(re.search(rf'\b{n}\b', clean) for n in (entry, relay, value)):
            continue
        head = source[first:hit.start()]
        head = re.sub(rf'(?<![\w.>]){re.escape(var)}\b', entry, head)
        indent = hit['indent']
        body = (f'{indent}{relay} = {entry};\n{indent}{value} = {hit["rhs"].strip()};\n{indent}{var} = {relay};\n'
                f'{indent}{var}->{hit["field"]} = {value};\n{hit["call"]}')
        text = source[:first] + head + body + source[hit.end():]
        cut = opening + declaration.end()
        if cut > first:
            continue
        text = text[:cut] + f'\n  {pointer_type}{entry};\n  {pointer_type}{relay};\n  {value_type} {value};' + text[cut:]
        if text != source and text not in result:
            result.append(text)
    return [(FAMILY, text) for text in result[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
