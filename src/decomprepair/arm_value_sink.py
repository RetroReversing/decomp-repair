"""A value computed before an `if`/`else` whose else arm overwrites it with a constant, written in the then arm.

    s = r->w << 5;                    if (r->flags & 0x80)
    if (r->flags & 0x80)              { s = r->w << 5; dsdx = ~dsdx; }
      dsdx = ~dsdx;            ->     else
    else                                s = 0;
      s = 0;

`s32 s = w << 5; if (c) { ... } else s = 0;` computes the value on both paths and then throws it away on one, and the
first statement's load and shift sit in the block before the branch, where the block allocator ranks the temporaries of
that block together. The target computed it inside the arm that keeps it. A KMC GCC 2.7.2 sprite drawer (`-G0 -mips3
-mgp32 -mfp32 -O2`, 653 instructions) had the flags test, the two scaled texture steps and `s` in one run: with `s`
sunk into the arm the quotient of the second step and the flags test exchanged `$v0` and `$v1` back (365 -> 325, eight
rows of the block, the register rows elsewhere in the function falling from 13 to 5 with them). `arm_invariant_sink`
never offered it: it needs the variable set once, and here the else arm sets it again. The explanation is a
hypothesis from the dumps (local-alloc's quantities of that block), not confirmed in the compiler's source.

Child, for `V = E;` directly before `if (C) THEN else V = K;` (braces optional on either arm; `E` and `C` with no call,
assignment, `++`/`--` or `volatile`, `C` not naming `V`, `K` a literal or a name, `THEN` not naming `V` before it
assigns it): `V = E;` as the first statement of the then arm, which gets braces. One child per match; the judge decides.
"""
import re

from .c_scan import close
from .csource import _blank, find

FAMILY = 'arm_value_sink'
FAMILIES = (FAMILY,)
_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'
_EFFECT = re.compile(rf'{_ID}\s*\(|\+\+|--|\bvolatile\b|(?<![=!<>])=(?!=)')
_ASSIGN = re.compile(rf'(?<![\w.>])(?P<v>{_ID})\s*=\s*(?P<e>[^;{{}}=][^;{{}}]*);\s*(?P<if>if)\s*\(')
_ELSE_ARM = re.compile(rf'\s*else\s*(?P<open>\{{)?\s*(?P<v>{_ID})\s*=\s*(?P<k>{_NUM}|{_ID})\s*;\s*(?(open)\}})')


def _statement_end(clean, at):
    """Index just past the statement or block starting at `at` (after whitespace), or -1."""
    at += len(clean[at:]) - len(clean[at:].lstrip())
    if at >= len(clean):
        return -1, at
    if clean[at] == '{':
        end = close(clean, at)
        return (end + 1 if end >= 0 else -1), at
    end = clean.find(';', at)
    return (end + 1 if end >= 0 else -1), at


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = []
    for pick in _ASSIGN.finditer(clean, span[0], span[1]):
        v, expr = pick['v'], pick['e']
        if _EFFECT.search(expr) or re.search(rf'(?<![\w.>]){re.escape(v)}\b', expr):
            continue
        opening = clean.rfind('(', pick.start(), pick.end())
        shut = close(clean, opening, '(', ')')
        if shut < 0:
            continue
        condition = clean[opening + 1:shut]
        if _EFFECT.search(condition) or re.search(rf'(?<![\w.>]){re.escape(v)}\b', condition):
            continue
        end, then_at = _statement_end(clean, shut + 1)
        if end < 0:
            continue
        other = _ELSE_ARM.match(clean, end)
        if not other or other['v'] != v:
            continue
        then = source[then_at:end]
        body = then[1:-1] if then.startswith('{') else then
        if re.search(rf'(?<![\w.>]){re.escape(v)}\b', body):
            continue
        new_then = '{ ' + f'{v} = {expr.strip()};' + ' ' + body.strip() + ' }'
        edited = source[:pick.start()] + source[pick.start('if'):then_at] + new_then + source[end:]
        out.append((FAMILY, edited))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
