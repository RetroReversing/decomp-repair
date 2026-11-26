"""An added `(x << k) - C` term kept apart from its constant, by a halfword conversion.

GCC 2.7.2 re-associates `A + ((x << 6) - 0x40)` into `(A + (x << 6)) - 0x40` however it is parenthesised, so the
constant lands after the add (`addu; addiu -0x40`). Some targets build the term first (`andi; sll; addiu -0x40; addu`).
A conversion on the term stops the re-association, and when the term's value fits a halfword the conversion emits no
instruction of its own. On an N64 KMC GCC `-O1` grid of calls this was the last step, 505 -> 0
(`(s32) pos.x + (s16) ((i << 6) - 0x40)`); `(u32)` left 791.

added_term_halfword
    `A + ((x << k) - C)`, `A + (x << k) - C` and `(A + (x << k)) - C` (also `+ C`, and `*` for `<<`) as `A + (s16) ((x << k) - C)`,
    where `x` is a byte (`u8`/`s8` declared, cast or `& 0xFF`) and the term's whole range fits a halfword, so the value
    is unchanged. One child with every such term converted, then one per term.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'added_term_halfword'
FAMILIES = (FAMILY,)
LIMIT = 8
BYTE = r'(?:u8|s8|(?:unsigned|signed)\s+char)'
ATOM = (rf'(?:\(\s*{BYTE}\s*\)\s*{IDENT}|\(\s*\(\s*{BYTE}\s*\)\s*{IDENT}\s*\)|\(\s*{IDENT}\s*&\s*0[xX][fF][fF]\s*\)|{IDENT})')
SHIFTED = re.compile(rf'(?P<open>\(\s*)?(?<![\w.])(?P<atom>{ATOM})\s*(?P<op><<|\*)\s*(?P<k>{NUMBER})\b(?(open)\s*\)|)')
MINUS = re.compile(rf'\s*(?P<sign>[-+])\s*(?P<c>{NUMBER})(?!\s*(?:\*|/|%|<<|>>))(?![\w.])')


def _number(text):
    text = text.rstrip('uUlL')
    return int(text, 16) if text[:2].lower() == '0x' else int(text, 8) if len(text) > 1 and text[0] == '0' else int(text)


def _largest(atom, scope):
    """The largest magnitude the byte `atom` can hold, or None when it isn't a byte."""
    cast = re.search(rf'\(\s*(?P<t>{BYTE})\s*\)', atom)
    if cast:
        return 128 if cast['t'].startswith('s') else 255
    if '&' in atom:
        return 255
    declared = re.search(rf'\b(?P<t>{BYTE})\s+(?:{IDENT}\s*,\s*)*{atom}\s*(?=[,;=)])', scope)
    if not declared:
        return None
    return 128 if declared['t'].startswith('s') else 255


def _added(clean, at):
    """Whether the expression starting at `at` is the right operand of a binary `+`."""
    before = clean[:at].rstrip()
    return before.endswith('+') and not before.endswith('++') and bool(re.search(r'[\w)\]]$', before[:-1].rstrip()))


def _opening(clean, closing):
    depth = 0
    for at in range(closing, -1, -1):
        depth += (clean[at] == ')') - (clean[at] == '(')
        if depth == 0:
            return at
    return None


def _sites(part, name):
    """(start, end, replacement pieces) of every term the conversion can keep apart."""
    clean = part.clean
    signature = re.search(rf'\b{re.escape(name)}\s*\([^{{}};]*\)\s*$', clean[:part.opening])
    scope = clean[signature.start() if signature else part.opening:part.end]
    out = []
    for hit in SHIFTED.finditer(clean, part.opening, part.end):
        largest = _largest(hit['atom'], scope)
        if largest is None:
            continue
        factor = _number(hit['k'])
        factor = 1 << factor if hit['op'] == '<<' and factor < 16 else factor if hit['op'] == '*' else None
        if factor is None:
            continue
        start, term_end = hit.start(), hit.end()
        minus = MINUS.match(clean, term_end)
        wrapper = None
        if not hit['open']:
            # A shift with no parentheses of its own starts the term only after a `+` or an opening parenthesis.
            # (`<<` binds looser than `-`, so an unparenthesised shift has no such term.)
            if hit['op'] != '*' or not minus or not re.search(r'[(+]\s*$', clean[part.opening:start]):
                continue
        if not minus:
            # `(A + (x << k)) - C`: the term closes a parenthesised sum that the constant is taken from.
            shut = re.compile(r'\s*\)').match(clean, term_end)
            if not shut or not _added(clean, start):
                continue
            minus = MINUS.match(clean, shut.end())
            wrapper = _opening(clean, shut.end() - 1)
            if not minus or wrapper is None or re.search(r'[\w\]]\s*$', clean[:wrapper]):
                continue
        if largest * factor + _number(minus['c']) > 0x7FFF:
            continue
        source = part.source
        term = source[start:term_end]
        value = f'(s16) ({term} {minus["sign"]} {source[minus.start("c"):minus.end("c")]})'
        if wrapper is not None:
            plus = clean.rfind('+', wrapper, start)
            left = source[wrapper + 1:plus].rstrip()
            out.append((wrapper, minus.end(), f'({left} + {value})'))
        elif _added(clean, start):
            out.append((start, minus.end(), value))
        else:
            # `A + ((x << k) - C)`: the parentheses around the whole term are the added operand.
            outer = re.compile(r'\(\s*$').search(clean, part.opening, start)
            if not outer or not _added(clean, outer.start()):
                continue
            shut = close(clean, outer.start(), '(', ')')
            if shut is None or clean[minus.end():shut - 1].strip():
                continue
            out.append((outer.start(), shut, value))
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(part, name)
    if not sites:
        return []
    out = []
    if len(sites) > 1:
        out.append((FAMILY, edit(source, sites)))
    out.extend((FAMILY, edit(source, [site])) for site in sites[:LIMIT])
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
