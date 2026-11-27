"""m2c's hand-written sign-bias block for a signed halving, written back as the signed division it came from.

GCC expands `x / 2^k` (signed x) as a test of the sign, an add of 2^k - 1 when it is set, and an arithmetic shift. m2c
reads that back as statements,

    var_a1 = (*(s32 *)((s8 *)arg0 + 0));
    if (var_a1 < 0) {
        var_a1 += 0xFF;
    }
    ...
    f(&G, var_a1 >> 8, ...);

and the bias block is a statement of its own where the division's expander has the load and the division together.
On an N64 function (KMC GCC 2.7.2, `-O2`, three such arguments, 260 points) the same three loads each divided where they
are loaded (`var_a1 = (*(s32 *)((s8 *)arg0 + 0)) / 0x100;`) were exact; loading all three first and dividing at the
calls was 380, so where the division sits is part of the repair and both spellings are children.

sign_bias_block_divide
    `V = X; if (V < 0) { V += 2^k-1; }` (with or without braces) where every later reference to the signed local V is
    `V >> k` (same k, V as the shift's whole left operand) becomes either `V = X / 2^k;` with the shifts dropped
    (the division at the load) or `V = X;` with each `V >> k` written `V / 2^k` (the division at the use). One child
    per site and per spelling, and one with every site in each spelling. The judge decides each child.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, locals_for, refs, view
from .pattern_repairs import close

FAMILY = 'sign_bias_block_divide'
FAMILIES = (FAMILY,)
LIMIT = 6
SIGNED = re.compile(r'(?:signed\s+)?(?:char|short|int)|s(?:8|16|32)')
BLOCK = r'if\s*\(\s*{v}\s*<\s*0\s*\)\s*(?:\{{\s*{v}\s*\+=\s*(?P<c1>' + NUMBER + r')\s*;\s*\}}|{v}\s*\+=\s*(?P<c2>' + NUMBER + r')\s*;)'
BEFORE = re.compile(r'(?:[(\[,?:;{}=]|&&|\|\||(?<!&)&|(?<!\|)\||\^|[<>](?![<>])|\breturn)\s*$')
AFTER = re.compile(r'\s*(?:[,);\]?:}]|&&|\|\||==|!=|(?<!&)&(?!&)|\^|<=|>=|<(?!<)|>(?!>)|\|(?!\|))')


def _number(text):
    return int(text.rstrip('uUlL'), 0)


def _unit(expr):
    """`expr` as an operand of `/`: as it is when it is one name or one bracketed group, else bracketed."""
    expr = expr.strip()
    if re.fullmatch(IDENT, expr):
        return expr
    if expr.startswith('('):
        end = close(expr, 0, '(', ')')
        if end == len(expr):
            return expr
    return f'({expr})'


def _site(part, decl):
    """(start, end, load expression, k, [(start, end) of each `V >> k`]) for a local whose bias block this is."""
    if not SIGNED.fullmatch(decl['type']):
        return None
    uses = refs(part, decl)
    if len(uses) < 4:
        return None
    clean, v = part.clean, decl['name']
    first = uses[0].start()
    if not re.search(r'[;{})]\s*$', clean[part.opening:first]):
        return None
    head = re.compile(rf'{re.escape(v)}\s*=\s*(?P<e>[^;{{}}=]+?)\s*;\s*' + BLOCK.format(v=re.escape(v)))
    hit = head.match(clean, first, part.end)
    if not hit or not hit['e'].strip() or re.search(r'(?<![<>=!])=(?!=)|\+\+|--', hit['e']):
        return None
    c = _number(hit['c1'] or hit['c2'])
    shifts, k = [], None
    for use in uses:
        if use.start() < hit.end():
            continue
        shift = re.compile(rf'{re.escape(v)}\s*>>\s*(?P<k>{NUMBER})').match(clean, use.start())
        if not shift or not BEFORE.search(clean[max(part.opening, use.start() - 12):use.start()]):
            return None
        if not AFTER.match(clean, shift.end()):
            return None
        width = _number(shift['k'])
        if k not in (None, width):
            return None
        k = width
        shifts.append((use.start(), shift.end()))
    if not shifts or k is None or not 1 <= k <= 30 or c != (1 << k) - 1:
        return None
    if any(start < hit.end() for start, _ in shifts):
        return None
    return first, hit.end(), hit['e'], k, shifts, v


def variants(source, name):
    part = view(source, name)
    if not part or not part.body.strip():
        return []
    sites = []
    for decl in locals_for(part):
        site = _site(part, decl)
        if site:
            sites.append(site)
        if len(sites) == LIMIT:
            break
    if not sites:
        return []

    def spelled(site, at_load):
        start, end, load, k, shifts, v = site
        power = f'{1 << k:#x}' if 1 << k > 0x10 else str(1 << k)
        if at_load:
            head = f'{v} = {_unit(load)} / {power};'
            return [(start, end, head)] + [(a, b, v) for a, b in shifts]
        return [(start, end, f'{v} = {load.strip()};')] + [(a, b, f'{v} / {power}') for a, b in shifts]

    out = []
    for at_load in (True, False):
        out += [edit(source, spelled(site, at_load)) for site in sites]
        if len(sites) > 1:
            out.append(edit(source, [one for site in sites for one in spelled(site, at_load)]))
    return [(FAMILY, child) for child in dict.fromkeys(out) if child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
