"""A call argument picked by an `if` into a local: the call written once in each arm.

m2c reads `f(cond ? a : b, ...)` back as `v = a; if (cond) { v = b; } r = f(v, ...);`. The original had the call in
both arms (or the compiler's cross-jumping made one of two calls out of it): with the selection written into a local
the call's setup, the copy of its result and the arguments' schedule come out differently from the target.

On an 842-instruction N64 lit-actor drawer (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`, scoring 2) the light lookup
`var_a0 = arg0; if (flags & 0x1000) { var_a0 = temp_s0; } idx = find(var_a0, &r, &g, &b);` went 4183 -> 3728 as
`if (flags & 0x1000) { idx = find(temp_s0, ...); } else { idx = find(arg0, ...); }`: the compiler merged the two call
sequences again (one `jal`, the other arm's `move $a0` in the delay slot) and the copy of the result went to the top of
the block, where the target has it. The explanation is a hypothesis, not confirmed in the compiler source (the delay
slot and cross-jump are reorg.c and jump.c).

`selected_argument_call_split` offers, for three consecutive statements `V = A;`, `if (C) { V = B; }` and a call that
names V once, with V read nowhere else, the function with the call written in both arms. The judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'selected_argument_call_split'
FAMILIES = (FAMILY,)
LIMIT = 4
PICK = re.compile(rf'(?P<v>{IDENT})\s*=\s*(?P<a>[^;{{}}=]+?)\s*;\s*if\s*\((?P<c>[^{{}};]+?)\)\s*\{{\s*(?P=v)\s*=\s*(?P<b>[^;{{}}=]+?)\s*;\s*\}}\s*'
                  rf'(?P<call>(?:{IDENT}\s*=\s*)?{IDENT}\s*\([^;{{}}]*\)\s*;)')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    result = []
    for hit in PICK.finditer(clean, part.opening, part.end):
        local = hit['v']
        uses = list(re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', clean[part.opening:part.end]))
        inside = list(re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', hit['call']))
        declared = len(re.findall(rf'(?m)^[ \t]*(?:{IDENT}[\s*]+)+{re.escape(local)}\s*;', clean[part.opening:part.end]))
        if len(inside) != 1 or len(uses) != 2 + len(inside) + declared:
            continue  # read anywhere but the pick and the one call
        call = source[hit.start('call'):hit.end('call')]
        indent = re.search(r'[ \t]*$', source[:hit.start()].rsplit('\n', 1)[-1])[0]
        cb = hit.end('call')
        offset = inside[0].start()
        text_then = call[:offset] + source[hit.start('b'):hit.end('b')].strip() + call[offset + len(local):]
        text_else = call[:offset] + source[hit.start('a'):hit.end('a')].strip() + call[offset + len(local):]
        rewrite = (f'if ({source[hit.start("c"):hit.end("c")].strip()})\n{indent}{{\n{indent}  {text_then}\n{indent}}}\n'
                   f'{indent}else\n{indent}{{\n{indent}  {text_else}\n{indent}}}')
        result.append((FAMILY, edit(source, [(hit.start(), cb, rewrite)])))
    return result[:LIMIT]
