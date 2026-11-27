"""A call's product and the stores of its shifted result, written one step at a time through the function's own locals.

A fixed-point vector step is often drafted as `vx = f(angle) * speed; obj->x = -(vx >> 12); obj->y = vy >> 12;`. On
SN64 GCC 2.8.1 (N64, `-mfp64`) that leaves registers wrong in the last rows only: the target shifted a narrow call's
result through a second register (`sll $v0, $v0, 16; sra $s1, $v0, 16`), multiplied into the same variable, negated
into another register and shifted `vy` where it was. A 68-instruction velocity routine went to 0 with the
steps below together; each of the first edits alone leaves rows behind, so they are also offered as one child:

  - `x = f(a) * s;` as `x = f(a); x *= s;`
  - a call whose prototype in the source returns `s16` or `s8`, declared as returning `s32` and sign-extended by hand
    through a local that is dead there: `d = f(a) << 16; x = d >> 16;`. Only when the function calls `f` once, so no
    other result changes width
  - `p->m = x >> k;` as `x >>= k; p->m = x;` when `x` is not read again
  - `p->m = -(x >> k);` as `x >>= k; d = -x; p->m = d;`, and `p->m = -x;` as `d = -x; p->m = d;`, `d` a dead local
    (a new temporary did not move the rows: the variable has to be one the function already uses)
  - a product's local replaced from that statement on by a local the function no longer names, alone and with the
    steps above (the target held the second product where the first call's result had been)

Hypothesis (SN's 2.8.1 passes have no public source): local-alloc ties a shift's intermediate to its destination when
both live in one block, and a variable the function uses in more than one block is left to global allocation. The
measured fact: on that one function, from the plain draft with a `do { } while (0)` around the constant the arm
assigns (140), one child of this module scores 0. The candidate is never a verdict: the judge decides.
"""
import re

from .csource import _blank, find
from .dead_local_stage_repairs import _dead, _loops
from .global_pointer_run_repairs import _blocks
from .pattern_repairs import close

FAMILY = 'call_product_stage'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_WORD = re.compile(rf'(?m)^[ \t]*(?:s32|int)\s+({_ID})\s*;')
_LEAD = r'(?<=[;{}])(?P<indent>\s*)'
_CALL = rf'(?P<call>(?P<callee>{_ID})\s*\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\))'
_PRODUCT = re.compile(rf'{_LEAD}(?P<x>{_ID})\s*=\s*{_CALL}\s*(?:\*\s*(?P<by>{_ID}))?\s*;')
_MEMBER = rf'(?P<dest>{_ID}(?:->|\.){_ID}(?:(?:->|\.){_ID})*)'
_SHIFTED = re.compile(rf'{_LEAD}{_MEMBER}\s*=\s*(?P<neg>-)?\s*(?:\(\s*(?P<x>{_ID})\s*>>\s*(?P<k>\d+)\s*\)|(?P<y>{_ID})\s*>>\s*(?P<j>\d+))\s*;')
_NEGATED = re.compile(rf'{_LEAD}{_MEMBER}\s*=\s*-\s*(?P<x>{_ID})\s*;')
_FENCE_END = re.compile(r'\s*\}\s*while\s*\(\s*0\s*\)')
_NARROW = {'s16': 16, 's8': 24}
_CHOICES = 3


