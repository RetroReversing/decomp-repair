"""Positions built from a halfword loop counter typed as halfwords, and their `* 4` written `<< 2`.

    u16 i, j; s32 tx, ty, ly;                      u16 i, j; u16 tx; u16 ty; u16 ly;
    tx = r->cw * i + r->x + X;                     tx = r->cw * i + r->x + X;
    ty = r->y + r->ch * j;                  ->     ty = r->y + r->ch * j;
    ly = ty + Y;                                   ly = ty + Y;
    rect((s16) (tx * 4), ly * 4, ...);             rect((s16) (tx << 2), ly << 2, ...);

A KMC GCC 2.7.2 sprite drawer (`-G0 -mips3 -mgp32 -mfp32 -O2`, 664 instructions, a grid of scissored texture
rectangles) multiplied its `u16` loop counters unextended (`mult $v1, $s2`) while testing them as halfwords
(`andi $v1, $s2, 0xffff; slt`); every earlier attempt had either the tests (u16 counters, an `andi` before each
multiply) or the multiply (s32 counters, a `blez` first test). The multiply is unextended when the sum it feeds is
assigned to a halfword: convert.c's `convert_to_integer` distributes the truncation over PLUS and over a MULT whose
operands are both no wider than the result and of one signedness (two `u16`s, a `u8` and a `u16`), so the product is
done in HImode and `expand_binop` widens it without extending the counter. The positions' reads then go through the
`(s16)` arguments of the SDK's scissored rectangle macro, and there the spelling decides: `(s16) (tx * 4)` is not
narrowed (MULT's operand `4` is an `int`, wider than the result), so the halfword is zero-extended first (an `andi`
per read); `(s16) (tx << 2)` is (LSHIFT narrows when the count is less than the result's width), and the reads are
raw like the target's. Retyping alone was worse (430 -> 790 and more); retyping with the shifts gave 110 and, with
the sum order, `arm_value_sink` and `reload_temp_inline`, 0. Rules read in convert.c (gcc 2.7.2); that the extension
then survives combine is observed, not read.

Children, for a function with a halfword local counted by a `for (i = 0; ...)`: the integer locals set from a sum or
copy that holds a product with such a counter, and the locals set from those (closure; no calls, division, shifts or
bit operations in their assignments), retyped to the counter's type, with every `E * 2^k` whose `E` names one of
them written `(E << k)` (one child), that child with each position's sum written with the counter product last
(`x + X + w * i`, the order the target added in; a second), the same two with the halfwords that were already
positions shifted as well, and the retyping alone. One combined child each: each half alone is worse. The retyped
declarations are written one per line, which `reload_temp_inline` (the first twin's next step) needs to see them.
"""
import re

from .integer_repair_support import IDENT, INTEGER, edit, locals_for, split_plain_declarations, view

FAMILY = 'halfword_position_shift'
FAMILIES = (FAMILY,)
_HALF = {'u16': 'u16', 's16': 's16', 'unsigned short': 'u16', 'short': 's16', 'signed short': 's16'}
_WIDE = {'s32', 'u32', 'int', 'signed int', 'unsigned int'}
_SHIFTS = {'2': 1, '4': 2, '8': 3, '16': 4}
_PLAIN = re.compile(r'[^;{}]*')
_BAD = re.compile(r'[/%&|^?:<>!~]|\w\s*\(|\+\+|--|\[')
_BEFORE = re.compile(r'(?:^|[(,=+\-])\s*$')


def _assignments(part, name):
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*=(?!=)\s*(?P<rhs>[^;{{}}]*);', part.clean[part.opening:part.end]):
        yield hit['rhs']


def _names(text):
    return set(re.findall(rf'(?<![\w.>]){IDENT}', text))


def _positions(part, decls, counters):
    found, changed = set(), True
    while changed:
        changed = False
        for name, decl in decls.items():
            if name in found or name in counters:
                continue
            rhs = list(_assignments(part, name))
            if not rhs or any(_BAD.search(re.sub(r'\(\s*[su](?:8|16|32)\s*\)', '', r).replace('->', '.')) for r in rhs):
                continue
            product = any(re.search(rf'(?<![\w.>])({c})\s*\*|\*\s*({c})\b', r)
                          for r in rhs for c in map(re.escape, counters))
            if product or any(_names(r) & found for r in rhs):
                found.add(name)
                changed = True
    return found


def _group_start(text, shut):
    depth = 0
    for at in range(shut, -1, -1):
        depth += (text[at] == ')') - (text[at] == '(')
        if depth == 0:
            return at
    return -1


