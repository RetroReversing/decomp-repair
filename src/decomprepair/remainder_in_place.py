"""m2c's sign-bias block for a signed remainder by a power of two, written back as `%`, in place in the variable the
remainder goes to when the dividend is only that variable plus a constant.

GCC computes `i = (i + 1) % 8;` (signed `i`) as `t = i + 1`, a biased copy for negative `t`, a shift, a shift back and
a subtraction. m2c reads it back with the bias written against `i` rather than `t` (cse folded `t + 7` into `i + 8`)
and the sum in a carrier local of its own:

    var_v1 = var_a0 + 1;
    ...
    do {
        var_v0 = var_v1;
        if (var_v1 < 0) {
            var_v0 = var_a0 + 8;
        }
        var_a0 = var_v1 - ((var_v0 >> 3) * 8);
        var_v1 = var_a0 + 1;
    } while (D_80125FA0[var_a0] == 0);

On an N64 function (SN GCC 2.7.2, `-G0 -mips3 -O1`, 18 instructions) that draft scored 710 and the automatic search
(6,784 trials) stopped at 15; `var_a0 = var_v1 % 8;` with the carrier kept scored 850, and
`var_a0 = (var_a0 + 1) % 8;` with the carrier gone was exact (710 -> 0). The carrier is a second pseudo the original
never had. So the family offers both.

remainder_in_place
    `B = T; if (T < 0) { B = X + C; } R = T - ((B >> k) * 2^k);` (also `T + C'` for the bias, `<< k` for the
    multiply, a braceless `if`), where the bias is `T + 2^k-1` (written against T, or against X when every assignment
    to T is `T = X + a;` and every assignment to X is followed at once by it, with C - a == 2^k-1), becomes
    `R = T % 2^k;` with B's statements and declaration gone, and, when R is X and T is read nowhere else,
    `X = (X + a) % 2^k;` with every `T = X + a;` and T's declaration gone. The judge decides each child.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, locals_for, refs, view

FAMILY = 'remainder_in_place'
FAMILIES = (FAMILY,)
LIMIT = 4
SIGNED = re.compile(r'(?:signed\s+)?(?:short|int)|s(?:16|32)')
CAST = r'(?:\(\s*s32\s*\)\s*)?'
SITE = re.compile(
    r'(?<![\w.>])(?P<b>' + IDENT + r')\s*=\s*(?P<t>' + IDENT + r')\s*;\s*'
    r'if\s*\(\s*(?P=t)\s*<\s*0\s*\)\s*(?P<open>\{)?\s*(?P=b)\s*=\s*(?P<x>' + IDENT + r')\s*\+\s*(?P<c>' + NUMBER
    + r')\s*;\s*(?(open)\}\s*)'
    r'(?P<r>' + IDENT + r')\s*=\s*(?P=t)\s*-\s*\(?\s*' + CAST + r'\(\s*' + CAST + r'(?P=b)\s*>>\s*(?P<k>' + NUMBER
    + r')\s*\)\s*(?:\*\s*(?P<n>' + NUMBER + r')|<<\s*(?P<k2>' + NUMBER + r'))\s*\)?\s*;')


def _number(text):
    return int(text.rstrip('uUlL'), 0)


def _statement(part, start, end):
    """The span of a statement with its line, when it stands alone on that line."""
    line_start = part.clean.rfind('\n', 0, start) + 1
    line_end = part.clean.find('\n', end)
    if part.clean[line_start:start].strip() or part.clean[end:line_end].strip():
        return start, end
    return line_start, line_end + 1


def _assignments(part, decl):
    """Every `name = ...;` statement of a local (start, end, right-hand side)."""
    name = re.escape(decl['name'])
    pattern = re.compile(r'(?<![\w.>=!<])' + name + r'\s*=(?!=)\s*(?P<rhs>[^;{}]*?)\s*;')
    found = []
    for hit in pattern.finditer(part.clean, part.opening + 1, part.end):
        if decl.start() <= hit.start() < decl.end():
            continue
        if not re.search(r'[;{}]\s*$', part.clean[part.opening:hit.start()]):
            return None  # an assignment inside an expression: not a plain statement
        found.append((hit.start(), hit.end(), hit['rhs']))
    return found


def _carrier(part, t_decl, x):
    """`a` when every assignment to T is `T = X + a;` (one a), else None."""
    found = _assignments(part, t_decl)
    if not found:
        return None
    addends = set()
    for _start, _end, rhs in found:
        hit = re.fullmatch(re.escape(x) + r'\s*\+\s*(' + NUMBER + r')', rhs)
        if not hit:
            return None
        addends.add(_number(hit[1]))
    return addends.pop() if len(addends) == 1 else None


def _followed(part, x_decl, t_name, x):
    """Every assignment to X is followed at once by `T = X + a;` (the remainder's own too), so T == X + a wherever
    T is read."""
    found = _assignments(part, x_decl)
    if found is None:
        return False
    follow = re.compile(r'\s*' + re.escape(t_name) + r'\s*=\s*' + re.escape(x) + r'\s*\+\s*' + NUMBER + r'\s*;')
    for _start, end, _rhs in found:
        if not follow.match(part.clean, end):
            return False
    return True


def _declaration(part, decl):
    start = part.clean.rfind('\n', 0, decl.start()) + 1
    end = part.clean.find('\n', decl.end())
    if part.clean[start:end].strip() != part.clean[decl.start():decl.end()].strip():
        return decl.start(), decl.end()
    return start, end + 1


def variants(source, name):
    part = view(source, name)
    if not part or not part.body.strip():
        return []
    signed = {decl['name']: decl for decl in locals_for(part) if SIGNED.fullmatch(decl['type'])}
    out = []
    seen = 0
    for hit in SITE.finditer(part.clean, part.opening + 1, part.end):
        b, t, x, r = hit['b'], hit['t'], hit['x'], hit['r']
        if b not in signed or t not in signed or r not in signed or len({b, t, r}) < 3:
            continue
        if not re.search(r'[;{}]\s*$', part.clean[part.opening:hit.start()]):
            continue
        k = _number(hit['k'])
        if not 1 <= k <= 30:
            continue
        if hit['n'] is not None and _number(hit['n']) != 1 << k:
            continue
        if hit['k2'] is not None and _number(hit['k2']) != k:
            continue
        bias = _number(hit['c'])
        addend = None
        if x == t:
            if bias != (1 << k) - 1:
                continue
        else:
            if x not in signed:
                continue
            addend = _carrier(part, signed[t], x)
            if addend is None or bias - addend != (1 << k) - 1:
                continue
            if not _followed(part, signed[x], t, x):
                continue
        b_uses = refs(part, signed[b])
        if any(not hit.start() <= use.start() < hit.end() for use in b_uses):
            continue
        power = f'{1 << k:#X}'.replace('0X', '0x') if 1 << k > 0x10 else str(1 << k)
        removed = [_declaration(part, signed[b]) + ('',)]
        stmt_start, stmt_end = _statement(part, hit.start(), hit.start('r'))
        # The copy and the bias block go; the remainder statement stays on its own line.
        indent = part.clean[part.clean.rfind('\n', 0, hit.start('r')) + 1:hit.start('r')]
        plain = edit(source, removed + [(hit.start(), hit.end(), f'{r} = {t} % {power};')])
        if stmt_start != hit.start():
            plain = edit(source, removed + [(stmt_start, hit.end(), f'{indent}{r} = {t} % {power};')])
        out.append(plain)
        if addend is not None and r == x:
            t_uses = refs(part, signed[t])
            assigned = _assignments(part, signed[t])
            inside = [use for use in t_uses if hit.start() <= use.start() < hit.end()]
            own = [use for use in t_uses if any(s <= use.start() < e for s, e, _rhs in assigned)]
            if len(inside) + len(own) == len(t_uses):
                a_text = re.search(r'\+\s*(' + NUMBER + r')', assigned[0][2])[1]
                changes = removed + [(stmt_start, hit.end(),
                                      f'{indent}{x} = ({x} + {a_text}) % {power};' if stmt_start != hit.start()
                                      else f'{x} = ({x} + {a_text}) % {power};')]
                changes += [_statement(part, s, e) + ('',) for s, e, _rhs in assigned]
                changes.append(_declaration(part, signed[t]) + ('',))
                out.append(edit(source, changes))
        seen += 1
        if seen == LIMIT:
            break
    return [(FAMILY, child) for child in dict.fromkeys(out) if child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
