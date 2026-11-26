"""A word built as `v = (a << 8) | (b << 16);` written in two statements, `v = a << 8; v |= b << 16;`.

KMC GCC 2.7.2 (`-O2`, N64) gives the one expression's two shifts a pseudo each and the `or` a third, so the value
the loop below reads is born at the `or` (`sll $v0, ..; sll $v1, ..; or $t0, $v0, $v1`). Built in steps, the first
shift is the variable itself and the `or` updates it in place (`sll $a3, $v0, 8; ...; or $a3, $a3, $v1`): one pseudo
with one more reference that lives from the first shift, which global.c ranks above the loop's other values. On a
1315-instruction sound-sequence interpreter's voice scan (a key compared in a loop), 3825 -> 3590. The register reading
is a hypothesis from the allocation dumps; the judge decides.

Rewrites a statement `V = X | Y;` or a declaration `T V = X | Y;` whose `|` is the top-level operator and whose
operands are both shifts (`<<`, in parentheses or not). A declaration keeps its place (`T V;`) and the two statements
go after the block's last declaration. Offers both orders (`V = X; V |= Y;` and `V = Y; V |= X;`); bounded.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'or_compound_steps'
FAMILIES = (FAMILY,)
LIMIT = 8
_TYPE = r'(?:(?:unsigned|signed|register)\s+)*(?:u8|s8|u16|s16|u32|s32|int|long|short|char|unsigned)'
_DECL_LINE = re.compile(rf'[ \t]*{_TYPE}\s*\**\s*{IDENT}\s*(?:\[[^\]]*\])?\s*(?:=[^;]*)?;[ \t]*\n')


def _python_top_or(expr):
    """The operands of `expr`'s top-level `|`, when there is exactly one."""
    depth, cuts = 0, []
    for at, char in enumerate(expr):
        depth += (char in '([') - (char in ')]')
        if char == '|' and depth == 0 and expr[at - 1:at] != '|' and expr[at + 1:at + 2] not in '|=':
            cuts.append(at)
    if len(cuts) != 1:
        return None
    left, right = expr[:cuts[0]].strip(), expr[cuts[0] + 1:].strip()
    return (left, right) if left and right else None


_top_or = _python_top_or
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _top_or(expr):
        cuts = [at for at in _scan.top_offsets(expr, '|', 2) if expr[at - 1:at] != '|' and expr[at + 1:at + 2] not in '|=']
        if len(cuts) != 1:
            return None
        left, right = expr[:cuts[0]].strip(), expr[cuts[0] + 1:].strip()
        return (left, right) if left and right else None


def _shift(text):
    inner = text
    while inner.startswith('(') and inner.endswith(')'):
        depth = 0
        for at, char in enumerate(inner):
            depth += (char == '(') - (char == ')')
            if depth == 0 and at < len(inner) - 1:
                break
        else:
            inner = inner[1:-1].strip()
            continue
        break
    depth = 0
    for at, char in enumerate(inner):
        depth += (char in '([') - (char in ')]')
        if depth == 0 and inner[at:at + 2] == '<<':
            return True
    return False


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    out = []
    pattern = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?:(?P<type>{_TYPE}\s*\**)\s*)?(?P<var>{IDENT})\s*=(?!=)\s*(?P<expr>[^;{{}}]+);[ \t]*\n')
    for found in pattern.finditer(clean, lo, hi):
        expr = source[found.start('expr'):found.end('expr')]
        parts = _top_or(expr)
        if not parts or not all(_shift(p) for p in parts):
            continue
        var, indent = found['var'], found['indent']
        if re.search(rf'\b{re.escape(var)}\b', expr):
            continue
        for first, second in (parts, parts[::-1]):
            steps = f'{indent}{var} = {first};\n{indent}{var} |= {second};\n'
            if found['type']:
                at = found.end()
                while True:
                    more = _DECL_LINE.match(clean, at)
                    if not more:
                        break
                    at = more.end()
                child = (source[:found.start()] + f'{indent}{found["type"].strip()} {var};\n' + source[found.end():at]
                         + steps + source[at:])
            else:
                child = source[:found.start()] + steps + source[found.end():]
            out.append((FAMILY, child))
        if len(out) >= LIMIT:
            break
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
