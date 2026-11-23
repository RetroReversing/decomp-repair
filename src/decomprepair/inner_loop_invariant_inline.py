"""A value m2c named once per outer pass because the inner loop only reads it, written where the inner loop uses it.

gcc 2.x's loop pass moves a loop-invariant expression out of the inner loop on its own, and m2c prints what it sees: the
expression assigned to a local between the two loops (`temp_ft1 = (f32) ((f64) (f32) var_t6 + 0.5);`,
`temp_t9 = var_t7 + (arg11 - var_t6);`, built from the outer loop's counters) and read inside the inner one. The game wrote
the expression at the use and the pass did the hoisting; the draft's local is a second variable with a live range of its
own across the inner loop, and the first scheduler's and the allocator's view of that loop depend on it. On a
315-instruction tile-rectangle builder (KMC GCC 2.7.2) writing those two back where they are read was 9894 -> 8832 and
the largest single step of the rest, with the later steps still to find (its match needs both). `hoisted_invariant_inline`
does the same for an invariant built from parameters only; this one takes locals and floats: the operands may be any local
that nothing assigns between the assignment and the end of the loop that reads it.

A candidate is a local assigned exactly once, by a plain statement `L = E;`, where E has no call, no assignment, no
increment and no address-of local (a game global may be read when nothing in the function writes it), and every read of L
is inside one do/while/for loop that starts after the assignment, with no mention of L between the assignment and that
loop. Every operand of E is a name no statement assigns after the assignment and before the loop's end (checked by text, so
a counter stepped at the foot of the loop is the loop's own and refuses). Every read becomes `(E)`; the assignment and the
declaration go ('inline'); or the assignment goes to the top of the loop's body and the declaration stays ('sink', the
value recomputed on each pass, which the loop pass hoists again: the form that matched the same builder for a float that
two arms read). Each local alone in each form (at most 6 locals), all of them in each form, and with up to three locals
every mix of the two. A hypothesis about the compiler's
choice; the exact judge decides."""
import itertools
import re

from .hoisted_invariant_inline import _loops
from .integer_repair_support import IDENT, edit, view

FAMILY = 'inner_loop_invariant_inline'
FAMILIES = (FAMILY,)
LIMIT = 6
_PLAIN = re.compile(rf'(?P<n>{IDENT})\s*=(?!=)\s*(?P<v>[^;{{}}]+);')
_TYPES = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 'f32', 'f64', 'int', 'unsigned', 'long', 'short', 'char', 'signed', 'float',
          'double', 'sizeof'}
_CAST = re.compile(r'\(\s*(?:unsigned\s+|signed\s+)?(?:s8|u8|s16|u16|s32|u32|f32|f64|int|long|short|char|float|double)\s*\)')


def _pure(expression):
    text = _CAST.sub(' ', expression)
    if re.search(r'\w\s*\(|\+\+|--|(?<![=!<>])=(?!=)|\?|,|\[|\]|->|\.\D', text) or re.search(r'(?:^|[(+\-*/%|^~<>!&])\s*&(?!&)', text):
        return False
    return True


def _written(clean, name, start, end):
    return bool(re.search(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?<![\w.>])(?:\+\+|--)\s*{re.escape(name)}\b|'
                          rf'(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)|&\s*{re.escape(name)}\b', clean[start:end]))


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, opening, end = part.clean, part.opening, part.end
    loops = _loops(clean, opening + 1, end)
    sites = []
    for hit in _PLAIN.finditer(clean, opening + 1, end):
        local, expression = hit['n'], hit['v'].strip()
        declaration = re.search(rf'(?m)^[ \t]*(?:register[ \t]+)?(?:unsigned[ \t]+|signed[ \t]+)?[A-Za-z_]\w*[ \t]+{re.escape(local)}[ \t]*;[ \t]*\n',
                                clean[opening:end])
        if not declaration or not _pure(expression):
            continue
        if len(re.findall(rf'(?<![\w.>]){re.escape(local)}\s*=(?!=)', clean[opening:end])) != 1 \
                or re.search(rf'(?<![\w.>]){re.escape(local)}\s*(?:[-+*/%&|^]|<<|>>)=(?!=)|(?<![\w.>])(?:\+\+|--)\s*{re.escape(local)}\b|'
                             rf'(?<![\w.>]){re.escape(local)}\s*(?:\+\+|--)|&\s*{re.escape(local)}\b', clean[opening:end]):
            continue
        reads = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', clean[hit.end():end])]
        if not reads:
            continue
        first = hit.end() + reads[0].start()
        loop = next((span for span in loops if span[0] > hit.end() and span[0] < first < span[1]), None)
        if loop is None or any(not loop[0] < hit.end() + m.start() < loop[1] for m in reads) \
                or re.search(rf'\b{re.escape(local)}\b', clean[hit.end():loop[0]]):
            continue
        operands = {n for n in re.findall(IDENT, _CAST.sub(' ', expression)) if n not in _TYPES}
        if local in operands or any(_written(clean, n, hit.end(), loop[1]) for n in operands):
            continue
        sites.append((hit, declaration, reads, expression, loop))
    if not sites:
        return []
    sites = sites[:LIMIT]
    # per local: written at its uses ('inline') or assigned again at the top of the loop body ('sink', the value is then
    # recomputed on each pass: the form the target's loop pass hoisted from)
    out = []
    plans = [[(site, mode) for site in sites] for mode in ('inline', 'sink')]
    if 1 < len(sites) <= 3:
        plans += [[(site, mode) for site, mode in zip(sites, combo)] for combo in itertools.product(('inline', 'sink'), repeat=len(sites))]
    plans += [[(site, mode)] for site in sites for mode in ('inline', 'sink')]
    for plan in plans:
        edits = []
        for (hit, declaration, reads, expression, loop), mode in plan:
            edits.append((hit.start(), hit.end(), ''))
            if mode == 'sink':
                edits.append((loop[0] + 1, loop[0] + 1, f' {hit["n"]} = {expression};'))
                continue
            edits.append((opening + declaration.start(), opening + declaration.end(), ''))
            simple = re.fullmatch(rf'{IDENT}|-?\d+', expression) is not None
            for m in reads:
                edits.append((hit.end() + m.start(), hit.end() + m.end(), expression if simple else f'({expression})'))
        out.append((FAMILY, edit(source, edits)))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 99}  # the registry: no caller wiring (registry.py)
