"""A literal that only seems constant: a scale factor assigned in both arms of the `if` that picks its sibling.

`dtdy = hires ? 0x200 : 0x400; dsdx = (0x400 * w) / cw; dtdy = (dtdy * h) / ch;` (a sprite's two texture steps) compiles the
`0x400` into the shift and multiply of the first expression. The target keeps it in a register that the
conditional also sets, so both factors are loaded in the arms and multiplied from there:

    if (hires) { dsdx = 0x400; dtdy = 0x200; } else { dsdx = 0x400; dtdy = 0x400; }
    dsdx = (dsdx * w) / cw; dtdy = (dtdy * h) / ch;

(the delay slot of the branch holds the shared `li`, and the multiply reads the register). 9682 -> 7545 on a 664-instruction
sprite drawer (exact judge, isolated), the third step of its rewrite. Hypothesis (not confirmed in the compiler's source): cse
folds `K * e` into a shift or a shorter sequence while a constant held across the branch stays a register operand.

Child, for `V = C ? K1 : K2;` followed within three statements by `W = (K3 * E) / F;` (`K` literals, `W` another local that
nothing between reads or writes): the pair assigned in both arms, `W` read in its own expression. The candidate is never a
verdict: the judge decides.
"""
import re

from .csource import _blank, find

FAMILY = 'arm_constant_pair'
FAMILIES = (FAMILY,)
_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'
_PICK = re.compile(rf'(?<![\w.>])(?P<v>{_ID})\s*=\s*(?P<c>(?:[^;?{{}}=]|[!=<>]=)+?)\s*\?\s*(?P<k1>{_NUM})\s*:\s*(?P<k2>{_NUM})\s*;')
_SCALE = re.compile(rf'(?<![\w.>])(?P<w>{_ID})\s*=\s*\(\s*(?P<k>{_NUM})\s*\*(?P<e>[^;]*)\)\s*/(?P<f>[^;]*);')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = []
    for pick in _PICK.finditer(clean, span[0], span[1]):
        v = pick['v']
        for scale in _SCALE.finditer(clean, pick.end(), span[1]):
            between = clean[pick.end():scale.start()]
            w = scale['w']
            if between.count(';') > 3 or w == v or '{' in between or '}' in between:
                break
            if re.search(rf'(?<![\w.>]){re.escape(w)}\b', between):
                continue
            arms = f'if ({pick["c"].strip()}) {{ {w} = {scale["k"]}; {v} = {pick["k1"]}; }} else {{ {w} = {scale["k"]}; {v} = {pick["k2"]}; }}'
            edited = source[:scale.start('k')] + w + source[scale.end('k'):]
            edited = edited[:pick.start()] + arms + edited[pick.end():]
            out.append((FAMILY, edited))
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
