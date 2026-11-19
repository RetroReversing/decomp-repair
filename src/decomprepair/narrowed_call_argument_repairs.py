"""An argument m2c narrowed to fit a guessed prototype, passed whole to the `int` parameter the callee has.

m2c gives a callee the narrow parameter it saw used once (`f(u16, ...)`) and then narrows every argument to fit,
`f((u16) M2C_FIELD(p, s32 *, 0x14), ...)`. gcc masks or re-loads the halfword; the game passed the whole word
(`lw $a0, 0x14($v0)`). An N64 function was 97.0% so and exact with the parameter as `s32` and the cast gone.
"""
import re

from . import m2cfix
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'narrowed_call_argument'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NARROW = r'(?:u8|s8|u16|s16)'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for proto in re.finditer(r'(?m)^[^\n;{}()]*?\b(' + IDENT + r')\s*\(([^()]*)\)\s*;', clean[:span[0]] + ' ' * (span[1] - span[0]) + clean[span[1]:]):
        callee, params = proto[1], m2cfix._split_top_level(proto[2])
        if callee == name:
            continue
        for call in re.finditer(r'\b' + re.escape(callee) + r'\s*\(', clean[opening:end]):
            paren = opening + call.end() - 1
            closing = close(clean, paren)
            if not closing:
                continue
            args, at = [], paren + 1
            for arg in m2cfix._split_top_level(clean[paren + 1:closing - 1]):
                args.append((at, at + len(arg)))
                at += len(arg) + 1
            for k, (a, b) in enumerate(args):
                if k >= len(params) or not re.fullmatch(r'\s*' + NARROW + r'\s*', params[k]):
                    continue
                cast = re.match(r'(\s*)\(\s*' + NARROW + r'\s*\)\s*', clean[a:b])
                if not cast:
                    continue
                param_at = proto.start(2) + sum(len(p) + 1 for p in params[:k])
                param_text = params[k]
                lead = len(param_text) - len(param_text.lstrip())
                edits = sorted([(a + cast.end(1), a + cast.end(), ''),
                                (param_at + lead, param_at + lead + len(param_text.strip()), 's32')], reverse=True)
                text = source
                for x, y, new in edits:
                    text = text[:x] + new + text[y:]
                if text not in [t for _, t in result]:
                    result.append((FAMILY, text))
    return result[:4]
