"""A pointer local's one read in a statement taken through a fenced scratch copy: `{ T *p; do { p = v; } while (0); f(p + off); }`.

GCC 2.x gives the saved registers to pseudos in order of `floor_log2(refs) * refs / live length` (global.c), and flow.c
counts a reference once more for every loop it sits in. `do { p = v; } while (0);` is one loop round a single read of `v`,
at no instruction cost (the copy is the same register), so it adds weight to `v` alone, where `local_weight_ladder`
wraps all of a local's statements together and `call_weight_ladder` the calls. A function whose saved registers are
rotated between a few locals that all live the length of two loops (a texture pointer, two scale factors) can be one
reference away from the target's order, and the one-statement fence is the smallest step that moves a single local.

Two sibling N64 display-list builders (KMC-built `-G0 -mips3 -O2` SN GCC 2.8.1, 421 and 437 instructions, one 16-bit and
one 32-bit texture loop each) sat at 80 and 70 with the texture pointer, the second scale factor and the first scale
factor in the saved registers in the wrong order. `call_weight_ladder` reached 20 with four statements two deep, which
disturbed the temporaries of one of them; the pointer's own read in the first loop's first statement,
`GFX(0xFD100000, (u32)(data + off));` as `{ u8 *p; do { p = data; } while (0); GFX(0xFD100000, (u32)(p + off)); }`, was
exact in both (0). The wrappers are scaffolding no developer wrote; polishing removes them once the match is recorded.
That the extra reference is what moves the allocation is a hypothesis from the allocation table, not confirmed in the
compiler source.

`variants` offers, for each plain pointer local and each statement that reads it once (and does not assign it), that
statement rewritten with the scratch copy one and two scopes deep, and the same for every such statement of that local at
once. The judge decides; no child is a verdict."""
import re

from .integer_repair_support import edit, view
from .local_weight_ladder import _declaration, units

FAMILY = 'local_read_fence'
FAMILIES = (FAMILY,)
LIMIT = 60
DEPTHS = (1, 2)


def _pointers(source, name):
    """{name: declared type text, e.g. 'u8 *'} of the function's plain pointer locals."""
    part = view(source, name)
    found = {}
    if not part:
        return found
    for text in part.clean[part.opening + 1:part.end].split('\n'):
        match = _declaration(text)
        if match and '*' in match['gap'] and not match['init']:
            found[match['name']] = f"{match['type']} {'*' * match['gap'].count('*')}"
    return found


def _fenced(text, local, declared, depth):
    """The statement with its one read of `local` taken through a fenced scratch copy, or None."""
    scratch = f'__fence_{local}'
    read = re.compile(rf'(?<![\w.>]){re.escape(local)}\b(?!\s*(?:[-+*/%&|^]|<<|>>)?=(?!=))')
    if len(read.findall(text)) != 1:
        return None
    body = read.sub(scratch, text.strip(), count=1)
    fence = 'do { ' * depth + f'{scratch} = {local};' + ' } while (0);' * depth
    return f'{{ {declared}{scratch}; {fence} {body} }}'


def variants(source, name):
    pointers = _pointers(source, name)
    if not pointers:
        return []
    found, _ = units(source, name)
    result, seen = [], set()

    def add(text):
        if text != source and text not in seen:
            seen.add(text)
            result.append((FAMILY, text))

    for local, declared in sorted(pointers.items()):
        reads = [(start, end, text) for start, end, text, counts in found if counts.get(local) == 1]
        for depth in DEPTHS:
            edits = []
            for start, end, text in reads:
                fenced = _fenced(text, local, declared, depth)
                if fenced is None:
                    continue
                edits.append((start, end, fenced))
                add(edit(source, [(start, end, fenced)]))
            if len(edits) > 1:
                add(edit(source, edits))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 92,
          'lanes': ('beam', 'local')}  # the registry: no caller wiring (registry.py)
