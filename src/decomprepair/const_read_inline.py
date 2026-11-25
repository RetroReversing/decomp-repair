"""Locals that only copy reads through read-only pointers written at their uses, with those pointers `const`.

m2c names every intermediate of a vector or plane routine (`f32 dy1 = p2->y - p1->y;`) and reuses it. The game's code
often wrote the differences inside the products instead, and gcc 2.7.2 (KMC, N64) only gives the loads the target's
order and registers when two things hold together: the pointers are `const` (a load from read-only memory may be lifted
among the prologue's saves and is shared across the stores through the output pointer), and the reads are written at
their uses so the loads are expanded where the products are. A plane-from-three-points routine (95 instructions),
`s32 f(Pl *out, V3 *p1, V3 *p2, V3 *p3)`, went 480 -> 240 with `const` alone (`const_read`), 7323 with the inlining
alone (the stores through `out` may alias the plain `p1`, so every use reloaded), 10 with both, and 0 once one
difference (`p2->z - p1->z`) stayed a local: no one step of those was reachable from the others, and the saved best was
480. The compiler's explanation (the order of the first loads follows the order the expander meets them, and `const`
loads schedule among the prologue's saves) is a hypothesis, not read in the compiler's source.

Variants, each with every read-only pointer parameter made `const` in the same edit: all the copy locals inlined, and
the same with one multi-use local kept in its place (its inlined neighbours reading it by name). The inlined value is
the expression the local held, so the program reads the same memory the same way as long as the stores through the
other pointers do not alias the const ones: the assumption `const` itself states. A local is a copy local when its
expression is pure arithmetic on const-able pointer reads, literals and earlier copy locals.
"""
import re

from .const_read_repairs import _written
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'const_read_inline'
FAMILIES = (FAMILY,)

PARAM = re.compile(r'^(\s*)(const\s+)?((?!const\b)[A-Za-z_][\w ]*?)\s*\*\s*(\w+)\s*$')
LOCAL = re.compile(r'(?m)^([ \t]*)((?:unsigned\s+)?[A-Za-z_]\w*)[ \t]+(\w+)[ \t]*=[ \t]*([^;{}\n]+);[ \t]*\n')
FIELD = re.compile(r'->\s*\w+|\.\s*\w+')
ATOM = re.compile(r'[\w.>\-\[\]]+\Z')
MAX_KEPT = 8


def _copy_locals(body, depth_one, pointers):
    """[(start, end, name, expression)] of the copy locals declared directly in the function's body."""
    found, names = [], set()
    for decl in LOCAL.finditer(body):
        if decl.start() not in depth_one or decl[2] in ('return', 'else', 'goto', 'case'):
            continue
        expr = decl[4].strip()
        if re.search(r'\w\s*\(|\+\+|--|[^=!<>]=[^=]|&&|\|\||\?|;', expr) or re.search(r'(?<![-\w\s)\]])&|&(?=[A-Za-z_])', expr):
            continue
        bare = FIELD.sub(' ', expr)
        idents = set(re.findall(r'[A-Za-z_]\w*', bare))
        if not (idents <= pointers | names) or not re.search(r'->|\[', expr) or not (idents & pointers):
            continue
        # only the local's single assignment: a later write to it makes it a variable, not a copy
        if re.search(rf'(?<![\w.>]){decl[3]}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{decl[3]}\b|\b{decl[3]}\s*(?:\+\+|--)|&\s*{decl[3]}\b', body[decl.end():]):
            continue
        found.append((decl.start(), decl.end(), decl[3], expr))
        names.add(decl[3])
    return found


def _python_top_level(clean_body):
    """Offsets in the body that sit directly inside the function's braces (not in a nested block)."""
    depth, offsets = 0, set()
    for index, char in enumerate(clean_body):
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        elif depth == 1 and (index == 0 or clean_body[index - 1] == '\n'):
            offsets.add(index)
    return offsets


_top_level = _python_top_level
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _top_level(clean_body):
        found = _scan.line_starts_at_depth_one(clean_body)
        return _python_top_level(clean_body) if found is NotImplemented else found


def _substitute(expr, values):
    for name, value in values.items():
        wrapped = value if ATOM.match(value) else '(' + value + ')'
        expr = re.sub(rf'(?<![\w.>]){name}\b', lambda _, w=wrapped: w, expr)
    return expr


def variants(source, name, asm=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    paren = clean.find('(', span[0], span[1])
    opening = clean.find('{', span[0], span[1])
    if paren < 0 or opening < 0 or (end := close(clean, opening, '{', '}')) is None:
        return []
    shut = close(clean, paren, '(', ')')
    if shut is None or shut > opening:
        return []
    shut -= 1
    params, body, clean_body = source[paren + 1:shut], source[opening:end], clean[opening:end]
    pieces = params.split(',')
    pointers, make = set(), {}
    for k, piece in enumerate(pieces):
        hit = PARAM.match(piece)
        if hit and not _written(body, hit[4]):
            pointers.add(hit[4])
            if not hit[2]:
                make[k] = piece[:hit.start(3)] + 'const ' + piece[hit.start(3):]
    if not pointers:
        return []
    top = _top_level(clean_body)
    locals_ = _copy_locals(clean_body, top, pointers)
    if not locals_:
        return []
    # (a local read before it is assigned, or not read at all, is not a copy to inline)
    uses = {n: len(re.findall(rf'(?<![\w.>]){n}\b', clean_body[e:])) for _, e, n, _ in locals_}
    locals_ = [item for item in locals_ if uses[item[2]]]
    if not locals_:
        return []
    kept_choices = [None] + [n for _, _, n, _ in locals_ if uses[n] >= 2][:MAX_KEPT]
    new_params = ','.join(make.get(k, piece) for k, piece in enumerate(pieces))
    found = []
    for kept in kept_choices:
        values, edits = {}, []
        for start, stop, local, expr in locals_:
            expr = _substitute(expr, values)
            if local == kept:
                edits.append((start, stop, body[start:stop].replace(body[start:stop].split('=', 1)[1].strip().rstrip(';'), expr, 1)))
            else:
                values[local] = expr
                edits.append((start, stop, ''))
        text = body
        for start, stop, replacement in reversed(edits):
            text = text[:start] + replacement + text[stop:]
        for local, value in values.items():
            wrapped = value if ATOM.match(value) else '(' + value + ')'
            text = re.sub(rf'(?<![\w.>]){local}\b', lambda _, w=wrapped: w, text)
        candidate = source[:paren + 1] + new_params + source[shut:opening] + text + source[end:]
        if candidate != source and (FAMILY, candidate) not in found:
            found.append((FAMILY, candidate))
    return found
