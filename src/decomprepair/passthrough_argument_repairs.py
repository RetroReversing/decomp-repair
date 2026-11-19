"""An argument the caller passed on untouched in its own register, which m2c doesn't see.

When a caller hands its own `arg2` to a callee as that callee's third argument too, nothing loads `$a2` before the
call, so m2c leaves it out and the call has one argument too few: its later arguments shift down a register and the
last one off the stack. An N64 function was 95% with `f(arg0, D, x, y)` where the game called `f(arg0, D, arg2, x,
y)`; exact with it. Offered for callees declared without parameters (`s32 f();`, m2c's guess), with the caller's
parameter at its own position.
"""
import re

from . import m2cfix
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'passthrough_argument'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    signature = clean[span[0]:opening]
    params_at = signature.rfind('(')
    params = [p.strip() for p in m2cfix._split_top_level(signature[params_at + 1:signature.rfind(')')])]
    names = [re.search(IDENT + r'\s*$', p)[0].strip() if re.search(IDENT + r'\s*$', p) else None for p in params]
    if not names or names == ['void']:
        return []
    outside = clean[:span[0]] + clean[span[1]:]
    unprototyped = set(re.findall(r'(?m)^[ \t]*(?:extern\s+)?[\w ]+?[\s*]+(' + IDENT + r')\s*\(\s*\)\s*;', outside))
    result = []
    for call in re.finditer(r'\b(' + IDENT + r')\s*\(', clean[opening:end]):
        if call[1] not in unprototyped:
            continue
        paren = opening + call.end() - 1
        closing = close(clean, paren)
        if not closing:
            continue
        args = [a.strip() for a in m2cfix._split_top_level(clean[paren + 1:closing - 1])] if clean[paren + 1:closing - 1].strip() else []
        if len(args) >= 8:
            continue
        for k, param in enumerate(names[:4]):
            if param is None or k > len(args) or (k < len(args) and args[k] == param) or param in args:
                continue
            # insert before the k-th argument (or at the end)
            if k < len(args):
                spot = paren + 1
                for _ in range(k):
                    spot = _next_argument(clean, spot)
                insert, at = param + ', ', spot + (len(clean[spot:]) - len(clean[spot:].lstrip()))
            else:
                insert, at = (', ' if args else '') + param, closing - 1
            text = source[:at] + insert + source[at:]
            if text not in [t for _, t in result]:
                result.append((FAMILY, text))
        if len(result) >= 6:
            break
    return result


def _next_argument(text, start):
    """Where the argument after the one starting at `start` begins."""
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        depth += (ch in '([{') - (ch in ')]}')
        if depth == 0 and ch == ',':
            return i + 1
    return len(text)
