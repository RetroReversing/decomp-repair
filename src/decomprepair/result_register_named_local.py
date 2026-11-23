"""An accumulated result handed to the local m2c named after the result register, when its block does not mention it.

`x = f + x;` (a field's final sum, written back into the variable it was built in) followed by one read of `x` leaves
the sum in `x`'s pseudo. KMC GCC 2.7.2 keeps that pseudo in a register chosen with all of `x`'s other references, while
the target computes the sum in `$v0` (`mfc1 $v0,$f2; addu $v0,$v0,$a3; andi $v1,$v0,0xffe`): the truncated float is
already in `$v0`, the sum is the same short-lived value. A local m2c named `temp_v0` / `var_v0` is the function's `$v0`
variable (a header word read at the entry, say), used in another block, so its pseudo is global and not one the loop's
temporaries compete with. Writing the sum into it took a 150-instruction packed-vector interpolation from 10 to 0 (the
`addu` took the target's `$v0` and the mask's result moved to `$v1`); the sum written into the loop's own variables, into
another block-local, or into a fresh local left it at 10-15.

Rewrites `X = E + X;` (or `X = X + E;`) into `Z = E + X;` and the one later read of `X` in the block into `Z`, where `Z`
is a declared integer local named `temp_v0` / `var_v0` (then `temp_v1` / `var_v1`) that the block does not mention
and that is mentioned elsewhere in the function (so the pseudo is multi-block, a hypothesis). Declines when `X` is read
more than once afterwards or after the block. One child per `Z` found, at most two."""
import re

from .integer_repair_support import edit, view

FAMILY = 'result_register_named_local'
FAMILIES = (FAMILY,)
LIMIT = 2
_SUM = re.compile(r'(?m)^([ \t]*)([A-Za-z_]\w*)\s*=\s*(?:(.+?)\s*\+\s*\2|\2\s*\+\s*(.+?))\s*;[ \t]*$')


def _block(clean, pos, lo, hi):
    depth, i = 0, pos
    while i > lo:
        i -= 1
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            if depth == 0:
                break
            depth -= 1
    start, depth = i, 0
    for j in range(pos, hi):
        if clean[j] == '{':
            depth += 1
        elif clean[j] == '}':
            if depth == 0:
                return start, j
            depth -= 1
    return None


def _read_later(text, x):
    """True when the first mention of `x` after the block is not a plain assignment (the sum could still be read)."""
    found = re.search(rf'\b{x}\b', text)
    return bool(found) and not re.match(r'\s*=(?!=)', text[found.end():])


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    body = clean[lo:hi]
    if re.search(r'\bvolatile\b', body):
        return []
    out = []
    for m in _SUM.finditer(clean, lo, hi):
        x = m.group(2)
        block = _block(clean, m.start(), lo, hi)
        if not block or not re.search(rf'(?m)^[ \t]*(?:s32|u32|int|long)\s+{x}\s*;', body):
            continue
        inside, rest_of_block = clean[block[0]:block[1]], clean[m.end():block[1]]
        reads = list(re.finditer(rf'\b{x}\b', rest_of_block))
        if len(reads) != 1 or _read_later(clean[block[1]:hi], x):
            continue
        for z in ('temp_v0', 'var_v0', 'temp_v1', 'var_v1'):
            declared = re.search(rf'(?m)^[ \t]*(?:s32|u32|int|long)\s+{z}\s*;[ \t]*\n', body)
            if (not declared or re.search(rf'\b{z}\b', inside)
                    or not re.search(rf'\b{z}\b', body[:declared.start()] + body[declared.end():])):
                continue
            at = m.end() + reads[0].start()
            out.append((FAMILY, edit(source, [(m.start(2), m.end(2), z), (at, at + len(x), z)])))
            break
        if len(out) == LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
