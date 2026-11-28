"""`v = obj->kind; switch (v)` written as `switch (obj->kind)`, with the arms' reads of `v` as their case values.

m2c keeps the value a `switch` dispatches on in a local, and where an arm compares with it (the compiler reused the
selector's register for the arm's literal) it reads the local back:

    sel = obj->kind;
    switch (sel) { case 1: if (obj->owner == sel) { .. } .. }

The game switched on the field and wrote the literal. The local is another value to GCC: the load right after an earlier
test of the same field is merged with the test's load, so the target's two loads (one for the test, one that lives in a
saved register for the dispatch) become one.

switch_selector_inline
    `v` is a local assigned once, from a read of its own width with no call or side effect, in the statement just
    before `switch (v)`,
    and read nowhere but there and in arms of one case value that nothing falls into. The assignment goes, the switch
    takes the expression and the arms' reads become the case value.

Measured on a 293-instruction N64 object update (SN gcc 2.8.1, `-G0 -mips3 -O2 -mgas -mfp64`): 110 -> 0, after the
tree had become a `switch` (`path_copy_hoist_switch`).

A candidate rewrite; the exact judge decides.
"""
import re

from .case_temporary_repairs import DECLARATION, _groups, _mentions, _switches
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'switch_selector_inline'
FAMILIES = (FAMILY,)
LIMIT = 8

_NUMBER = re.compile(r'(?:case\s+)?(-?(?:0[xX][0-9A-Fa-f]+|\d+))[uUlL]*$')
_LEAVES = re.compile(r'(?:^|[;{}])\s*(?:break|continue|return(?:\s+[^;{}]+)?|goto\s+\w+)\s*;\s*\}?\s*$')
# a call (a name or `)` before `(` that is not a cast), an assignment or a step: the value could differ when read later
_EFFECT = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|(?<![\w])[A-Za-z_]\w*\s*\(|\]\s*\(')


def _calls(clean_expression):
    text = re.sub(r'\bM2C_FIELD\s*\(', '(', clean_expression)
    return bool(_EFFECT.search(text))


def _same_width(clean, kind, value):
    """Whether the local of type `kind` holds `value` as it is: a word local, a value that names that type, or a
    member declared with it. A narrower local would otherwise change which arm a wider value reaches."""
    if kind in ('s32', 'u32', 'int', 'unsigned int') or re.search(rf'\b{re.escape(kind)}\b', value):
        return True
    member = re.search(r'(?:->|\.)\s*([A-Za-z_]\w*)$', value)
    return bool(member and re.search(rf'\b{re.escape(kind)}\s+{member[1]}\s*;', clean))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    switches = _switches(clean, opening, end)
    declared = {m['name']: m['type'].strip() for m in DECLARATION.finditer(clean, opening + 1, end)}
    result = []
    for hit in re.finditer(r'(?<![\w.>])(?P<var>[A-Za-z_]\w*)\s*=(?!=)\s*(?P<value>[^;{}]+);\s*'
                           r'switch\s*\(\s*(?P=var)\s*\)\s*(?=\{)', clean[:end]):
        var = hit['var']
        if hit.start() < opening or var not in declared or _calls(hit['value']):
            continue
        if not _same_width(clean, declared[var], hit['value'].strip()):
            continue
        before = clean[opening:hit.start()].rstrip()
        if before[-1:] not in ';{}':
            continue  # the assignment is a braceless arm of something
        if re.search(rf'&\s*{var}\b|\b{var}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)=)|(?:\+\+|--)\s*{var}\b', clean[opening:end]):
            continue
        writes = re.findall(rf'(?<![\w.>])\b{var}\s*=(?!=)', clean[opening:end])
        if len(writes) != 1 or _mentions(var).search(hit['value']):
            continue
        body = next((b for b in switches if b[0] == hit.end()), None)
        if not body:
            continue
        nested = [s for s in switches if body[0] < s[0] and s[1] < body[1]]
        groups = _groups(clean, body, nested)
        if not groups:
            continue
        reads, bad = [], False
        for index, (label, a, b) in enumerate(groups):
            found = list(_mentions(var).finditer(clean, a, b))
            if not found:
                continue
            number = _NUMBER.match(label)
            previous = clean[groups[index - 1][1]:groups[index - 1][2]] if index else ''
            # one value reaches this arm: its own label, and the arm above leaves (an empty one is a second label)
            if not number or (index and not _LEAVES.search(re.sub(r'\bcase\b[^:]*:\s*$', '', previous).rstrip())):
                bad = True
                break
            reads += [(m.start(), m.end(), number[1]) for m in found]
        # every mention is the declaration, the assignment, the selector or one of those reads
        if bad or len(_mentions(var).findall(clean[opening:end])) != len(reads) + 3:
            continue
        value = source[hit.start('value'):hit.end('value')].strip()
        gap = source[clean.rfind(';', hit.start(), hit.end()) + 1:hit.end()]
        edits = reads + [(hit.start(), hit.end(), f'switch ({value})' + gap[gap.rfind(')') + 1:])]
        child = source
        for start, stop, new in sorted(edits, reverse=True):
            child = child[:start] + new + child[stop:]
        result.append((FAMILY, child))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
