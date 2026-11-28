"""A global counter or flag reached through a pointer or `*&` spelling: read by name and declared `volatile`.

A game's delay or poll loop on a `volatile` global loads it again for every test and every step
(`sw $zero, %lo(G)($v1); j test; lw; addiu; sw; test: lw; slt; bnez`). A draft that has lost the qualifier is often
respelled by earlier repairs until the accesses go through a pointer (`s32 *p; p = &G; (*p) += 1;`) or `*(&G)`, and then
`scalar_reload_volatile` leaves it alone, because the address is taken. Folding the spellings back to `G` alone leaves
gcc keeping the value in a register, and `volatile` alone leaves the pointer's accesses plain: both are needed at once.
Measured on a 13-instruction N64 busy-wait loop (SN gcc 2.8.1, `-G0 -mips3 -O2`): 715 on the saved source, 510 with
the spellings folded, 0 with the folded spellings and `extern volatile s32 G;`.

The family `aliased_global_volatile` offers one child for each extern scalar global reached that way (never an array or
pointer, or one whose address is used for anything else): the local pointer and `*&` spellings become the name and the
declaration gains `volatile`. `volatile` only keeps accesses in place, so the meaning stays."""
import re

from .csource import _blank, find
from .integer_repair_support import edit
from .pattern_repairs import close

FAMILY = 'aliased_global_volatile'
FAMILIES = (FAMILY,)
LIMIT = 4
SCALAR = r'(?:(?:unsigned|signed)\s+)?(?:u8|s8|u16|s16|u32|s32|int|short|char|long)(?:\s+(?:int|long|short|char))?'
EXTERN = re.compile(rf'(?m)^[ \t]*extern\s+(?P<type>{SCALAR})\s+(?P<g>[A-Za-z_]\w*)\s*;')
# what may not follow a dereference: it would apply to the pointer before the `*` does
BINDS_TIGHTER = r'(?!\s*(?:\[|\(|\.|->|\+\+|--))'


def _aliases(clean, opening, end, kind, glob):
    """(name, declaration span, assignment span, dereference spans) of each local that only ever stands for `&glob`."""
    words = r'\s+'.join(map(re.escape, kind.split()))
    for decl in re.finditer(rf'(?m)^[ \t]*{words}\s*\*\s*(?P<p>[A-Za-z_]\w*)\s*;[ \t]*\n?', clean[:end]):
        if decl.start() < opening:
            continue
        pointer = decl['p']
        sets = list(re.finditer(rf'(?m)^[ \t]*{pointer}\s*=\s*&\s*{glob}\s*;[ \t]*\n?', clean[:end]))
        if len(sets) != 1:
            continue
        derefs = list(re.finditer(rf'\*\s*\b{pointer}\b{BINDS_TIGHTER}', clean[opening:end]))
        derefs = [(opening + m.start(), opening + m.end()) for m in derefs]
        # the declaration's own `*p` is not a use
        derefs = [(a, b) for a, b in derefs if not decl.start() <= a < decl.end()]
        uses = len(re.findall(rf'(?<![\w.>])\b{pointer}\b', clean[opening:end]))
        if derefs and uses == len(derefs) + 2:
            yield pointer, decl.span(), sets[0].span(), derefs


def _named(clean, spans, glob):
    """Edits that write `glob` at each span, taking the parentheses of a parenthesised statement-leading target along."""
    edits = []
    for start, finish in spans:
        wrapped_left = re.search(r'(?<=[;{}])\s*(\()\s*$', clean[:start])
        wrapped_right = re.match(r'\s*\)', clean[finish:])
        if wrapped_left and wrapped_right:
            start, finish = wrapped_left.start(1), finish + wrapped_right.end()
        edits.append((start, finish, glob))
    return edits


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or re.search(r'(?m)^[ \t]*#|\b(?:asm|__asm__)\b', clean[opening:end]):
        return []
    result = []
    for decl in EXTERN.finditer(clean, 0, span[0]):
        glob = decl['g']
        if re.search(rf'(?m)^[ \t]*#\s*define[^\n]*\b{glob}\b', clean):
            continue
        spans, edits, taken = [], [], []
        for _, declared, assigned, derefs in _aliases(clean, opening, end, decl['type'], glob):
            edits += [(declared[0], declared[1], ''), (assigned[0], assigned[1], '')]
            spans += derefs
            taken.append(assigned)
        for m in re.finditer(rf'\*\s*(?:\(\s*&\s*{glob}\s*\)|&\s*{glob}\b){BINDS_TIGHTER}', clean[opening:end]):
            spans.append((opening + m.start(), opening + m.end()))
        if not spans:
            continue
        # every other `&glob` lets the address out, and a local of the same name is another object
        covered = spans + taken
        escaped = any(not any(a <= opening + m.start() < b for a, b in covered)
                      for m in re.finditer(rf'(?<!&)&\s*{glob}\b', clean[opening:end]))
        shadowed = re.search(rf'(?m)^[ \t]*{SCALAR}\s*\**\s*{glob}\b', clean[opening:end])
        accesses = len(spans) + len(re.findall(rf'(?<![\w.>&])\b{glob}\b(?!\s*\[)', clean[opening:end]))
        if escaped or shadowed or accesses < 2:
            continue
        edits += _named(clean, spans, glob)
        edits.append((decl.start('type'), decl.start('type'), 'volatile '))
        result.append((FAMILY, edit(source, edits)))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
