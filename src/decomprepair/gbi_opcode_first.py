"""A display-list word whose opcode constant is written last, written first as the Gbi macro writes it.

libultra's macros build a command's first word as `_SHIFTL(G_VTX, 24, 8) | _SHIFTL(n, 12, 8) | _SHIFTL(v0 + n, 1, 7)`:
the opcode comes first. Drafts and saved bests usually print it last (`(n << 12) | (((v + n) & 0x7F) << 1) |
0x01000000`), and GCC keeps the operand order of the `|` chain, which decides which partial result is computed first
and so the registers of the chain (`lui $v1, 0x100; or $v0, $v0, $v1; or $a0, $a0, $v0` in the target). A
618-instruction N64 display-list interpreter (SN64 GCC 2.8.1, `-mfp32`): its gSPVertex word with the opcode first went
4226 -> 4001; the same move on its triangle words was worse (4206-4451), so each site is its own child.

Children (`gbi_opcode_first`, bounded): for each assignment `X = A | B | ... | K;` whose last top-level `|` operand `K`
is a hex constant of at least 0x01000000 (an opcode in the top byte), `X = K | A | B | ...;`; every such site at once
as one more child.
"""
import re

from . import c_scan
from .csource import _blank, find

FAMILY = 'gbi_opcode_first'
FAMILIES = (FAMILY,)
LIMIT = 8
STORE = re.compile(r'(?m)^([ \t]*[^;{}\n=]*[^=!<>+\-*/%&|^\s]\s*=\s*)([^;{}\n]+);')
OPCODE = re.compile(r'0[xX]0*([0-9A-Fa-f]{7,8})[uUlL]*')


def variants(source, name):
    return [(FAMILY, text) for text in rewrites(source, name)]


def _top_ors(expr):
    """The top-level operands of an `|` chain (no `||`), or None."""
    parts, depth, at = [], 0, 0
    i = 0
    while i < len(expr):
        c = expr[i]
        if c == '(':
            close = c_scan.close(expr, i, '(', ')')
            if close < 0:
                return None
            i = close + 1
            continue
        if c in '?:' and depth == 0:
            return None
        if c == '|':
            if expr[i + 1:i + 2] == '|' or expr[i - 1:i] == '|':
                return None
            parts.append(expr[at:i].strip())
            at = i + 1
        i += 1
    parts.append(expr[at:].strip())
    return parts if len(parts) >= 2 and all(parts) else None


def rewrites(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    sites = []
    for hit in STORE.finditer(clean, opening, end):
        expr = source[hit.start(2):hit.end(2)]
        parts = _top_ors(expr)
        if not parts or not OPCODE.fullmatch(parts[-1]) or int(parts[-1].rstrip('uUlL'), 16) < 0x01000000:
            continue
        lead = re.match(r'\s*', expr).group()
        sites.append((hit.start(2), hit.end(2), lead + ' | '.join([parts[-1]] + parts[:-1])))
    result = []
    for site in sites:
        text = source[:site[0]] + site[2] + source[site[1]:]
        if text not in result:
            result.append(text)
    if len(sites) > 1:
        text = source
        for a, b, new in reversed(sites):
            text = text[:a] + new + text[b:]
        result.append(text)
    return result[:LIMIT - 1] + result[-1:] if len(result) > LIMIT else result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
