"""A byte offset stepped beside a loop counter, written off the counter (GCC 2.7.2, KMC, N64).

m2c keeps the scaled index of a table walk as its own variable, stepped with the counter:

    s32 offset = 0;
    for (i = 0; i < n; i++, offset += 4)
    {
        p = *((char **) (((char *) table) + offset));

The explicit `offset` is initialised before the loop's guard, so its `move $rN,$zero` is emitted there and lives
while the loop's hoisted conversions (a parameter's zero-extend, set in the preheader) are still being made. When
the table is indexed by the counter instead, `*(char **)((char *) table + (i << 2))`, GCC's loop pass makes the
`i * 4` induction variable itself and initialises it after the hoisted invariants. The register of an incoming
stack byte (the fifth argument, loaded at entry) then no longer overlaps the offset's and goes where the target has
it. A 86-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) went 115 -> 20 with this edit alone
and to 0 with `one_shot_unwrap` on top; written `i * 4` it was 790 (cse folds the product into a stepped pointer), so
the shift form comes first. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import NUMBER, edit, view
from .line_scan import lines
from .pattern_repairs import close

FAMILY = 'counter_derived_offset'
FAMILIES = (FAMILY,)
_ID = r'[A-Za-z_]\w*'
_DECL = re.compile(rf'^[ \t]*(?:s32|u32|int|unsigned int|u16|s16)[ \t]+(?P<off>{_ID})[ \t]*=[ \t]*0[ \t]*;[ \t]*$')
_FOR = re.compile(
    rf'^(?P<indent>[ \t]*)for[ \t]*\([ \t]*(?P<i>{_ID})[ \t]*=[ \t]*0[ \t]*;(?P<cond>[^;{{}}]*);'
    rf'[ \t]*(?P<step>[^;{{}}]*)\)[ \t]*$')


def _step(text, counter, offset):
    """The constant the offset advances by when `text` is the loop's step clause (counter by 1, offset by a constant)."""
    parts = [p.strip() for p in text.split(',')]
    if len(parts) != 2:
        return None
    one = {f'{counter}++', f'++{counter}', f'{counter} += 1', f'{counter} = {counter} + 1'}
    found = [p for p in parts if p in one]
    other = [p for p in parts if p not in one]
    if len(found) != 1 or len(other) != 1:
        return None
    m = re.fullmatch(rf'{re.escape(offset)}\s*\+=\s*(?P<k>{NUMBER})', other[0])
    return int(m['k'].rstrip('uUlL'), 0) if m else None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = []
    for index in range(1, len(body)):
        loop = _FOR.fullmatch(body[index].stripped)
        decl = _DECL.fullmatch(body[index - 1].stripped)
        if not loop or not decl or index + 1 >= len(body) or body[index + 1].stripped != '{':
            continue
        counter, offset = loop['i'], decl['off']
        k = _step(loop['step'], counter, offset)
        if not k or counter == offset:
            continue
        stop = close(part.clean, body[index + 1].start + body[index + 1].text.index('{'), '{', '}')
        if stop is None:
            continue
        inner = part.clean[body[index + 1].end:stop - 1]
        rest = part.clean[part.opening:body[index - 1].start] + part.clean[stop:part.end]
        mention = rf'(?<![\w.>]){re.escape(offset)}\b'
        # the offset is the loop's alone: not read before or after it, and the counter is only stepped by the header
        if re.search(mention, rest) or re.search(mention+r'\s*(?:=(?!=)|[-+*/|&^]=|\+\+|--)', inner) \
                or re.search(rf'&\s*{re.escape(offset)}\b', inner):
            continue
        if re.search(rf'(?<![\w.>]){re.escape(counter)}\b\s*(?:=(?!=)|[-+*/|&^]=|\+\+|--)', inner) \
                or re.search(rf'(?:\+\+|--)\s*{re.escape(counter)}\b|&\s*{re.escape(counter)}\b', inner):
            continue
        if not re.search(mention, inner):
            continue
        spellings = []
        if k & (k - 1) == 0:
            spellings.append(f'({counter} << {k.bit_length() - 1})')
        spellings.append(f'({counter} * {k})')
        for spelling in spellings:
            edits = [(body[index - 1].start, body[index - 1].end, ''),
                     (body[index].start, body[index].end,
                      f'{loop["indent"]}for ({counter} = 0;{loop["cond"]}; {counter}++)\n')]
            for m in re.finditer(mention, inner):
                at = body[index + 1].end + m.start()
                edits.append((at, at + len(offset), spelling))
            out.append((FAMILY, edit(source, edits)))
    return out
