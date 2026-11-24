"""A load m2c held in a temporary that only the next call statement reads, written inline in the call's operands.

`v = rec->verts; if (hit(&a, &b, v + t[0] * 12, v + t[1] * 12, v + t[2] * 12, &d) & 0xFF)` loads `rec->verts` before
any argument is computed: the pseudo is set first and local-alloc gives it the first free register (`$t0`). With the
load written in each operand (`rec->verts + t[0] * 12`, ...) cse makes one load, but it is emitted where the first
operand needs it, after the index loads, and takes the register the target has (`lhu $a3, ($s0); lw $v1, 0x34($s2)`).
A 1928-instruction collision sweep (KMC gcc 2.7.2), twenty such temporaries: the four ray tests 8155 -> 7125, all of
them 6656. One function; the judge decides.

A candidate: `t = E;` with E free of calls, assignments and increments, `t` read only in the statement on the next line
(a call, an assignment from a call, or an `if` whose condition calls), and nowhere else. Children: all at once, then
each alone.
"""
import re

from .csource import _blank, find

FAMILY = 'call_operand_load_inline'
COMBINED = 'call_operand_load_inline_all'
FAMILIES = (FAMILY, COMBINED)

I = r'[A-Za-z_]\w*'


def _sites(lines, clean_body):
    out = []
    for i in range(len(lines) - 1):
        m = re.match(r'([ \t]*)(' + I + r') = ([^;]+);\s*$', lines[i])
        if not m:
            continue
        t, expr = m[2], m[3]
        if re.search(I + r'\s*\(', re.sub(r'\(\s*\w+\s*\*\s*\)', '', expr)) or re.search(r'(?<![=!<>])=(?!=)|\+\+|--', expr):
            continue
        if re.search(r'(?<![\w.>])' + t + r'\b', expr):
            continue
        nxt = lines[i + 1]
        if not re.match(r'\s*(?:if \(|' + I + r'\s*=\s*)?\(?' + I + r'\s*\(', nxt):
            continue
        uses = len(re.findall(r'(?<![\w.>])' + t + r'\b', nxt))
        total = len(re.findall(r'(?<![\w.>])' + t + r'\b', clean_body))
        decl = len(re.findall(r'(?m)^[ \t]*(?:register\s+)?[\w ]+?\b' + t + r'\s*;', clean_body))
        if uses and total == uses + 1 + decl:
            out.append((i, t, expr))
    return out


def _apply(lines, sites):
    lines = list(lines)
    for i, t, expr in sorted(sites, reverse=True):
        spelled = '(' + expr + ')'
        lines[i + 1] = re.sub(r'\(\s*(?:int|s32|u32|long)\s*\)\s*' + t + r'\b', spelled, lines[i + 1])
        lines[i + 1] = re.sub(r'(?<![\w.>])' + t + r'\b', lambda _, s=spelled: s, lines[i + 1])
        del lines[i]
    text = '\n'.join(lines)
    for _, t, _ in sites:
        text = re.sub(r'(?m)^[ \t]*(?:register\s+)?[\w ]+?\b' + t + r'\s*;\n', '', text, count=1)
    return text


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    body = source[opening:span[1]]
    lines = body.split('\n')
    sites = _sites(lines, clean[opening:span[1]])
    if not sites:
        return []
    wrap = lambda text: source[:opening] + text + source[span[1]:]  # noqa: E731
    out = []
    if len(sites) > 1:
        out.append((COMBINED, wrap(_apply(lines, sites))))
    out += [(FAMILY, wrap(_apply(lines, [s]))) for s in sites[:8]]
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
