"""A command word split into a tested byte and an index, the index passed to a call in one arm and scaled into two
stores in the other (m2c's form):

    x = ((u32) W) >> 0x10;  ...  if ((((u32) W) >> 8) & 0xFF) { f(v, x & 0xFF, d); } else { x = x & 0x1F; o = x * 2;
    if (x < 0x10U) { *((u16 *) (((char *) (o + v)) + 0x180)) = d; ... } *((s16 *) (((char *) (&G)) + o)) = d; }

written as the game had it: the tested byte read first into a `u8` local of its own (`u8 flag = ((u32) W) >> 8;` at
the head of the block, `if (flag)`), the call's index through a `u8` copy made just before the `if`, and the stores
indexed by the index (`((u16 *) ((char *) v + 0x180))[x] = d;`, `((s16 *) &G)[x] = d;`) with the scaled offset gone.

KMC GCC 2.7.2 (`-O2`, N64), a 1315-instruction sound-sequence interpreter's indirect-variable write (2070 -> 1910,
only the three together; each alone or in pairs 2000..2170): with the byte read first, the index's shift ends the
word's life and ties to its register (`srl $v0, $v1, 8; srl $v1, $v1, 16`); the copy is the target's delay-slot
`move $a1, $v1`; and an offset computed before the inner `if` is a pseudo of both arms that takes `$a0` from the stored
value, where an index scaled in each arm is reorg's one `sll` in the branch's delay slot. The readings are from the
output; the judge decides. Children: the three together first, then each alone.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'byte_test_index_split'
FAMILIES = (FAMILY,)
LIMIT = 8


def _flag(text, cond):
    """(a) The tested byte read into a `u8` local at the head of the block holding the `if`."""
    head = text.rfind('{', 0, cond.start())
    if head < 0:
        return None
    decls = re.match(r'\{[ \t]*\n(?:[ \t]*(?:u8|s8|u16|s16|u32|s32|int)[ \t]+\w+[ \t]*;[ \t]*\n)*', text[head:])
    at = head + decls.end()
    ind = re.match(r'[ \t]*', text[at:]).group(0)
    line = f'{ind}u8 flag = {cond["w"]};\n'
    return text[:at] + line + text[at:cond.start('c')] + 'flag' + text[cond.end('c'):]


def _copy(text, cond, x):
    """(b) The then-arm's `f(.., x & 0xFF, ..)` read through a `u8` copy made just before the `if`."""
    then = re.search(rf'\b{re.escape(x)}\s*&\s*0[xX][fF][fF]\b', text[cond.end():])
    if not then:
        return None
    at = text.rfind('\n', 0, cond.start()) + 1
    ind = re.match(r'[ \t]*', text[at:]).group(0)
    head = text.rfind('{', 0, cond.start())
    decls = re.match(r'\{[ \t]*\n', text[head:])
    if head < 0 or not decls:
        return None
    use = cond.end() + then.start()
    out = text[:use] + 'idx & 0xFF' + text[cond.end() + then.end():]
    out = out[:at] + f'{ind}idx = {x};\n' + out[at:]
    d = head + decls.end()
    return out[:d] + f'{ind}u8 idx;\n' + out[d:]


def _index(text, x):
    """(c) `o = x * 2;` and its two byte-offset stores written as stores indexed by `x`."""
    scale = re.search(rf'(?m)^[ \t]*(?P<o>{IDENT})\s*=\s*{re.escape(x)}\s*\*\s*2\s*;[ \t]*\n', text)
    if not scale:
        return None
    o = scale['o']
    rest = text[scale.end():]
    first = re.search(rf'\*\(\((?P<t>\w+) \*\) \(\(\(char \*\) \({re.escape(o)} \+ (?P<b>{IDENT})\)\) \+ (?P<k>0[xX][0-9a-fA-F]+|\d+)\)\)', rest)
    second = re.search(rf'\*\(\((?P<t>\w+) \*\) \(\(\(char \*\) \(&(?P<g>{IDENT})\)\) \+ {re.escape(o)}\)\)', rest)
    if not (first and second):
        return None
    out = rest[:first.start()] + f'(({first["t"]} *) ((char *) {first["b"]} + {first["k"]}))[{x}]' + rest[first.end():]
    second = re.search(rf'\*\(\((?P<t>\w+) \*\) \(\(\(char \*\) \(&(?P<g>{IDENT})\)\) \+ {re.escape(o)}\)\)', out)
    out = out[:second.start()] + f'(({second["t"]} *) &{second["g"]})[{x}]' + out[second.end():]
    if re.search(rf'\b{re.escape(o)}\b', out[:out.find("break;", second.start()) if "break;" in out[second.start():] else len(out)]):
        return None
    return text[:scale.start()] + out


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    lo, hi = part.opening + 1, part.end - 1
    out = []
    cond_re = re.compile(rf'if \((?P<c>\((?P<w>\(\(u32\) (?P<g>{IDENT})\) >> (?:8|0x8|0x10|16|0x18|24))\) & 0[xX][fF][fF])\)')
    for cond in cond_re.finditer(source, lo, hi):
        before = source[max(lo, cond.start() - 400):cond.start()]
        idx = re.search(rf'(?m)^[ \t]*(?P<x>{IDENT})\s*=\s*\(\(u32\) {re.escape(cond["g"])}\) >> (?:0x10|16)\s*;', before)
        if not idx:
            continue
        x = idx['x']
        region_end = source.find('break;', cond.end())
        region_end = hi if region_end < 0 else region_end + 600
        region = source[:region_end]
        tail = source[region_end:]
        a = _flag(region, cond)
        b = _copy(region, cond, x)
        c = _index(region, x)
        steps = []
        if a and b and c:
            whole = c
            m = cond_re.search(whole, lo)
            whole = _copy(whole, m, x) if m else None
            m = cond_re.search(whole, lo) if whole else None
            whole = _flag(whole, m) if m else None
            if whole:
                steps.append(whole)
        steps += [s for s in (a, b, c) if s]
        for text in steps:
            out.append((FAMILY, text + tail))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