def _shifted(source, clean, start, end, names):
    """`E * 2^k` with `E` a name in `names` or a parenthesised group naming one, as `(E << k)`."""
    pattern = re.compile(r'\*\s*(?P<k>2|4|8|16)\b(?!\s*[\w(.\[])')
    edits = []
    for hit in pattern.finditer(clean, start, end):
        left = clean[:hit.start()].rstrip()
        if left.endswith(')'):
            opening = _group_start(left, len(left) - 1)
            if opening < 0 or re.search(r'[\w)\]]\s*$', clean[:opening]):
                continue  # a call or an indexed/called group
            operand = left[opening:]
            if not _names(operand[1:-1]) & names or re.fullmatch(r'\(\s*[\w\s]+\*?\s*\)', operand) and not _names(operand) & names:
                continue
        else:
            word = re.search(rf'(?<![\w.>]){IDENT}$', left)
            if not word or word[0] not in names:
                continue
            opening = word.start()
        if not _BEFORE.search(clean[:opening]):
            continue
        edits.append((opening, hit.end(), f'({source[opening:len(left)]} << {_SHIFTS[hit["k"]]})'))
    taken, out = [], []
    for a, b, text in sorted(edits):
        if any(a < y and x < b for x, y, _ in taken):
            continue
        taken.append((a, b, text))
        out.append((a, b, text))
    return edit(source, out) if out else source


def _one_per_line(source, name):
    """The declarations `split_plain_declarations` left on one line, one per line, as other families read them."""
    part = view(source, name)
    if not part:
        return source
    one = rf'(?:{INTEGER})\s+{IDENT}\s*;'
    body = re.sub(rf'(?m)^(?P<indent>[ \t]*)(?P<decls>{one}(?:[ \t]*{one})+)[ \t]*$',
                  lambda m: '\n'.join(m['indent'] + d.strip() for d in re.findall(one, m['decls'])),
                  source[part.opening:part.end])
    return source[:part.opening] + body + source[part.end:]


def _terms(text):
    """The top-level terms of a sum of `+` only, or None."""
    terms, depth, start = [], 0, 0
    for at, char in enumerate(text):
        depth += (char == '(') - (char == ')')
        if depth == 0 and char == '-' and text[at + 1:at + 2] != '>':
            return None
        if depth == 0 and char == '+':
            terms.append(text[start:at].strip())
            start = at + 1
    terms.append(text[start:].strip())
    return terms if len(terms) > 1 and all(terms) else None


def _product_last(source, name, positions, counters):
    """Each position's sum with its counter product first written with the product last (`x + X + w * i`)."""
    part = view(source, name)
    if not part:
        return source
    edits = []
    for hit in re.finditer(rf'(?<![\w.>])(?P<v>{IDENT})\s*=(?!=)\s*(?P<rhs>[^;{{}}]*);', part.clean[:part.end]):
        if hit.start() < part.opening or hit['v'] not in positions:
            continue
        terms = _terms(source[hit.start('rhs'):hit.end('rhs')])
        if not terms:
            continue
        product = [k for k, term in enumerate(terms) if any(
            re.fullmatch(rf'.*(?<![\w.>]){re.escape(c)}\s*\*.*|.*\*\s*{re.escape(c)}\b.*', term) for c in counters)]
        if len(product) != 1 or product[0] == len(terms) - 1:
            continue
        moved = terms[:product[0]] + terms[product[0] + 1:] + [terms[product[0]]]
        edits.append((hit.start('rhs'), hit.end('rhs'), ' + '.join(moved)))
    return edit(source, edits) if edits else source


def variants(source, name):
    split = split_plain_declarations(source, name)
    part = view(split, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto)\b', part.body):
        return []
    decls = {}
    for decl in locals_for(part):
        kind = ' '.join(decl['type'].split())
        decls[decl['name']] = (decl, kind)
    counters = {n for n, (d, kind) in decls.items() if kind in _HALF
                and re.search(rf'\bfor\s*\(\s*{re.escape(n)}\s*=', part.body)}
    if not counters:
        return []
    kind = _HALF[decls[sorted(counters)[0]][1]]
    found = _positions(part, {n: d for n, d in decls.items()}, counters)
    retype = sorted(n for n in found if decls[n][1] in _WIDE)
    if not retype:
        return []
    typed = _one_per_line(edit(split, [(decls[n][0].start('type'), decls[n][0].end('type'), kind) for n in retype]), name)
    out = []
    for names in (set(retype), found):
        again = view(typed, name)
        if not again:
            break
        child = _shifted(typed, again.clean, again.opening + 1, again.end, names)
        if child != typed:
            out.append(child)
            out.append(_product_last(child, name, found, counters))
    out.append(typed)
    seen, result = set(), []
    for child in out:
        if child not in seen and child != source:
            seen.add(child)
            result.append((FAMILY, child))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
