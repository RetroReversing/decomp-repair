"""A pointer local set to a global's address, declared far above the one nested block that uses it.

m2c and the agents' earlier edits declare `s32 *entries = (s32 *) (&sym);` at the top of the block that holds a loop
and use it once, inside a nested block at the loop's end: `p = (index << 2) + (char *) entries`. On KMC GCC 2.7.2 (N64)
cse orders the operands of the add by the quantity numbers of the two registers, and the address's pseudo, created
where the local is set, comes before the index's: the target adds the other way (`addu $v1,$v1,$s3` against
`addu $v1,$s3,$v1`) because the address register was created after the index. Declared in the block that uses it, the
address is set after the index is computed and loop.c still hoists the set out of the loop (the `lui`/`addiu` pair
stays before it), so only the operand order changes. A text-layout function went 345 -> 340 on this edit (the fourth
of five steps to 95). Hypothesis (not confirmed in the compiler's source): cse.c's canonical operand order of a
commutative add (`fold_rtx`'s swap by quantity), measured as the one-row difference.

Children, for a local pointer initialised from `&name` (any casts around it) that has exactly one use, inside a block
nested in the block that declares it: the declaration moved to that inner block, after the declarations the block
already starts with. Only MIPS. The candidate is never a verdict: the judge decides.
"""
import re

from .c_scan import close, enclosing_block
from .csource import _blank, find

FAMILY = 'address_local_scope_sink'
FAMILIES = (FAMILY,)
_ID = r'[A-Za-z_]\w*'
_DECLARATION = re.compile(
    rf'^([ \t]*)((?:{_ID}[ \t]+)+\*+[ \t]*)({_ID})[ \t]*=[ \t]*([^;\n]*?&[ \t]*{_ID}[\s)]*)[ \t]*;[ \t]*\n', re.M)
_ADDRESS_ONLY = re.compile(rf'^[\s()\w*]*&\s*{_ID}[\s)]*$')
_LEADING = re.compile(
    rf'[ \t]*(?:(?:const|volatile|unsigned|signed|struct|union)[ \t]+)*(?!(?:return|goto|else|case|break|continue)\b){_ID}'
    rf'[ \t]+\**[ \t]*{_ID}(?:\[[^\]\n]*\])?[ \t]*(?:=[^;\n]*)?;[ \t]*\n')


def _leading_end(source, clean, opening, end):
    """Offset just past the declarations that start the block opened at `opening`."""
    at = opening + 1
    nl = source.find('\n', at, end)
    if nl < 0:
        return None
    at = nl + 1
    while True:
        hit = _LEADING.match(clean, at, end)
        if not hit:
            return at
        at = hit.end()


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    out = []
    for hit in _DECLARATION.finditer(source, opening, span[1]):
        local, init = hit[3], hit[4]
        if not _ADDRESS_ONLY.match(init):
            continue
        uses = [m.start() for m in re.finditer(rf'(?<![\w.>]){local}\b', clean[opening:span[1]])]
        uses = [opening + u for u in uses if not hit.start() <= opening + u < hit.end()]
        if len(uses) != 1:
            continue
        home = enclosing_block(clean, hit.start(), opening)
        inner = enclosing_block(clean, uses[0], opening)
        if inner < 0 or home < 0 or inner == home or not home < inner < close(clean, home):
            continue
        inner_end = close(clean, inner)
        if inner_end < 0 or not hit.end() <= inner:
            continue
        at = _leading_end(source, clean, inner, inner_end)
        if at is None:
            continue
        at = min(at, source.rfind('\n', 0, uses[0]) + 1)
        if at <= inner:
            continue
        indent = re.match(r'[ \t]*', source[at:])[0] or hit[1] + '  '
        moved = f'{indent}{hit[2]}{local} = {init.strip()};\n'
        out.append((FAMILY, source[:hit.start()] + source[hit.end():at] + moved + source[at:]))
    return [x for x in out if x[1] != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
