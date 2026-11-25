"""A dead pointer local reused for the address a later loop walks, with the one-shot scope moved to match.

m2c names every value once, but the game's code reused a pointer variable: a pointer to one record that is dead after its
last use, then pointed at the table a counted loop walks. The reuse ties the two lifetimes into one register web, so the
global allocator's priority for the pointer (reference count over live length) changes with it, and with it which of
the early values shares a register with which. On a KMC `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2` menu-update
function the reuse alone made the score worse (65 -> 110: the pointer's priority rose above a value that has to come
first), and only with the function-wide `do { } while (0)` scope narrowed to start at the loop (the references before
it are then counted one loop level less) did the registers fall as in the target (110 -> 20). The two edits pay off
together, so a child carries both (`dead_pointer_reuse_fence_shift`); the reuse alone is `dead_pointer_address_reuse`.

The pointer is a local declared with `&symbol` (or assigned it) whose uses are all before a later loop; the loop
reads another `&symbol` that is not the pointer's own; one assignment `p = (T *)&symbol;` is put before the loop and the
loop's `&symbol` become `p`. The fence shift is offered only when the whole body after the declarations is one
`do { } while (0);` and the loop sits in a brace block of its own (the new scope runs from the loop to the end of that
block). A candidate for the exact judge, never a verdict."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

REUSE = 'dead_pointer_address_reuse'
SHIFT = 'dead_pointer_reuse_fence_shift'
FAMILIES = (REUSE, SHIFT)
LIMIT = 4
POINTER = re.compile(rf'(?P<type>\b[A-Za-z_][\w\s]*?)\s*\*\s*(?P<p>{IDENT})\s*=\s*&\s*(?P<s>{IDENT})\s*;')
LOOP = re.compile(r'\b(?:do|for|while)\b')


def _loops(clean, floor, end):
    """(start, body_open, body_end) of each `do {` / `for (...) {` / `while (...) {` statement."""
    found = []
    for m in LOOP.finditer(clean, floor, end):
        at = m.end()
        if m[0] != 'do':
            paren = clean.find('(', at)
            if paren < 0 or clean[at:paren].strip():
                continue
            at = close(clean, paren)
            if not at:
                continue
            if m[0] == 'while' and re.match(r'\s*;', clean[at:]):
                continue  # the tail of a do-while
        brace = re.match(r'\s*\{', clean[at:])
        if not brace:
            continue
        open_at = at + brace.end() - 1
        body_end = close(clean, open_at, '{', '}')
        if body_end:
            found.append((m.start(), open_at, body_end))
    return found


def _python_enclosing(clean, at, floor):
    depth = 0
    for pos in range(at - 1, floor - 1, -1):
        if clean[pos] == '}':
            depth += 1
        elif clean[pos] == '{':
            if depth == 0:
                end = close(clean, pos, '{', '}')
                return (pos, end) if end and end > at else None
            depth -= 1
    return None


_enclosing = _python_enclosing
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _enclosing(clean, at, floor):
        found = _scan.enclosing_open(clean, at, floor, -1)
        if found is not NotImplemented:
            if found < 0:
                return None
            end = close(clean, found, '{', '}')
            return (found, end) if end and end > at else None
        return _python_enclosing(clean, at, floor)


def _outer_fence(clean, opening, end):
    """(do_start, brace_end, while_start, while_end) of a body made of declarations and one `do { } while (0);`."""
    tail = re.search(r'(?P<c>\})\s*while\s*\(\s*0\s*\)\s*;(?P<rest>\s*\}\s*)$', clean[opening:end])
    if not tail:
        return None
    while_start = opening + tail.start('c')
    start, depth = None, 0
    for pos in range(while_start, opening, -1):
        if clean[pos] == '}':
            depth += 1
        elif clean[pos] == '{':
            depth -= 1
            if depth == 0:
                start = pos
                break
    if start is None:
        return None
    head = re.search(r'\bdo\s*$', clean[opening + 1:start])
    if not head or '(' in clean[opening + 1:opening + 1 + head.start()]:
        return None
    return opening + 1 + head.start(), start + 1, while_start, opening + tail.start('rest')


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    loops = _loops(clean, part.opening, part.end)
    fence = _outer_fence(clean, part.opening, part.end)
    out = []
    for m in POINTER.finditer(clean, part.opening, part.end):
        pointer, own = m['p'], m['s']
        uses = [u.start() for u in re.finditer(rf'\b{pointer}\b', clean[m.end():part.end])]
        for start, open_at, body_end in loops:
            if start < m.end() or any(m.end() + u >= start for u in uses):
                continue
            body = clean[open_at:body_end]
            for symbol in dict.fromkeys(re.findall(rf'&\s*({IDENT})\b(?!\s*[\[.])(?!\s*->)', body)):
                if symbol == own or symbol == pointer:
                    continue
                inner = re.sub(rf'&\s*{symbol}\b', pointer, source[open_at:body_end])
                assign = f'{pointer} = ({m["type"].strip()} *) &{symbol};\n  '
                base = [(open_at, body_end, inner), (start, start, assign)]
                out.append((REUSE, edit(source, base)))
                block = _enclosing(clean, start, part.opening)
                if fence and block and block[0] > fence[1] and block[1] <= fence[2]:
                    shifted = [(open_at, body_end, inner), (start, start, assign + 'do {\n  '),
                               (fence[0], fence[1], '{'), (fence[2], fence[3], '}'),
                               (block[1] - 1, block[1] - 1, '} while (0);\n')]
                    out.append((SHIFT, edit(source, shifted)))
    seen, result = set(), []
    for family, text in out[:2 * LIMIT]:
        if text != source and text not in seen:
            seen.add(text)
            result.append((family, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 150}
