"""A function m2c made `void` that returns the value it last stores to a global.

`x = ...; G = x; return x;` compiles with the result in `$v0`, the return register, and the store `sw $v0, %lo(G)`
last. m2c sees no use of `$v0` after the return and writes `void f(void) { ... G = ...; }`; gcc then computes in
other registers. The SDK's random-number routine in an N64 game was 95.9% so, and exact as `u32 f(void)` with
`return G;` after the store. Offered only when the target's last store to that global is from `$v0` and no other
instruction after it writes `$v0`.

The other way round, a counter's old value returned (`return p->count--;`): the target loads `$v0` from the address
it finally stores the stepped value to, from another register. An N64 function ending in m2c's
`M2C_FIELD(arg0, s32 *, 0) = (s32) (M2C_FIELD(arg0, s32 *, 0) - 1);` was 99.7% and exact as
`s32 f(...) { ...; return M2C_FIELD(arg0, s32 *, 0)--; }`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'stored_return_value'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    head = re.match(r'\s*(?:static\s+)?void\s+' + re.escape(name) + r'\s*\(', clean[span[0]:])
    if not head:
        return []
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    if re.search(r'\breturn\b', clean[opening:end]):
        return []
    if old := _old_value(source, clean, span, head, opening, end, asm):
        return [old]
    last = re.search(r'(?m)^(?P<indent>[ \t]*)(?P<g>' + IDENT + r')\s*=(?!=)[^;]*;[ \t]*\n\s*\}\s*$', clean[opening:end])
    if not last:
        return []
    symbol = last['g']
    stores = list(re.finditer(r'\bs[wbh]\s+\$(\w+)\s*,\s*%lo\(\s*' + re.escape(symbol) + r'\s*\)', asm))
    if not stores or stores[-1][1] != 'v0' or re.search(r'\b\w+\s+\$v0\s*,', asm[stores[-1].end():]):
        return []
    declared = re.search(r'(?m)^\s*extern\s+([\w ]+?)\s+' + re.escape(symbol) + r'\s*;', clean)
    kind = declared[1].strip() if declared and '*' not in declared[0] else 's32'
    at = opening + last.end() - len(last.group(0)) + last.group(0).index(';') + 1
    text = source[:at] + f'\n{last["indent"]}return {symbol};' + source[at:]
    void_at = span[0] + head.start() + head.group(0).index('void')
    text = text[:void_at] + kind + text[void_at + len('void'):]
    return [(FAMILY, text)]


def _old_value(source, clean, span, head, opening, end, asm):
    """`LV = (T) (LV - 1);` last, where the target returns the value before the step: `return LV--;`."""
    step = re.search(r'(?m)^(?P<indent>[ \t]*)(?P<lv>[^;=\n]+?)\s*=(?!=)\s*(?:\(\s*(?P<t>[\w ]+?)\s*\)\s*)?'
                     r'\(\s*(?P<again>[^;\n]+?)\s*(?P<op>[-+])\s*1\s*\)\s*;[ \t]*\n\s*\}\s*$', clean[opening:end])
    if not step or ' '.join(step['lv'].split()) != ' '.join(step['again'].split()):
        return None
    lines = [line for line in asm.splitlines() if re.search(r'\b(?:s[wbh]|l[wbh]u?)\s', line)]
    store = next((re.search(r'\bs[wbh]\s+\$(\w+)\s*,\s*(\S+)', line) for line in reversed(lines)
                  if re.search(r'\bs[wbh]\s', line)), None)
    if not store or store[1] == 'v0':
        return None
    load = re.search(r'\bl[wbh]u?\s+\$v0\s*,\s*' + re.escape(store[2]) + r'\s*$', asm, re.M)
    if not load or re.search(r'\b\w+\s+\$v0\s*,', asm[load.end():]):
        return None
    kind = step['t'] or 's32'
    lv = source[opening + step.start('lv'):opening + step.end('lv')].strip()
    at = opening + step.start('lv')
    stop = source.index(';', opening + step.end('again')) + 1
    text = source[:at] + f'return {lv}{step["op"] * 2};' + source[stop:]
    void_at = span[0] + head.start() + head.group(0).index('void')
    return (FAMILY, text[:void_at] + kind.strip() + text[void_at + len('void'):])