def _context(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', clean[opening:end]):
        return None
    # a `do { } while (0)` fence has no back edge: a value read before the statement is not read again after it
    loops = [(start, stop) for start, stop in _loops(clean, opening, end) if not _FENCE_END.match(clean, stop)]
    return clean, opening, end, list(_blocks(clean, opening, end)), loops, _WORD.findall(clean[opening:end])


def _free(context, local, start, stop):
    """`local` holds nothing that is read after the statement from `start` to `stop`."""
    clean, opening, end, blocks, loops, _ = context
    return _dead(clean, opening, end, blocks, loops, local, stop, start)


def _spare(context, hit, used):
    """The word locals that are free at the statement `hit` and not named in it."""
    start, stop = hit.start() + len(hit['indent']), hit.end()
    return [local for local in context[5]
            if local not in used and _free(context, local, start, stop)][:_CHOICES]


def _narrow_return(clean, opening, callee):
    """(match of the one `s16 callee(` prototype, shift) when the function calls `callee` exactly once, else None."""
    prototypes = list(re.finditer(rf'(?m)^[ \t]*(?:extern\s+)?(?P<type>{_ID})\s+{callee}\s*\([^;{{}}]*\)\s*;', clean[:opening]))
    if len(prototypes) != 1 or prototypes[0]['type'] not in _NARROW:
        return None
    if len(re.findall(rf'\b{callee}\s*\(', clean[opening:])) != 1:
        return None
    return prototypes[0], _NARROW[prototypes[0]['type']]


def _products(context):
    """[(start, end, text, [])]: each `x = f() * s;` split."""
    clean, opening, end, *_ = context
    edits = []
    for hit in _PRODUCT.finditer(clean, opening, end):
        if hit['x'] in context[5] and hit['by'] and hit['by'] != hit['x']:
            text = f"{hit['x']} = {hit['call']};{hit['indent']}{hit['x']} *= {hit['by']};"
            edits.append((hit.start('x'), hit.end(), text, []))
    return edits


def _extensions(context, spare_index):
    """[(start, end, text, [prototype edit])]: each single narrow call sign-extended through a spare local."""
    clean, opening, end, *_ = context
    edits = []
    for hit in _PRODUCT.finditer(clean, opening, end):
        if hit['x'] not in context[5]:
            continue
        narrow = _narrow_return(clean, opening, hit['callee'])
        spare = _spare(context, hit, {hit['x'], hit['by']}) if narrow else []
        if len(spare) <= spare_index:
            continue
        prototype, shift = narrow
        local, indent, x = spare[spare_index], hit['indent'], hit['x']
        text = f"{local} = {hit['call']} << {shift};{indent}{x} = {local} >> {shift};"
        if hit['by']:
            text += f"{indent}{x} *= {hit['by']};"
        edits.append((hit.start('x'), hit.end(), text, [(prototype.start('type'), prototype.end('type'), 's32')]))
    return edits


def _stores(context, spare_index):
    """[(start, end, text, [])]: each member store of a shifted or negated word local taken in steps."""
    clean, opening, end, *_ = context
    edits = []
    for hit in _SHIFTED.finditer(clean, opening, end):
        x, k = hit['x'] or hit['y'], hit['k'] or hit['j']
        if x not in context[5] or not _free(context, x, hit.start('dest'), hit.end()):
            continue
        indent, dest = hit['indent'], hit['dest']
        if hit['neg']:
            spare = _spare(context, hit, {x})
            if not spare:
                continue
            local = spare[min(spare_index, len(spare) - 1)]
            text = f"{x} >>= {k};{indent}{local} = -{x};{indent}{dest} = {local};"
        else:
            text = f"{x} >>= {k};{indent}{dest} = {x};"
        edits.append((hit.start('dest'), hit.end(), text, []))
    for hit in _NEGATED.finditer(clean, opening, end):
        spare = _spare(context, hit, {hit['x']}) if hit['x'] in context[5] else []
        if spare:
            local = spare[min(spare_index, len(spare) - 1)]
            text = f"{local} = -{hit['x']};{hit['indent']}{hit['dest']} = {local};"
            edits.append((hit.start('dest'), hit.end(), text, []))
    return edits


def _apply(source, edits):
    """`source` with every edit made; an edit overlapping an earlier one is left out."""
    spans = {}
    for start, end, text, more in edits:
        if any(start < e and s < end for s, (e, _) in spans.items()):
            continue
        spans[start] = (end, text)
        for s, e, replacement in more:
            spans[s] = (e, replacement)
    for start in sorted(spans, reverse=True):
        end, text = spans[start]
        source = source[:start] + text + source[end:]
    return source


def _renamed(source, context):
    """`source` with one product's local replaced, from that statement on, by a local that is never named again."""
    clean, opening, end, *_ = context
    out = []
    for hit in _PRODUCT.finditer(clean, opening, end):
        x, at = hit['x'], hit.start('x')
        if x not in context[5] or not hit['by'] or len(re.findall(rf'\b{x}\b', clean[opening:at])) > 1:
            continue  # one mention before the statement is the declaration
        for local in _spare(context, hit, {x, hit['by']}):
            if re.search(rf'(?<![\w.>]){local}\b', clean[at:end]):
                continue
            text = source
            for use in reversed([m for m in re.finditer(rf'(?<![\w.>]){x}\b', clean[:end]) if m.start() >= at]):
                text = text[:use.start()] + local + text[use.end():]
            out.append(text)
    return out[:_CHOICES * 2]


def _steps(source, context, singles=True):
    """The children that write `source`'s products and stores in steps; `singles` adds the one-edit children."""
    children, products = [], _products(context)
    for index in range(_CHOICES):
        extensions, stores = _extensions(context, index), _stores(context, index)
        # the whole step first; then one call extended at a time (the target extended one of two narrow calls);
        # then without each of the three parts, then one edit at a time
        for group in [extensions + products + stores] + [[edit] + products + stores for edit in extensions] + \
                [extensions + products, products + stores, extensions + stores]:
            children.append(_apply(source, group))
        if singles:
            children.extend(_apply(source, [edit]) for edit in extensions + stores)
    if singles:
        children.extend(_apply(source, [edit]) for edit in products)
    return children


def variants(source, name):
    context = _context(source, name)
    if not context:
        return []
    children = _steps(source, context)
    for renamed in _renamed(source, context):
        inner = _context(renamed, name)
        children.append(renamed)
        if inner:
            children.extend(_steps(renamed, inner, singles=False))  # only the combined steps, to stay small
    return [(FAMILY, child) for child in dict.fromkeys(children) if child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
