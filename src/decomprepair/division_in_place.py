"""m2c's sign-bias block for a signed division whose quotient goes to a new local, written back as one division that
the dividend's own variable keeps.

GCC expands `v = v * K / 0x1000;` (signed `v`) as the product, a test of its sign, an add of 0xFFF and an arithmetic
shift, and m2c reads it back as statements with the quotient in a local of its own:

    var_s1 = var_s1 * 0x10CC;
    if (var_s1 < 0) {
        var_s1 += 0xFFF;
    }
    temp_s1 = var_s1 >> 0xC;
    ... temp_s1 ...                      (var_s1 never read again)

The two names are two pseudos where the original had one, so the product and the quotient take the wrong registers:
on an N64 function (SN GCC 2.7.2, `-G0 -mips3 -O1`, 134 instructions, the quotient live across three calls) the target
keeps the dividend in `$s1`, the product in `$v0` and the quotient back in `$s1` (`sra $s1, $v0, 12`). Written as
`var_s1 = var_s1 * 0x10CC / 4096;` with every later `temp_s1` read as `var_s1` it was exact (20 -> 0). Each half alone
is worse: the quotient kept in `temp_s1` (`temp_s1 = var_s1 * 0x10CC / 4096;`) scored 50, and the division in place
but as a statement of its own (`var_s1 = var_s1 * 0x10CC; var_s1 = var_s1 / 4096;`) 310: the product must be a
temporary of the division's expander, not a value of the variable. So the in-place child writes both at once.

division_in_place
    `V = E; if (V < 0) { V += 2^k-1; } Q = V >> k;` (braces optional, `(s32) V` allowed), where V and Q are signed
    locals and Q is not referenced before the shift, becomes `V = E / 2^k;` with every later Q read as V and Q's
    declaration dropped (the quotient in the dividend's variable; only when V is not read after the shift), and, as a
    second child, `Q = E / 2^k;` (the quotient in its own local, the bias block gone). The judge decides each child.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, locals_for, refs, view
from .pattern_repairs import close

FAMILY = 'division_in_place'
FAMILIES = (FAMILY,)
LIMIT = 4
SIGNED = re.compile(r'(?:signed\s+)?(?:short|int)|s(?:16|32)')
SITE = re.compile(
    r'(?<![\w.>])(?P<v>' + IDENT + r')\s*=\s*(?P<e>[^;{}]+?)\s*;\s*'
    r'if\s*\(\s*(?P=v)\s*<\s*0\s*\)\s*(?:\{\s*(?P=v)\s*\+=\s*(?P<c1>' + NUMBER + r')\s*;\s*\}|(?P=v)\s*\+=\s*(?P<c2>'
    + NUMBER + r')\s*;)\s*'
    r'(?P<q>' + IDENT + r')\s*=\s*(?:\(\s*s32\s*\)\s*)?(?P=v)\s*>>\s*(?P<k>' + NUMBER + r')\s*;')


def _number(text):
    return int(text.rstrip('uUlL'), 0)


def _unit(expr):
    """`expr` as the left operand of `/`: as it is when it is one name or one bracketed group, else bracketed."""
    expr = expr.strip()
    if re.fullmatch(IDENT, expr):
        return expr
    if expr.startswith('('):
        end = close(expr, 0, '(', ')')
        if end == len(expr):
            return expr
    return f'({expr})'


def _sites(part):
    signed = {decl['name']: decl for decl in locals_for(part) if SIGNED.fullmatch(decl['type'])}
    found = []
    for hit in SITE.finditer(part.clean, part.opening + 1, part.end):
        v, q = hit['v'], hit['q']
        if v == q or v not in signed or q not in signed:
            continue
        if not re.search(r'[;{}]\s*$', part.clean[part.opening:hit.start()]):
            continue
        expr = hit['e']
        if re.search(r'(?<![<>=!])=(?!=)|\+\+|--|\?|,', expr) or re.search(rf'\b{re.escape(q)}\b', expr):
            continue
        k = _number(hit['k'])
        if not 1 <= k <= 30 or _number(hit['c1'] or hit['c2']) != (1 << k) - 1:
            continue
        alive = any(use.start() >= hit.end() for use in refs(part, signed[v]))
        q_uses = refs(part, signed[q])
        if any(use.start() < hit.start('q') for use in q_uses):
            continue
        later = [use for use in q_uses if use.start() >= hit.end()]
        found.append((hit, k, signed[q], later, alive))
        if len(found) == LIMIT:
            break
    return found


def _declaration(part, decl):
    """The span of Q's declaration line, so it goes with its last name."""
    start = part.clean.rfind('\n', 0, decl.start()) + 1
    end = part.clean.find('\n', decl.end())
    line = part.clean[start:end]
    if line.strip() != part.clean[decl.start():decl.end()].strip():
        return decl.start(), decl.end()
    return start, end + 1


def variants(source, name):
    part = view(source, name)
    if not part or not part.body.strip():
        return []
    out = []
    for hit, k, q_decl, later, alive in _sites(part):
        v, q = hit['v'], hit['q']
        power = f'{1 << k:#X}'.replace('0X', '0x') if 1 << k > 0x10 else str(1 << k)
        expr = source[hit.start('e'):hit.end('e')]
        quotient = f'{_unit(expr)} / {power}'
        if not alive:
            in_place = [(hit.start(), hit.end(), f'{v} = {quotient};')]
            in_place += [(use.start(), use.end(), v) for use in later]
            start, end = _declaration(part, q_decl)
            in_place.append((start, end, ''))
            out.append(edit(source, in_place))
        out.append(edit(source, [(hit.start(), hit.end(), f'{q} = {quotient};')]))
    return [(FAMILY, child) for child in dict.fromkeys(out) if child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
