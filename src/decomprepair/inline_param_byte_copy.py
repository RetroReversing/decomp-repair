"""An inline helper's parameter read as `p & 0xFF` in both arms of an `if`, read through a `u8` local copied just
before that `if`: `if (b == 0xFF) { x = id & 0xFF; .. } else { .. y = id & 0xFF; }` as
`slot = id; if (b == 0xFF) { x = slot; .. } else { .. y = slot; }`.

KMC GCC 2.7.2 (`-O2`, N64): integrate.c gives the parameter the caller's pseudo, so both masks read the caller's
register (`andi $v0, $v1, 0xff` in each arm). A target that copies it in the branch's delay slot (`bne ..; move $a0,
$v1`) and masks the copy in each arm (`andi $v1, $a0, 0xff`, `andi $v0, $a0, 0xff`) had a byte local of its own
(MIPS has no PROMOTE_MODE: a QImode pseudo, its zero-extension at each use). On a 1315-instruction sound-sequence
interpreter's slot-ownership test, 2700 -> 2515. The program is the same: `(u8) id` is `id & 0xFF`.

Rewrites a `static inline` function's integer parameter `P` whose `P & 0xFF` reads all sit in the two arms of one
`if`/`else`: `u8 slot;` is declared at the top of the function, `slot = P;` goes before that `if`, and the reads
become `slot`. Bounded to `LIMIT` children.
"""
import re

from .integer_repair_support import IDENT
from .pattern_repairs import close

FAMILY = 'inline_param_byte_copy'
FAMILIES = (FAMILY,)
LIMIT = 4
_HEAD = re.compile(rf'(?m)^[ \t]*(?:static\s+inline|inline\s+static)\s+[^;{{()]*?\b(?P<fn>{IDENT})\s*\((?P<params>[^)]*)\)\s*\{{')


def variants(source, name, header=''):
    out = []
    for head in _HEAD.finditer(source):
        if head['fn'] == name:
            continue
        opening = head.end() - 1
        end = close(source, opening, '{', '}')
        if not end:
            continue
        body = source[opening:end]
        if re.search(r'\bslot\b', body):
            continue
        for param in re.finditer(rf'(?:u8|u16|s16|u32|s32|int)\s+({IDENT})\s*(?:,|$)', head['params']):
            var = param.group(1)
            masked = list(re.finditer(rf'(?<![\w.>]){re.escape(var)}\s*&\s*0[xX][fF][fF]\b(?!\w)', body))
            if len(masked) < 2:
                continue
            for guard in re.finditer(r'\bif\s*\(', body):
                cond_end = close(body, guard.end() - 1)
                arm = re.compile(r'\s*\{').match(body, cond_end) if cond_end else None
                if not arm:
                    continue
                a = arm.end() - 1
                b = close(body, a, '{', '}')
                other = re.compile(r'\s*else\s*\{').match(body, b) if b else None
                if not other:
                    continue
                d = close(body, other.end() - 1, '{', '}')
                if not d or not all(a < m.start() < d for m in masked):
                    continue
                if not any(m.start() < b for m in masked) or not any(m.start() > b for m in masked):
                    continue  # one arm only
                line = body.rfind('\n', 0, guard.start()) + 1
                indent = re.match(r'[ \t]*', body[line:])[0]
                first = body.find('\n', 0) + 1
                mask = rf'(?<![\w.>]){re.escape(var)}\s*&\s*0[xX][fF][fF]\b(?!\w)'
                new = body[:line] + f'{indent}slot = {var};\n' + re.sub(mask, 'slot', body[line:])
                lead = re.match(r'[ \t]*', body[first:])[0] or '  '
                new = new[:first] + f'{lead}u8 slot;\n' + new[first:]
                out.append((FAMILY, source[:opening] + new + source[end:]))
                break
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
