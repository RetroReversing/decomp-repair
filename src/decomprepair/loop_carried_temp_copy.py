"""A loop's next value read into a temporary that is only copied into the loop variable on the arm that continues.

m2c writes the end of a `for (;;)` that carries a character as

    t = *p;  ...;  if (t == 0) { } else { v = t; continue; }

On KMC GCC 2.7.2 (N64) the temporary's register is allocated first and the loop variable's copy of it is a
move in the branch's delay slot: the variable takes the temporary's register by preference (`$v0`), so the register
the target gives the variable (`$v1`) goes to another value and four rows cascade. Written `v = *p; ...; if (v != 0)
{ continue; }` the variable is the loaded value itself, conflicts with the temporary-free range and takes the
target's register. A text-layout function went 365 -> 345 on this edit (the third of five steps to 95). Hypothesis (not
confirmed in the compiler's source): global.c's copy preference between the temporary and the variable.

Children, for `t = E; S...; if (t == 0) { } else { v = t; continue; }` (or `if (t != 0) { v = t; continue; }`) where
`t` has no other use, the statements `S` (simple, between the read and the test) mention neither `t` nor `v`, and `v`
is not read after the loop the `continue` belongs to (its value on the arm that leaves the loop changes from the old
character to zero). An identity inline helper around `E` is also offered unwrapped. Only MIPS. The candidate is never a
verdict: the judge decides.
"""
import re

from .c_scan import close, enclosing_block, header_before
from .csource import _blank, find

FAMILY = 'loop_carried_temp_copy'
FAMILIES = (FAMILY,)
_ID = r'[A-Za-z_]\w*'
_PATTERN = re.compile(
    rf'(?P<def>(?<![\w.>])(?P<t>{_ID})\s*=\s*(?P<e>[^;{{}}=]+?)\s*;)(?P<mid>(?:[^;{{}}]*;)*?)(?P<ws>\s*)'
    rf'if\s*\(\s*(?:(?P=t)\s*==\s*0\s*\)\s*\{{\s*\}}\s*else\s*\{{\s*(?P<v>{_ID})\s*=\s*(?P=t)\s*;\s*continue\s*;\s*\}}'
    rf'|(?P=t)\s*(?:!=\s*0\s*)?\)\s*\{{\s*(?P<w>{_ID})\s*=\s*(?P=t)\s*;\s*continue\s*;\s*\}})')


def _mentions(text, name):
    return re.search(rf'(?<![\w.>]){re.escape(name)}\b', text) is not None


def _pure(expr, helpers):
    """True for an expression with no `++`/`--` and no call but an identity helper's."""
    if re.search(r'\+\+|--', expr):
        return False
    return all(call in helpers for call in re.findall(rf'({_ID})\s*\(', expr))


def _uses(text, name):
    return len(re.findall(rf'(?<![\w.>]){re.escape(name)}\b', text))


def _declarations(text, name):
    return len(re.findall(rf'\b[A-Za-z_]\w*[ \t*]+{re.escape(name)}\s*;', text))


def _loop_end(clean, at, lo):
    """Index just past the closing brace of the innermost loop around `at`, or -1."""
    block = enclosing_block(clean, at, lo)
    while block >= 0:
        if re.search(r'(?:\b(?:for|while)\s*\(.*\)|\bdo)$', header_before(clean, block), re.S):
            return close(clean, block) + 1
        block = enclosing_block(clean, block, lo)
    return -1


def _identity_helpers(source):
    return set(re.findall(rf'\binline\s+static\s+\w+\s+({_ID})\s*\(\s*\w+\s+(\w+)\s*\)\s*\{{\s*return\s+\2\s*;\s*\}}', source))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    out = []
    helpers = {helper for helper, _ in _identity_helpers(source)}
    for hit in _PATTERN.finditer(clean, opening, span[1]):
        t, e, v = hit['t'], hit['e'].strip(), hit['v'] or hit['w']
        mid = hit['mid']
        if t == v or _mentions(mid, t) or _mentions(mid, v) or _mentions(e, t) or not _pure(e, helpers):
            continue
        if _uses(clean[opening:span[1]], t) != _uses(clean[hit.start():hit.end()], t) + _declarations(clean[opening:span[1]], t):
            continue
        end = _loop_end(clean, hit.start(), opening)
        if end < 0 or _mentions(clean[end:span[1]], v):
            continue
        indent = re.search(r'([ \t]*)$', source[:hit.start()])[1]
        reads = [e]
        for helper in helpers:
            unwrapped = re.fullmatch(rf'{helper}\s*\((.*)\)', e)
            if unwrapped and _pure(unwrapped[1], helpers):
                reads.append(unwrapped[1].strip())
        for read in reads:
            mid_text = source[hit.start('mid'):hit.end('mid')]
            text = f'{v} = {read};{mid_text}{hit["ws"]}if ({v} != 0)\n{indent}{{\n{indent}  continue;\n{indent}}}'
            out.append((FAMILY, source[:hit.start()] + text + source[hit.end():]))
    return [x for x in out if x[1] != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
