"""A global pointer loaded inside the right-hand side of the literal store before the call that dereferences it.

A statement `*(f32 *)(base + 0x2C) = -3.0f;` followed by `call(*G, ...)` (G a global pointer variable) compiles in
source order to: the store's address (a volatile load of the actor), the literal, the store, then the load of `G`. The
first scheduler (`sched.c`) orders insns of equal priority by their position in the source, so the store, which no later
insn of the block waits for, and the load of `G`, whose result the call's argument load needs, tie at the same priority
and the store goes first. The game has the load of `G` before the store (the store waits one load longer, `lw v0,G;
swc1 ...; lw a0,(v0)`): the load is emitted between the literal and the store when it is written in the store's
right-hand side, held in a local, `(tmp = G, -3.0f)`, and the call dereferences the local (`*tmp`). On a 578-instruction
menu routine (`gcc-2.7.2-kmc -O2 -G0 -mips3 -mgp32 -mfp32`) this one edit took 370 to 60 (the two other rows of that
region, a register pair and the store's position, both followed from it); no family offered it.

Offered only where it is the same program unless the store writes `G` itself: a statement of the form
`*(T *)(address) = literal;` directly followed by a statement that reads a plain global pointer `*G` exactly once and
does not name `G` otherwise, `G` declared `extern ... *G;` (a variable, not an array or a macro) and not named by the
store. That the store does not alias `G` is the hypothesis, and the judge is what says whether it helps. The local has the
global's own type (a `volatile` pointee stays `volatile`).

`variants` gives, labelled `late_pointer_load_in_store`, one child per such pair.
"""
import re

from .case_temporary_repairs import _identifiers
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'late_pointer_load_in_store'
FAMILIES = (FAMILY,)
LIMIT = 6
ID = r'[A-Za-z_]\w*'
NUMBER = r'-?\s*(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?[fFuUlL]*|\.\d+[fF]?)'
STORE = re.compile(rf'(?P<indent>[ \t]*)(?P<lhs>\*\s*\([^;{{}}=]+\))\s*=(?!=)\s*(?P<rhs>{NUMBER})\s*;')


def _pointer_type(text, name):
    """The declared type of global pointer `name` (`volatile long *`), or None."""
    for m in re.finditer(rf'(?m)^[ \t]*extern\s+([^;{{}}()\[\]]*?\*)\s*{re.escape(name)}\s*;', _blank(text)):
        return re.sub(r'\s+', ' ', m[1]).strip()
    return None


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    types = header + '\n' + source[:span[0]]
    taken = _identifiers(source)
    out = []
    for hit in STORE.finditer(clean, opening, end):
        after = re.compile(r'\s*').match(clean, hit.end()).end()
        stop = clean.find(';', after)
        if stop < 0 or '{' in clean[after:stop] or clean[after:after + 2] in ('if', 'do', 'wh', 'fo', 're', 'sw'):
            continue
        # the statement after the store may be a call; take it whole (balanced parentheses up to its `;`)
        depth, k = 0, after
        while k < end:
            if clean[k] == '(':
                depth += 1
            elif clean[k] == ')':
                depth -= 1
            elif clean[k] == ';' and depth == 0:
                break
            k += 1
        statement = clean[after:k + 1]
        for ptr in set(re.findall(rf'(?<![\w.>*])\*\s*({ID})\b(?!\s*[(\[])', statement)):
            if len(re.findall(rf'(?<![\w.>])\b{re.escape(ptr)}\b', statement)) != 1 or re.search(rf'\b{re.escape(ptr)}\b', hit['lhs']):
                continue
            kind = _pointer_type(types, ptr)
            if not kind or re.search(rf'\b{re.escape(ptr)}\s*(?:\[|\()', statement):
                continue
            fresh = '__repair_probe'
            while fresh in taken:
                fresh += '_'
            decl = f"\n  {kind}{'' if kind.endswith('*') else ' '}{fresh};"
            new_store = f"{hit['indent']}{hit['lhs']} = ({fresh} = {ptr}, {hit['rhs'].strip()});"
            new_statement = re.sub(rf'(?<![\w.>*])\*\s*{re.escape(ptr)}\b', f'*{fresh}', source[after:k + 1], count=1)
            text = source[:hit.start()] + new_store + source[hit.end():after] + new_statement + source[k + 1:]
            text = text[:opening + 1] + decl + text[opening + 1:]
            if text != source and all(text != t for _, t in out):
                out.append((FAMILY, text))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 64}
