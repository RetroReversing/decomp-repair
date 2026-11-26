"""A value stepped in a `for` header beside the counter, written off the counter at its uses.

`for (i = 0, px = x; i < 5; px += w, i++) { f(px); }` against `for (i = 0; i < 5; i++) { f(x + i * w); }`. On SN64
GCC 2.8.1 (N64, `-O2`) the loop pass makes the multiple of the counter a giv of its own either way, but a user
variable stepped in the header is an induction variable from the start, created before the loop's other givs (the
`i * 2` offset of a halfword table read in the body), so it takes the other saved register and the increments come
out in another order. Written off the counter, it is reduced together with the others in the target's order. A
194-instruction HUD drawer whose only rows left were those two registers and increments (40 under `-mfp32`) matched
with this edit. `counter_companion` does the same for m2c's `do`/`while` with literal strides and steps as the last
statements; this covers the `for` header, a stride held in a local that the loop never assigns, and the comma parts in
either order. Hypothesis (not confirmed in the compiler's source): the giv creation order decides it.

Children, for a `for` whose initialisation sets the counter to 0 and one companion `v` to an expression, and whose
step is `i++` and `v += S` in either order (`S` a literal or a name the loop does not assign): the companion's uses
in the body as `INIT + i * S`, the header reduced to the counter, the companion's declaration dropped when nothing else
names it; also with the product written `S * i`. The companion must not be assigned in the body or read after the loop.
Only MIPS; the candidate is never a verdict, the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'for_header_companion_index'
FAMILIES = (FAMILY,)
_ID = r'[A-Za-z_]\w*'
_FOR = re.compile(r'\bfor\s*\(')
_SIMPLE = re.compile(rf'(?:{_ID}|0[xX][0-9A-Fa-f]+|\d+)')


def _parts(text):
    """Comma-separated parts at depth 0."""
    out, depth, start = [], 0, 0
    for i, c in enumerate(text):
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c == ',' and depth == 0:
            out.append(text[start:i].strip())
            start = i + 1
    out.append(text[start:].strip())
    return out


def _assigned(text, name):
    return re.search(rf'(?:\b{name}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+\s*{name}\b|--\s*{name}\b|\b{name}\s*(?:\+\+|--)'
                     rf'|&\s*{name}\b)', text)


def _header(head):
    """(counter, companion, init, stride) of a `for` header, else None."""
    pieces = head.split(';')
    if len(pieces) != 3:
        return None
    init, cond, step = (_parts(p) for p in pieces)
    if len(init) != 2 or len(step) != 2 or len(cond) != 1:
        return None
    sets = [re.fullmatch(rf'({_ID})\s*=\s*([^=].*)', p, re.S) for p in init]
    if not all(sets):
        return None
    for counter_set, companion_set in (sets, sets[::-1]):
        counter, companion = counter_set[1], companion_set[1]
        if counter_set[2].strip() != '0' or counter == companion:
            continue
        bumps = {re.sub(r'\s+', '', p) for p in step}
        stride = None
        for p in step:
            hit = re.fullmatch(rf'{companion}\s*\+=\s*(.+)', p, re.S)
            if hit and _SIMPLE.fullmatch(hit[1].strip()):
                stride = hit[1].strip()
        if stride is None or not ({f'{counter}++', f'++{counter}'} & bumps):
            continue
        value = companion_set[2].strip()
        if re.search(rf'\b(?:{counter}|{companion})\b', value) or re.search(r'[(=?]', value):
            continue
        return counter, companion, value, stride
    return None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    out = []
    for hit in _FOR.finditer(clean, opening, span[1]):
        head_open = hit.end() - 1
        head_close = close(clean, head_open)
        if head_close is None or head_close > span[1]:
            continue
        found = _header(clean[head_open + 1:head_close - 1])
        if not found:
            continue
        counter, companion, value, stride = found
        body_open = head_close
        while body_open < span[1] and clean[body_open].isspace():
            body_open += 1
        if body_open >= span[1] or clean[body_open] != '{':
            continue
        body_close = close(clean, body_open, '{', '}')
        if body_close is None or body_close > span[1]:
            continue
        body = clean[body_open:body_close]
        if _assigned(body, companion) or (_SIMPLE.fullmatch(stride) and re.fullmatch(_ID, stride)
                                          and (_assigned(body, stride) or stride == counter)):
            continue
        after = clean[body_close:span[1] - 1]
        if re.search(rf'\b{companion}\b', after) or any(_assigned(body, n) for n in re.findall(_ID, value)):
            continue
        if not re.search(rf'\b{companion}\b', body):
            continue
        head = f'for ({counter} = 0; {clean[head_open + 1:head_close - 1].split(";")[1].strip()}; {counter}++)'
        for product in (f'{counter} * {stride}', f'{stride} * {counter}'):
            new_body = re.sub(rf'\b{companion}\b', f'{value} + {product}', source[body_open:body_close])
            child = source[:hit.start()] + head + source[head_close:body_open] + new_body + source[body_close:]
            new_span = find(child, name)
            decl = re.compile(rf'\n[ \t]*(?:s32|int|u32|s16|u16)\s+{companion}\s*;[ \t]*(?=\n)')
            if new_span and len(re.findall(rf'\b{companion}\b', _blank(child)[new_span[0]:new_span[1]])) == 1:
                child = child[:new_span[0]] + decl.sub('', child[new_span[0]:new_span[1]], count=1) + child[new_span[1]:]
            out.append((FAMILY, child))
    return [x for x in out if x[1] != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
