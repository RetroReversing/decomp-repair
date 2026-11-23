"""An indirect call's function pointer loaded into an integer temp that is dead by then, just after the temp's last read.

`R = G(args);` with `G` a global function pointer: GCC 2.7.2 loads `G` into a fresh pseudo at the call
(`prepare_call_address`). That pseudo is set once, so the first scheduler's `adjust_priority` (sched.c) treats the load
as a *birthing* insn and raises it to the launch priority as soon as the call is scheduled: it wins every tie with the
value the arguments are built from and lands right before the call, after the last argument's arithmetic. Written as
`V = (s32) G; R = ((T (*)(P)) V)(args);` with `V` an integer local whose value is dead from there on, the load sets a
pseudo with several sets (no launch priority) and has an anti-dependence on `V`'s last read: it is scheduled straight
after that read, and because `V` and the pointer are one pseudo they share one hard register.

The case (KMC GCC 2.7.2, `-O2 -G0 -mips3`): an audio setup function allocating `size * 2` bytes through
`gDataBankAlloc`. The quotient `(q / 192)` lived in `$v1`, the product in `$v0`, the pointer load sat between the
product's last shift and `addiu $a2, $v0, 0xc0` in `$v1`; every spelling with a direct call put the load after the
`addiu` (launch priority) or in `$v0` (a fresh pseudo after the product's death), 255. Holding the quotient in the
dead rate local and loading the pointer into it after the product (`temp_v0 = (s32) gDataBankAlloc;`) was exact
(255 -> 0; with the product held in a local that a later block reassigns, so local-alloc does not tie it to the size).
The scheduler reading is from sched.c (`adjust_priority`, `birthing_insn_p`); the judge decides each child.

The child (`call_pointer_dead_temp`, one per call and temp, bounded) inserts `V = (s32) G;` right after the statement
holding `V`'s last mention before the call, in the call's own block, and calls through `V`, when:
- `G` is declared in the source or header as a function pointer (`T (*G)(P);`);
- `V` is an integer local declared in the function (no pointer, array or `volatile`);
- `V` is not mentioned between that statement and the call, and after the call its next mention is a plain assignment.
"""
import re

from .csource import _blank, find
from .reassigned_local_inline import IDENT, _match

FAMILY = 'call_pointer_dead_temp'
FAMILIES = (FAMILY,)
LIMIT = 8
INTEGER = r'(?:unsigned\s+|signed\s+)?(?:u8|s8|u16|s16|u32|s32|int|long|short|char)'


def _pointers(text):
    """Function-pointer globals: name -> (return type, parameter list)."""
    found = {}
    for hit in re.finditer(rf'(?:^|[;}}\n])\s*(?:extern\s+|static\s+)?((?:const\s+)?{IDENT}(?:\s*\*)*)\s*\(\s*\*\s*({IDENT})'
                           r'\s*\)\s*\(([^()]*)\)\s*;', text):
        found.setdefault(hit[2], (hit[1].strip(), hit[3].strip()))
    return found


def _block_of(clean, at, opening, end):
    """The innermost `{` before `at` whose block contains it."""
    depth, i = 0, at - 1
    while i > opening:
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            if depth == 0:
                return i
            depth -= 1
        i -= 1
    return opening


def _statement_ends(clean, start, stop):
    """Offsets just past each `;` or `}` that ends a statement at the block's own depth."""
    ends, depth, paren = [], 0, 0
    for i in range(start, stop):
        c = clean[i]
        if c == '(':
            paren += 1
        elif c == ')':
            paren -= 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and paren == 0 and not re.match(r'\s*(?:else\b|while\b|;)', clean[i + 1:stop]):
                ends.append(i + 1)
        elif c == ';' and depth == 0 and paren == 0:
            ends.append(i + 1)
    return ends


def variants(source, name, header=''):
    clean = _blank(source)
    span = find(source, name)
    if not span:
        return []
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    pointers = _pointers(_blank(header or '') + '\n' + clean[:start])
    if not pointers:
        return []
    body = clean[opening:end]
    declared = {}
    for hit in re.compile(rf'(?<![\w*])(?:const\s+)?{INTEGER}\s+(?!\*)({IDENT})\s*[;=,]').finditer(clean, opening, end):
        declared.setdefault(hit[1], hit.start())
    for hit in re.finditer(rf'volatile[^;]*?\b({IDENT})\s*[;=,\[]', body):
        declared.pop(hit[1], None)
    declaration = re.compile(rf'\s*(?:const\s+)?{INTEGER}\s+[\w\s,=*]*$')
    result = []
    for call in re.finditer(rf'(?<![\w.>&]){"|".join(map(re.escape, pointers))}\s*\(', clean[opening:end]):
        at = opening + call.start()
        callee = re.match(IDENT, clean[at:])[0]
        if re.match(r'\s*=(?!=)', clean[at + len(callee):]):
            continue
        ret, params = pointers[callee]
        block = _block_of(clean, at, opening, end)
        stop = clean.rfind(';', block, at)
        head = max(stop, clean.rfind('{', block, at), clean.rfind('}', block, at)) + 1
        call_end = clean.find(';', at)
        ends = [e for e in _statement_ends(clean, block + 1, head) if e <= head]
        for var in sorted(declared):
            scope = _block_of(clean, declared[var], opening, end)
            if _match(clean, scope) < at:
                continue
            mention = re.compile(rf'(?<![\w.>]){re.escape(var)}\b')
            if mention.search(clean, head, call_end + 1):
                continue
            later = mention.search(clean, call_end + 1, end)
            if later and not re.match(r'\s*=(?!=)', clean[later.end():]):
                continue
            last = None
            for hit in mention.finditer(clean, block + 1, head):
                last = hit
            if last is None:
                continue
            after = [e for e in ends if e > last.end()]
            if not after:
                continue
            insert = after[0]
            begin = max([e for e in ends if e <= last.start()] + [block + 1])
            if declaration.match(clean[begin:last.start()]):
                continue
            if mention.search(clean, insert, head):
                continue
            cast = 'u32' if re.search(rf'\bu32\s+(?:[^;]*,\s*)?{re.escape(var)}\b', body) else 's32'
            typed = f'(({ret} (*)({params})) {var})'
            text = (source[:insert] + f' {var} = ({cast}) {callee};' + source[insert:at] + typed
                    + source[at + len(callee):])
            if text != source and text not in result:
                result.append(text)
    return [(FAMILY, text) for text in result[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 60}  # the registry: no caller wiring (registry.py)
