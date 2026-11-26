"""A stored sum that the parameter keeps, and a `void` function that hands back that sum plus a constant.

    void f(s32 arg0) { ...; D_800B2D64 = arg0 + 0x300; g(D_800B2D64, p, 0x80); }
    s32  f(s32 arg0) { ...; arg0 += 0x300; D_800B2D64 = arg0; g(arg0, p, 0x80); return 0x80 + arg0; }

Two steps that a N64 loader (KMC GCC 2.7.2, 25 instructions) needed together; each one alone scored worse (100 -> 205
for the widened return, 100 -> 100 for the accumulation), and the pair reached 70, then 0 with the argument-weight
scope that `argument_weight_scope` already offers:
- `stored_sum_param_accumulate`: a statement `G = P + K;` (P a parameter, K a literal) becomes `P += K; G = P;` and the
  later reads of `G` read `P`. The game advanced the parameter and stored it, so the stored copy and the register that
  feeds the next call are one value, not two; written as a sum stored to a global and read back, the reload (or a second
  register) is what differs. Offered for any function. Nothing is offered when `G` or `P` is written later.
- `void_sum_return`: the same, in a `void` function whose target ends with `addiu $v0, $reg, K` before its `jr $ra` and no
  call after it: m2c cannot see a value that no caller reads, so the draft is `void`. The return type becomes `s32` and
  the function ends with `return K + P;` (children: with the accumulation, and `return K + G;` without it, since the
  target's bytes cannot tell the variable apart). A prototype earlier in the source changes with it; one in the project's
  header is not a source rewrite and stops the repair (`return_type_widen` takes the same stance). Hypothesis, not
  confirmed in the compiler source: the parameter's register is the one value live across the last call, so the
  epilogue's `addiu $v0` reads it. The exact judge decides."""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY_ACCUMULATE = 'stored_sum_param_accumulate'
FAMILY_RETURN = 'void_sum_return'
FAMILIES = (FAMILY_ACCUMULATE, FAMILY_RETURN)
_SUM = re.compile(rf'(?m)^(?P<lead>[ \t]*)(?P<g>{IDENT})\s*=\s*(?P<p>{IDENT})\s*\+\s*(?P<k>{NUMBER})\s*;[ \t]*$')
_TAIL = re.compile(r'(?:\bjr\s+\$ra\b)')
_ADDI = re.compile(r'\baddiu\s+\$v0\s*,\s*\$(?!zero)\w+\s*,\s*(-?(?:0x[0-9a-fA-F]+|\d+))\b')


def _params(clean, part_start, opening):
    """The parameter names of the definition between `part_start` and its opening brace."""
    head = clean[part_start:opening]
    inside = head[head.index('(') + 1:head.rindex(')')] if '(' in head and ')' in head else ''
    names = [(re.findall(IDENT, item) or [''])[-1] for item in inside.split(',')]
    return {n for n in names if n and n != 'void'}


def _return_constant(asm):
    """K of the `addiu $v0, $reg, K` the target ends with (no call after it), else None."""
    lines = [line.split('#')[0].strip() for line in (asm or '').splitlines() if line.split('#')[0].strip()]
    ends = [i for i, line in enumerate(lines) if _TAIL.search(line)]
    if len(ends) != 1:
        return None
    window = lines[max(0, ends[0] - 8):ends[0] + 2]
    last = None
    for line in window:
        if re.search(r'\bjal\b|\bjalr\b', line):
            last = None
        hit = _ADDI.search(line)
        if hit:
            last = hit[1]
    return None if last is None or int(last, 0) == 0 else last


def _accumulate(source, part, hit, params):
    """Edits that make `G = P + K;` advance the parameter, or None when a later write forbids it."""
    g, p = hit['g'], hit['p']
    if p not in params or g == p:
        return None
    rest = part.clean[hit.end():part.end]
    if re.search(rf'(?<![\w.>])(?:{re.escape(g)}|{re.escape(p)})\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|\b{re.escape(p)}\s*(?:\+\+|--)', rest):
        return None
    reads = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(g)}\b(?!\s*\()', rest)]
    if not reads:
        return None
    edits = [(hit.start(), hit.end(), f"{hit['lead']}{p} += {hit['k']};\n{hit['lead']}{g} = {p};")]
    edits += [(hit.end() + m.start(), hit.end() + m.end(), p) for m in reads]
    return edits, p


def variants(source, name, asm='', header=''):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    if re.search(r'\b(?:volatile|asm|__asm__)\b|^\s*#', body, re.M):
        return []
    definition = re.search(rf'\b{re.escape(name)}\s*\(', part.clean)
    params = _params(part.clean, definition.start(), part.opening) if definition else set()
    out = []
    sums = [hit for hit in _SUM.finditer(part.clean, part.opening, part.end)]
    plain = [(hit, _accumulate(source, part, hit, params)) for hit in sums]
    for hit, built in plain:
        if built:
            out.append((FAMILY_ACCUMULATE, edit(source, built[0])))
    k = _return_constant(asm)
    is_void = re.search(rf'\bvoid\s+{re.escape(name)}\s*\(', part.clean)
    if (k is None or not is_void or re.search(rf'\bvoid\s+\**{re.escape(name)}\s*\(', re.sub(r'/\*.*?\*/', '', header or '', flags=re.S))
            or re.search(r'\breturn\b', body)):
        return list(dict.fromkeys(out))
    close_at = source.rindex('}', 0, part.end)
    ending = source[:close_at].rstrip()
    indent = (re.search(r'\n([ \t]+)\S[^\n]*\Z', ending) or [None, '    '])[1]
    widen = [(m.start(), m.start() + 4, 's32') for m in re.finditer(rf'\bvoid(?=\s+{re.escape(name)}\s*\()', source)]
    for hit, built in plain:
        if not built:
            continue
        p = built[1]
        out.append((FAMILY_RETURN, edit(source, built[0] + widen + [(len(ending), len(ending), f'\n{indent}return {k} + {p};')])))
        g = hit['g']
        out.append((FAMILY_RETURN, edit(source, widen + [(len(ending), len(ending), f'\n{indent}return {k} + {g};')])))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
