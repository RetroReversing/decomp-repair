"""A loop's call arguments carried by the locals m2c named after the argument registers, shared with an earlier block's.

m2c names a value after the register it lived in: `var_a3` for the callback loop's offset (the call's fourth argument
register), `temp_a1` / `temp_a2` for two values of an earlier unpacking loop that also sat in `$a1` / `$a2`. It writes the
call as `temp_a0 = var_a3 * 4; f(s, p1 + temp_a0, p2 + temp_a0, p3 + temp_a0);`, so the earlier loop's `temp_a3` and the
call's `var_a3` are two C variables, every one of them used in one basic block only. KMC GCC 2.7.2's local allocator
(local-alloc.c: pseudos that live in one block and die once, lowest free register first) then takes the unpacking
loop's values before the global allocator sees its packed word, so the word lands in `$a3` and the values in
`$v1`/`$a1`/`$a2`: fifteen register rows on a 150-instruction packed-vector interpolation. A game's source named one
variable per role: the offset scaled in place (`off *= 4`), the two pointer arguments computed into locals, and the
unpacking loop reusing the offset's variable. Those pseudos are used in two blocks, so they are global, they are
allocated after the loop's temporaries by priority, and the target's registers follow (measured 75 -> 20 on that
function, and 10 with `last_use_double_in_place`). Any one of the three edits alone is worse (the shared name alone 85,
the in-place offset alone 65 of 65, the carriers without the shared name 95).

The rewrite, one child (a hypothesis for the judge, not a proof): in a block with `T = V * K;` right before a call whose
arguments are `P + T`,
- the scaling is written in place, `V = V * K;`, and the arguments use `V`; T goes;
- argument registers 1 and 2 are carried by the existing locals named `temp_a1` / `temp_a2` (or `var_a1` / `var_a2`)
  that the call's block does not mention: `L = (s32)(P + V);` before the call, `(void *) L` in it;
- the sibling of `V` (`temp_a3` for `var_a3`) that the call's block does not mention becomes `V`.
It declines without a `V`, a `T` used elsewhere, or a sibling that the call's block mentions."""
import re

from .integer_repair_support import edit, split_args, view

FAMILY = 'call_arg_register_locals'
FAMILIES = (FAMILY,)

_SCALE = re.compile(r'(?m)^([ \t]*)([A-Za-z_]\w*)\s*=\s*((?:var|temp)_a([0-3]))\s*\*\s*(\d+|0[xX][0-9a-fA-F]+)\s*;[ \t]*$')
_SUM = re.compile(r'^\(?\s*([A-Za-z_]\w*)\s*\+\s*([A-Za-z_]\w*)\s*\)?$')
_CALL = re.compile(r'(?m)^([ \t]*)([A-Za-z_]\w*)\s*\(')
_SKIP = {'if', 'while', 'for', 'switch', 'return', 'sizeof'}


def _declared(body, name):
    return re.search(rf'(?m)^[ \t]*(?:s32|int|u32|long)\s+{name}\s*;[ \t]*\n', body)


def _declared_off(body, name):
    found = _declared(body, name)
    return body[:found.start()] + body[found.end():] if found else body


def _block(clean, pos, lo, hi):
    """The innermost braces around `pos` as (open, close)."""
    depth, i = 0, pos
    while i > lo:
        i -= 1
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            if depth == 0:
                break
            depth -= 1
    start = i
    depth = 0
    for j in range(pos, hi):
        if clean[j] == '{':
            depth += 1
        elif clean[j] == '}':
            if depth == 0:
                return start, j
            depth -= 1
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    body = clean[lo:hi]
    for scale in _SCALE.finditer(clean, lo, hi):
        indent, temp, var, number, factor = scale.group(1), scale.group(2), scale.group(3), scale.group(4), scale.group(5)
        call = _CALL.match(clean, scale.end() + 1)
        if not call or call.group(2) in _SKIP:
            continue
        semi = clean.find(';', call.end())
        text = clean[call.end():semi]
        args = text.rstrip().rstrip(')')
        parts = [args[a:b].strip() for a, b in split_args(args)]
        if len(parts) < 4 or not number == '3' or temp == var:
            continue
        if len(re.findall(rf'\b{re.escape(temp)}\b', _declared_off(body, temp))) != 1 + sum(len(re.findall(rf'\b{re.escape(temp)}\b', p)) for p in parts):
            continue
        sums = [_SUM.match(p) for p in parts[1:4]]
        if not all(sums) or any(m.group(2) != temp for m in sums):
            continue
        block = _block(clean, scale.start(), lo, hi)
        if not block:
            continue
        inside = clean[block[0]:block[1]]
        sibling = 'temp_a3' if var.startswith('var_') else 'var_a3'
        if sibling == var or not _declared(body, sibling) or re.search(rf'\b{sibling}\b', inside):
            continue
        carriers = []
        for k in (1, 2):
            for prefix in ('temp_a', 'var_a'):
                local = f'{prefix}{k}'
                if _declared(body, local) and not re.search(rf'\b{local}\b', inside) and local != var:
                    carriers.append(local)
                    break
        if len(carriers) != 2:
            continue
        lines = [f'{indent}{var} = {var} * {factor};']
        newargs = [parts[0]]
        for local, m in zip(carriers, sums[:2]):
            lines.append(f'{indent}{local} = (s32)({m.group(1)} + {var});')
            newargs.append(f'(void *){local}')
        newargs.append(f'{sums[2].group(1)} + {var}')
        edits = [(scale.start(), scale.end(), '\n'.join(lines)),
                 (call.end(), semi, ', '.join(newargs) + ')')]
        decl = _declared(body, sibling)
        edits.append((lo + decl.start(), lo + decl.end(), ''))
        for m in re.finditer(rf'\b{sibling}\b', clean[lo:hi]):
            at = lo + m.start()
            if not (lo + decl.start() <= at < lo + decl.end()):
                edits.append((at, at + len(sibling), var))
        return [(FAMILY, edit(source, edits))]
    return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
