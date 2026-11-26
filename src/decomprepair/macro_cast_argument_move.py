"""A narrowing cast on a macro's argument at every call, moved into the macro's other uses of that parameter.

    HIRECT(PKT, ..., (s16) dsdx, (s16) dtdy);        HIRECT(PKT, ..., dsdx, dtdy);
    #define HIRECT(..., dsdx, dtdy)              ->  ... ADJ(((s16)(xl) * ((s16)(dsdx))) >> 7, ((s16)(dsdx))) ...
      ... _SHIFTL(dsdx, 16, 16) ...                  ... _SHIFTL(dsdx, 16, 16) ...

A texture-rectangle macro packs `dsdx` and `dtdy` raw into the last word (`_SHIFTL(dsdx, 16, 16)`: the field is masked to 16
bits anyway) and also reads them as signed halfwords for the scissor correction. With the cast written at the call the packing
reads the sign-extended copy as well, which is a second pseudo that ends where the loop's hoisted copies begin, while the
target packs the register that already holds the value (`sll $v1,$s6,16` from the variable, the sign-extended copies in
`$t7`/`$t6`): the variable then stays live through the loop in a saved register. A KMC GCC 2.7.2 sprite drawer
(`-G0 -mips3 -mgp32 -mfp32 -O2`, 653 instructions) went 4837 -> 3302 on this edit alone, 149 register rows to 123, the two
scale registers `$s5`/`$s6` as the target has them.

Child, for a function-like macro defined in the source whose parameter `p` appears inside `_SHIFTL(p, ...)` (a raw packing)
and elsewhere in the body, when every call of the macro in the source passes `(T) x` (T a 16- or 8-bit integer type, `x` a plain
name) for it: the cast dropped at each call and written around every other use of `p` in the macro. One child per macro and
parameter, and one with all of them (`macro_cast_argument_move_all`: the four casts of a sprite drawer's two
rectangle macros pay off together). The candidate is never a verdict: the judge decides.
"""
import re

from .c_scan import close
from .csource import _blank

FAMILY = 'macro_cast_argument_move'
FAMILY_ALL = 'macro_cast_argument_move_all'
FAMILIES = (FAMILY, FAMILY_ALL)
_ID = r'[A-Za-z_]\w*'
_DEFINE = re.compile(rf'^[ \t]*#[ \t]*define[ \t]+(?P<name>{_ID})\((?P<params>[^)]*)\)(?P<body>(?:\\\n|[^\n])*)', re.M)
_CAST = re.compile(rf'^\s*\(\s*(?P<t>[su](?:8|16))\s*\)\s*(?P<x>{_ID})\s*$')


def _python_split(text):
    """The top-level comma-separated pieces of an argument list."""
    out, depth, start = [], 0, 0
    for i, c in enumerate(text):
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        elif c == ',' and depth == 0:
            out.append((start, i))
            start = i + 1
    out.append((start, len(text)))
    return out


_split = _python_split
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split(text):
        result, start = [], 0
        for at in _scan.top_offsets(text, ',', 3):
            result.append((start, at))
            start = at + 1
        result.append((start, len(text)))
        return result


def _calls(clean, name, blanked_defines):
    """[(start, end)] of the argument text of every call `name(...)` outside the #define lines."""
    out = []
    for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*\(', blanked_defines):
        shut = close(blanked_defines, m.end() - 1, '(', ')')
        if shut > 0:
            out.append((m.end(), shut))
    return out


def _single(source):
    clean = _blank(source)
    # the same text with the #define lines blanked, so a call inside another macro's body is not a call site
    blanked = clean
    macros = []
    for d in _DEFINE.finditer(clean):
        blanked = blanked[:d.start()] + re.sub(r'[^\n]', ' ', d.group()) + blanked[d.end():]
        macros.append(d)
    out = []
    for d in macros:
        params = [p.strip() for p in d['params'].split(',')]
        body_at = d.start('body')
        body = source[body_at:d.end()]
        calls = _calls(clean, d['name'], blanked)
        if not calls:
            continue
        for k, p in enumerate(params):
            if not re.fullmatch(_ID, p) or not re.search(rf'_SHIFTL\(\s*\(?\s*{re.escape(p)}\b', body):
                continue
            edits, types = [], set()
            for lo, hi in calls:
                pieces = _split(clean[lo:hi])
                if len(pieces) != len(params):
                    types.add(None)
                    break
                a, b = pieces[k]
                cast = _CAST.match(source[lo + a:lo + b])
                if not cast:
                    types.add(None)
                    break
                types.add(cast['t'])
                text = source[lo + a:lo + b]
                edits.append((lo + a + len(text) - len(text.lstrip()), lo + b - (len(text) - len(text.rstrip())), cast['x']))
            if len(types) != 1 or None in types:
                continue
            t = types.pop()
            others = re.compile(rf'(?<![\w.>])(?<!_SHIFTL\()(?<!_SHIFTL\( )(?<!_SHIFTL\(\()(?<!_SHIFTL\(\( ){re.escape(p)}\b')
            new_body = others.sub(f'(({t})({p}))', body)
            if new_body == body:
                continue
            edits.append((body_at, d.end(), new_body))
            edited = source
            for lo, hi, text in sorted(edits, reverse=True):
                edited = edited[:lo] + text + edited[hi:]
            out.append((FAMILY, edited))
    return out


def variants(source, name):
    out = _single(source)
    # the casts of every macro and parameter at once: the packing reads of all of them stay the variable
    combined, steps = source, 0
    while steps < 8:
        more = _single(combined)
        if not more:
            break
        combined, steps = more[0][1], steps + 1
    if steps > 1:
        out.append((FAMILY_ALL, combined))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
