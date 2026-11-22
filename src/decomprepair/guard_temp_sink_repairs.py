"""A temporary set just before an `if` that alone uses it, set inside the `if` instead.

m2c sets a value before the test (`t = x - 0x2000; if (x != 0x2000) { ... t ... }`). The compiler then keeps `x` live
across the test and gives `t` a register of its own, where the target's subtract overwrote the dying `x`
(`addiu $v1,$v1,-0x2000`). Set as the first statement of the `if` body, `t`'s live range starts after the test and the
register is `x`'s. Measured on a 719-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`):
1750 -> 1735. Only for an assignment whose value calls nothing, an `if` whose test mentions neither `t` nor a call, and
a `t` read nowhere but inside that `if`'s body. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, block_end, lines, mentions

FAMILY = 'guard_temp_sink'
FAMILIES = (FAMILY,)
_SET = re.compile(r'(?P<t>[A-Za-z_]\w*) = (?P<e>[^;]*);')
_CALL = re.compile(r'\b(?!if\b|while\b|sizeof\b)[A-Za-z_]\w*\s*\(')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = []
    for i, line in enumerate(body):
        hit = _SET.fullmatch(line.stripped)
        if not hit or _CALL.search(hit['e']):
            continue
        j = i + 1
        while j < len(body) and not body[j].stripped:
            j += 1
        if j + 1 >= len(body) or not body[j].stripped.startswith('if ('):
            continue
        test = body[j].stripped
        opening = j if test.endswith('{') else j + 1
        if opening != j and body[opening].stripped != '{':
            continue
        closing = block_end(body, opening)
        if closing is None or mentions(test, hit['t']) or _CALL.search(test[3:]):
            continue
        declaration = re.compile(rf'(?:[A-Za-z_]\w*\s+)+\**\s*{re.escape(hit["t"])};')
        outside = [l for k, l in enumerate(body) if not (opening < k < closing) and k != i and not declaration.fullmatch(l.stripped)]
        if any(mentions(l.text, hit['t']) for l in outside) or not any(mentions(l.text, hit['t']) for l in body[opening + 1:closing]):
            continue
        # Keep C89 declarations first. Only cross plain scalar declarations
        # whose initializer cannot change a value used by the sunk expression.
        insert = opening + 1
        while insert < closing:
            declaration = re.fullmatch(r'(?:s32|u32|int|unsigned int)\s+([A-Za-z_]\w*)'
                                       r'(?:\s*=\s*([A-Za-z_]\w*|[0-9]+))?\s*;', body[insert].stripped)
            if not declaration:
                break
            if mentions(hit['e'], declaration[1]) or mentions(body[insert].text, hit['t']):
                break
            insert += 1
        if insert < closing and re.match(r'(?:[A-Za-z_]\w*\s+)+\**\s*[A-Za-z_]\w*\s*(?:=|;)', body[insert].stripped):
            continue
        inner = body[insert].indent if insert < closing else body[opening].indent + '    '
        point = body[insert].start if insert < closing else body[opening].end
        out.append((FAMILY, apply(source, [(line.start, line.end, ''), (point, point, inner + line.stripped + '\n')])))
    return out
