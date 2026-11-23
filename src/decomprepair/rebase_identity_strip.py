"""A pointer rebased onto its own symbol through two identity helpers, written as the pointer.

A long search (or a draft chain that kept an `inline_fn2(p, inline_fn234())` pair) can leave an address as
`(u8 *) &S + (p - (u8 *) base())`, with `base()` returning `&S` again: the address of `p` computed through a detour that
is the identity. Compiled, the detour folds to `p`, but only after the first pass has made a second pseudo that holds
`&S`, hoisted that pseudo's copy out of the loop and left it as a dead `move` in the register the real address then
takes (`move $a3,$a1` before `la $a3,gSaveTotalSlots`), so the loop bound's address register is allocated a different
way (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, a 143-instruction save-slot function: 265 -> 205, the next steps
`loop_goto_form` 145, then `skip_join_loop_wrapper` 60 and `comparison_sides` 0). `scaffold_strip` declines a function
with a `goto`, and no family read this pair, so the greedy chain found nothing on the saved best.

The rewrite reads the two helpers' own bodies, so it fires only where the identity holds:
  * `base()` (no parameters) returns `&S` (any cast around it);
  * `rebase(a, b)` returns `(u8 *) &S + (a - (u8 *) b)` for the same `S`;
  * a call `rebase(X, base())` (or `rebase(X, &S)`) is `X`, kept as its own parenthesised operand.
Every such call in the function goes at once in one child (`rebase_identity_strip`); the helpers stay (an unused static
inline function emits nothing). A candidate for the exact judge, never a verdict."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit
from .pattern_repairs import close

FAMILY = 'rebase_identity_strip'
FAMILIES = (FAMILY,)

BYTE = r'(?:u8|s8|char|unsigned\s+char|signed\s+char)'
DEFINITION = re.compile(
    rf'\b(?:static|inline)\s+(?:static\s+|inline\s+)*[\w\s*]*?\b(?P<name>{IDENT})\s*'
    r'\((?P<params>[^()]*)\)\s*\{\s*return\s+(?P<body>[^;{}]*);\s*\}')
BASE = re.compile(rf'\(*(?:\(\s*[\w\s*]+\)\s*)?&\s*(?P<symbol>{IDENT})\s*\)*')
REBASE = re.compile(
    rf'\(*\(\s*{BYTE}\s*\*\s*\)\s*\(*\s*&\s*(?P<symbol>{IDENT})\s*\)*\s*\)*\s*\+\s*\(\s*(?P<a>{IDENT})\s*-\s*\(*\s*'
    rf'\(\s*{BYTE}\s*\*\s*\)\s*(?P<b>{IDENT})\s*\)*\s*\)')


def _helpers(text):
    """({base helper: symbol}, {rebase helper: symbol}) read from the bodies in `text`."""
    bases, rebases = {}, {}
    for m in DEFINITION.finditer(_blank(text)):
        params = [p.strip() for p in m['params'].split(',') if p.strip() and p.strip() != 'void']
        body = m['body'].strip()
        if not params:
            hit = BASE.fullmatch(body)
            if hit:
                bases[m['name']] = hit['symbol']
        elif len(params) == 2:
            hit = REBASE.fullmatch(body)
            names = [re.split(r'[\s*]+', p)[-1] for p in params]
            if hit and [hit['a'], hit['b']] == names:
                rebases[m['name']] = hit['symbol']
    return bases, rebases


def _split(text):
    """The top-level comma-separated arguments of a call's parenthesised text."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        depth += (ch == '(') - (ch == ')')
        if ch == ',' and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    bases, rebases = _helpers(header + '\n' + source)
    if not rebases:
        return []
    clean = _blank(source)
    edits = []
    for m in re.finditer(rf'\b(?P<fn>{"|".join(map(re.escape, rebases))})\s*\(', clean[span[0]:span[1]]):
        open_at = span[0] + m.end() - 1
        end = close(clean, open_at)
        if not end:
            continue
        parts = _split(source[open_at + 1:end - 1])
        if len(parts) != 2:
            continue
        symbol = rebases[m['fn']]
        second = re.sub(r'\s+', '', parts[1])
        call = re.fullmatch(rf'({IDENT})\(\)', second)
        if not (call and bases.get(call[1]) == symbol
                or re.fullmatch(rf'\(*(?:\(\w+\*\))?&{re.escape(symbol)}\)*', second)):
            continue
        edits.append((span[0] + m.start(), end, '(' + parts[0].strip() + ')'))
    kept = []
    for e in sorted(edits):  # nested calls: the outermost only
        if not kept or e[0] >= kept[-1][1]:
            kept.append(e)
    return [(FAMILY, edit(source, kept))] if kept else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
