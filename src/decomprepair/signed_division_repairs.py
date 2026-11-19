"""m2c's expansion of a signed division by a power of two, written back as `/` and `%`.

gcc divides a signed value by 2^N with a shift and a correction for negative values; m2c reads that back as

    q = t >> 0x10;
    if (t < 0) {
        q = (s32) (t + 0xFFFF) >> 0x10;
    }
    ... (t - (q << 0x10)) ...

which compiles to the same steps but not the same registers: an N64 function was 99.8% so and exact as
`t % 0x10000` (the quotient, where it is used as one, becomes `t / 0x10000`).

Two more of m2c's forms: a divide with an addend, which it writes with the addend folded twice,

    v = arg2 + 0xFF;  if (v < 0) { v = arg2 + 0x1FE; }  t = v >> 8;      ->  t = (arg2 + 0xFF) / 0x100;

and a correction under a test of the sign bit, `if (t & 0x800000) { w += 0xFF; } ... w >> 8` -> `w / 0x100`. An N64
function was 90.6% with both and exact as the two divisions.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'signed_division'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'0[xX][0-9a-fA-F]+|\d+'
SHAPE = re.compile(
    r'(?m)^[ \t]*(?P<q>' + IDENT + r')\s*=\s*(?P<t>' + IDENT + r')\s*>>\s*(?P<n>' + NUMBER + r')\s*;[ \t]*\n'
    r'[ \t]*if\s*\(\s*(?P=t)\s*<\s*0\s*\)\s*\{\s*\n'
    r'[ \t]*(?P=q)\s*=\s*(?:\(\s*s32\s*\)\s*)?\(\s*(?P=t)\s*\+\s*(?P<c>' + NUMBER + r')\s*\)\s*>>\s*(?P=n)\s*;\s*\n'
    r'[ \t]*\}[ \t]*\n')


ADDEND = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<v>' + IDENT + r')\s*=\s*(?P<x>' + IDENT + r')\s*(?:\+\s*(?P<a>' + NUMBER + r'))?\s*;[ \t]*\n'
    r'(?P<between>(?:[ \t]*[^\n;{}]*;[ \t]*\n)*?)'
    r'[ \t]*if\s*\(\s*(?P=v)\s*<\s*0\s*\)\s*\{\s*\n'
    r'[ \t]*(?P=v)\s*=\s*(?P=x)\s*\+\s*(?P<b>' + NUMBER + r')\s*;\s*\n'
    r'[ \t]*\}[ \t]*\n'
    r'[ \t]*(?P<t>' + IDENT + r')\s*=\s*(?P=v)\s*>>\s*(?P<n>' + NUMBER + r')\s*;[ \t]*\n')
SIGN_FIX = re.compile(
    r'(?m)^[ \t]*if\s*\((?P<cond>[^\n{}]*)\)\s*\{\s*\n'
    r'[ \t]*(?P<w>' + IDENT + r')\s*\+=\s*(?P<c>' + NUMBER + r')\s*;\s*\n'
    r'[ \t]*\}[ \t]*\n'
    r'(?P<line>[^\n]*?)(?<![\w.>])(?P=w)\s*>>\s*(?P<n>' + NUMBER + r')')


def _forms(source, clean, opening, end):
    """The addend and sign-test forms (see the docstring), each where its constants agree."""
    result = []
    text = source
    for hit in reversed(list(ADDEND.finditer(clean, opening, end))):
        n = int(hit['n'], 0)
        a = int(hit['a'], 0) if hit['a'] else 0
        if int(hit['b'], 0) - a != (1 << n) - 1:
            continue
        v = hit['v']
        later = clean[hit.end():end]
        if re.search(r'(?<![\w.>])' + v + r'\b', later) or re.search(r'(?<![\w.>])' + v + r'\b', hit['between']):
            continue
        value = f"{hit['x']} + {source[hit.start('a'):hit.end('a')]}" if hit['a'] else hit['x']
        replacement = (source[hit.start('between'):hit.end('between')]
                       + f"{hit['indent']}{hit['t']} = ({value}) / 0x{1 << n:X};\n")
        text = text[:hit.start()] + replacement + text[hit.end():]
    clean2 = _blank(text)
    end2 = close(clean2, opening, '{', '}')
    for hit in reversed(list(SIGN_FIX.finditer(clean2, opening, end2))):
        n = int(hit['n'], 0)
        if int(hit['c'], 0) != (1 << n) - 1 or not re.search(r'<\s*0|&\s*0[xX]', hit['cond']):
            continue
        shift = re.compile(r'(?<![\w.>])' + hit['w'] + r'\s*>>\s*' + re.escape(hit['n']))
        line = text[hit.start('line'):hit.end()]
        text = text[:hit.start()] + text[hit.start('line'):hit.start('line')] + shift.sub(
            f"{hit['w']} / 0x{1 << n:X}", line) + text[hit.end():]
    if text != source:
        result.append((FAMILY, text))
    return result


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
    for hit in SHAPE.finditer(clean, opening, end):
        n, c = int(hit['n'], 0), int(hit['c'], 0)
        if c != (1 << n) - 1:
            continue
        q, t, power = hit['q'], hit['t'], f'0x{1 << n:X}'
        rest = source[hit.end():end]
        rest = re.sub(r'\(\s*' + t + r'\s*-\s*\(\s*' + q + r'\s*<<\s*' + hit['n'] + r'\s*\)\s*\)', f'({t} % {power})', rest)
        rest = re.sub(r'(?<![\w.>])' + q + r'\b', f'({t} / {power})', rest)
        text = source[:hit.start()] + rest + source[end:]
        declared = re.search(r'(?m)^[ \t]*[\w ]+?\s+' + q + r'\s*;[ \t]*\n', text[opening:])
        if declared and not re.search(r'(?<![\w.>])' + q + r'\b', text[opening + declared.end():]):
            text = text[:opening + declared.start()] + text[opening + declared.end():]
        result.append((FAMILY, text))
    result += _forms(source, clean, opening, end)
    return result[:3]
