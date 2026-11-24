"""A cell mask held in a temporary that two `&` tests read, read twice from its table, with the loop's element pointer
staged as `p = base; p += offset;` ahead of the tests.

m2c writes the head of a triangle loop that tests a cell mask against two halves as

    idx = i & 0xFFFF; mask = cells(idx, mesh); tri = (*(s32 *) (mesh + 0x3C)) + (idx * 6);
    if ((lo & mask) && hi_test(hi, mask)) ...

A 2,267-instruction collision sweep (KMC gcc 2.7.2, `-O2 -mips3`) whose matched sibling queries spell the same loop
`q16 = mesh->tris; q16 += j * 3; if ((mesh->cellMasks[j] & lo) && (mesh->cellMasks[j] & hi))` had, at both of its
object loops, the target's `lw $a2, 0x3C($s5)` (the element base) ahead of the index and the mask loaded once into
`$a0` for both `and`s, where m2c's spelling loaded the mask first and copied it (`move $a3, $v1`): with the mask read
twice (cse merges the two loads) and the pointer staged, 1770 -> 1210 -> 980 (one function; each edit alone was worse:
1910 and 2565). Both edits are offered as one child: every such loop head at once, then each alone. Only for a temporary assigned once and read by exactly the two tests, with the pointer's sum on the line before or after.
"""
import re

from .csource import _blank, find

FAMILY = 'mask_reread_pointer_stage'
FAMILIES = (FAMILY,)

I = r'[A-Za-z_]\w*'
# One expression without `;`, braces or a top-level comma: good enough for m2c's one-line loop heads.
E = r'[^;{}]+?'


def _paren(text):
    text = text.strip()
    return text if re.fullmatch(I + r'(?:\s*\([^;{}]*\))?', text) else '(' + text + ')'


def _second(test, mask):
    """`hi` for the second test `(hi & mask)`, `(mask & hi)` or a helper call `f(hi, mask)` / `f(mask, hi)`, else None."""
    test = test.strip()
    for pat in (r'\(\s*(' + I + r')\s*&\s*' + mask + r'\s*\)', r'\(\s*' + mask + r'\s*&\s*(' + I + r')\s*\)',
                I + r'\s*\(\s*(' + I + r')\s*,\s*' + mask + r'\s*\)', I + r'\s*\(\s*' + mask + r'\s*,\s*(' + I + r')\s*\)'):
        m = re.fullmatch(pat, test)
        if m:
            return m.group(1)
    return None


HEAD = re.compile(
    r'(?P<m>' + I + r')\s*=\s*(?P<load>' + E + r');\s*'
    r'(?P<p>' + I + r')\s*=\s*\((?P<base>' + E + r')\)\s*\+\s*\((?P<off>' + E + r')\);\s*'
    r'if\s*\(\s*\(\s*(?P<a>' + I + r')\s*&\s*(?P=m)\s*\)\s*&&\s*(?P<second>' + E + r')\)\s*\{')
HEAD_AFTER = re.compile(
    r'(?P<p>' + I + r')\s*=\s*\((?P<base>' + E + r')\)\s*\+\s*\((?P<off>' + E + r')\);\s*'
    r'(?P<m>' + I + r')\s*=\s*(?P<load>' + E + r');\s*'
    r'if\s*\(\s*\(\s*(?P<a>' + I + r')\s*&\s*(?P=m)\s*\)\s*&&\s*(?P<second>' + E + r')\)\s*\{')


def _sites(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    out = []
    for pattern in (HEAD, HEAD_AFTER):
        for m in pattern.finditer(body):
            mask = m['m']
            hi = _second(m['second'], mask)
            if hi is None or mask in (m['p'], m['a'], hi):
                continue
            # The mask is assigned here and read only by the two tests (its declaration aside).
            reads = [r for r in re.finditer(r'\b' + mask + r'\b', body)]
            decl = [r for r in reads if re.match(r'[ \t]*\w[\w\s\*]*\s$', body[body.rfind('\n', 0, r.start()) + 1:r.start()])
                    and body[r.end():].lstrip().startswith(';')]
            if len(reads) - len(decl) != 3 or re.search(r'\b' + mask + r'\b', m['load']):
                continue
            if m['p'] in (m['load'] + m['base'] + m['off']):
                continue
            out.append((span[0] + m.start(), span[0] + m.end(), m, hi))
    return sorted(out, key=lambda s: s[0])


def _rewrite(m, hi):
    load = _paren(m['load'])
    stage = '%s = %s; %s += %s;' % (m['p'], m['base'].strip(), m['p'], m['off'].strip())
    return stage + ' if ((%s & %s) && (%s & %s)) {' % (load, m['a'], load, hi)


def variants(source, name):
    sites = _sites(source, name)
    if not sites:
        return []
    text = source
    for start, end, m, hi in reversed(sites):
        new = _rewrite(m, hi)
        text = text[:start] + new + text[end:]
    out = [(FAMILY, text)]
    if len(sites) > 1:
        for start, end, m, hi in sites:
            new = _rewrite(m, hi)
            out.append((FAMILY, source[:start] + new + source[end:]))
    return out[:6]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
