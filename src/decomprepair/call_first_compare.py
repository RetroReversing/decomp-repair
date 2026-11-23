"""A comparison whose right side holds the call, written with the call on the left so it runs first.

gcc evaluates a comparison's left operand first. `if ((u8) table[i] < (u32) next())` loads the table byte, then makes the
call, so the loaded byte has to survive the call in a callee-saved register (an extra `$s` register, and every register
after it shifts). Written `if ((u32) next() > (u8) table[i])` the call comes first and the load follows it, in a
temporary, which is how a menu-update function's target read it (a KMC `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`
function: 215 -> 85 once the comparison was turned round, the rest being operand order). `comparison_sides` swaps only
two plain loads; this one swaps a load against an operand that contains a call, through casts and inline helpers, and
flips the operator so the meaning is the same. The side without a call must itself be free of calls, assignments and
increments, so no side effect changes its order. A candidate for the exact judge, never a verdict."""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'call_first_compare'
FAMILIES = (FAMILY,)
LIMIT = 6
FLIP = {'<': '>', '>': '<', '<=': '>=', '>=': '<=', '==': '==', '!=': '!='}
CALL = re.compile(r'(?<![\w.>])(?!(?:if|while|for|switch|sizeof|return|M2C_\w+)\b)[A-Za-z_]\w*\s*\(')
EFFECT = re.compile(r'(?<![=!<>])=(?!=)|\+\+|--')
TOKEN = re.compile(r'[(\[]|[)\]]|<<|>>|<=|>=|==|!=|&&|\|\||[<>?:,;]|(?<![=!<>])=(?!=)')


def _top_level(condition):
    """(operator, position) of the only depth-0 comparison of `condition`, or None when there are several operators,
    a logical operator, a conditional or a comma."""
    depth, found = 0, None
    for m in TOKEN.finditer(condition):
        t = m[0]
        if t in '([':
            depth += 1
        elif t in ')]':
            depth -= 1
        elif depth == 0:
            if t in FLIP:
                if found:
                    return None
                found = (t, m.start())
            elif t in ('&&', '||', '?', ':', ',', ';', '='):
                return None
    return found


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    out = []
    for m in re.finditer(r'\bif\s*\(', part.clean[part.opening:part.end]):
        start = part.opening + m.end() - 1
        end = close(part.clean, start)
        if not end:
            continue
        inner = part.clean[start + 1:end - 1]
        found = _top_level(inner)
        if not found:
            continue
        op, at = found
        left, right = inner[:at], inner[at + len(op):]
        if CALL.search(left) or EFFECT.search(left) or not CALL.search(right) or not left.strip() or not right.strip():
            continue
        swapped = right.strip() + ' ' + FLIP[op] + ' ' + left.strip()
        out.append(edit(source, [(start + 1, end - 1, swapped)]))
    return [(FAMILY, c) for c in dict.fromkeys(out) if c != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 120}
