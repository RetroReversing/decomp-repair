"""A parameter reused as the address of a local array, given a local of its own.

m2c reuses a parameter's name for a value it computed later (`arg0 = sp18;`), so the parameter's register carries
a frame address for the rest of the function. The game's C kept the address in a local:

    do { arg0 = sp18; } while (0);                 pv = sp18;
    rotate(sp28, arg0);                  ->        rotate(sp28, pv);
    use(arg0, ...);                                use(pv, ...);

With the parameter, the address was set by an insn the first scheduler hoisted above the previous call and sched2
ordered after the argument move; the fresh local gave the target's `move $a0; addiu; move $a1` order (an N64 function,
`gcc-2.7.2-kmc`: 60 to exact, after eight spellings of the reused parameter had kept two insns swapped).

Offered when a parameter is assigned `P = X;` (alone or as the only statement of a `do { } while (0)`) where X is a
local array or an `&local`, P is read afterwards and not assigned again. Two variants: with the wrapper kept and with
it dropped.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'param_address_local'
FAMILIES = (FAMILY,)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    signature = clean[span[0]:opening]
    params = set(re.findall(r'(\w+)\s*(?=[,)])', signature[signature.rfind('('):]))
    arrays = set(re.findall(r'^[ \t]*[A-Za-z_][\w \t\*]*?\s(\w+)\s*\[[^\]]*\]\s*;', clean[opening:end], re.M))
    results = []
    for assign in re.finditer(r'(?<![\w.>])(\w+) = (&?\w+);', clean[opening:end]):
        param, value = assign[1], assign[2]
        if param not in params or value.lstrip('&') not in arrays:
            continue
        lo, hi = opening + assign.start(), opening + assign.end()
        later = clean[hi:end]
        if re.search(rf'(?<![\w.>]){param} (?:[-+*/%&|^]|<<|>>)?=(?!=)', later) or not re.search(rf'\b{param}\b', later):
            continue
        local = f'{param}_addr'
        if re.search(rf'\b{local}\b', clean):
            continue
        body = re.sub(rf'(?<![\w.>])\b{param}\b', local, source[hi:end])
        wrapper = re.search(r'do\s*\{\s*$', clean[:lo]) and re.match(r'\s*\}\s*while\s*\(0\)\s*;', clean[hi:])
        keep = source[:lo] + f'{local} = {value};' + body
        decl = f'\n  void *{local};'
        pieces = [keep]
        if wrapper:
            start = clean.rfind('do', 0, lo)
            tail = hi + re.match(r'\s*\}\s*while\s*\(0\)\s*;', clean[hi:]).end()
            body2 = re.sub(rf'(?<![\w.>])\b{param}\b', local, source[tail:end])
            pieces = [source[:start] + f'{local} = {value};' + body2 + source[end:], keep + source[end:]]
        else:
            pieces = [keep + source[end:]]
        for text in pieces:
            text = text[:opening + 1] + decl + text[opening + 1:]
            results.append((FAMILY, text))
    return results
