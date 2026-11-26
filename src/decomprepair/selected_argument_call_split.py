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

Two shapes a search leaves around the same pick are taken too (SN64 GCC 2.8.1, a 179-instruction N64 billboard drawer:
`w = 0x10; if (o->f74 == 0 && *(s32 *)(p + 8) == 0x20) { w = 0x20; } do { f(w, q, 0, 0); } while (0);` with `w` reused
much later for a call's copy, 250 -> 10, then 0 under the function's `-mfp32` profile): the call inside a one-shot
`do { } while (0);` (the arms are scopes of their own, so the wrapper is dropped), and V read again after the call when
that later web starts with a plain assignment to V (m2c's reuse of one name for an unrelated value). Plain assignments
to other locals between the pick and the call (`sMax = 0x7C0; tMax = sMax;`) stay ahead of the split `if` when they
change nothing the pick reads. When the later web starts with a copy written just after an early-return guard, the
split is also offered with that copy moved above the guard (`guard_return_copy_hoist`): the drawer needed both at once
(the split alone 635, the hoist alone 250, both 0).
"""
import re

from . import guard_return_copy_hoist
from .integer_repair_support import IDENT, edit, view

FAMILY = 'selected_argument_call_split'
FAMILIES = (FAMILY,)
LIMIT = 4
PICK = re.compile(rf'(?P<v>{IDENT})\s*=\s*(?P<a>[^;{{}}=]+?)\s*;\s*if\s*\((?P<c>[^{{}};]+?)\)\s*\{{\s*(?P=v)\s*=\s*(?P<b>[^;{{}}=]+?)\s*;\s*\}}\s*'
                  rf'(?P<mid>(?:{IDENT}\s*=(?!=)[^;{{}}()=]*;\s*)*)'
                  rf'(?P<wrap>do\s*\{{\s*)?(?P<call>(?:{IDENT}\s*=\s*)?{IDENT}\s*\([^;{{}}]*\)\s*;)'
                  r'(?(wrap)\s*\}\s*while\s*\(\s*0\s*\)\s*;)')


def _new_web(clean, after, later, name_re):
    """Whether V's next mention after the call is a plain assignment that every later read follows: one that does not
    read V itself and stands in the call's own block (not inside a nested arm or a loop the call is not in)."""
    statement = re.match(r'\s*=(?!=)([^;]*);', clean[later.end():])
    if not statement or re.search(name_re, statement[1]):
        return False
    depth = 0
    for char in clean[after:later.start()]:
        depth += (char == '{') - (char == '}')
        if depth < 0:
            return False
    return depth == 0


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    result = []
    for hit in PICK.finditer(clean, part.opening, part.end):
        local = hit['v']
        name_re = rf'(?<![\w.>]){re.escape(local)}\b'
        inside = list(re.finditer(name_re, hit['call']))
        declared = len(re.findall(rf'(?m)^[ \t]*(?:{IDENT}[\s*]+)+{re.escape(local)}\s*;', clean[part.opening:part.end]))
        before = len(re.findall(name_re, clean[part.opening:hit.start()]))
        later = re.compile(name_re).search(clean, hit.end(), part.end)
        if len(inside) != 1 or before != declared:
            continue  # read before the pick, or more than once in the call
        if later and not _new_web(clean, hit.end(), later, name_re):
            continue  # read after the call before a new assignment starts another web
        mid = hit['mid']
        if mid and (re.search(name_re, mid) or set(re.findall(rf'({IDENT})\s*=(?!=)', mid))
                    & set(re.findall(IDENT, hit['a'] + ' ' + hit['b'] + ' ' + hit['c']))):
            continue  # a statement between the pick and the call that reads V or changes what the pick reads
        call = source[hit.start('call'):hit.end('call')]
        indent = re.search(r'[ \t]*$', source[:hit.start()].rsplit('\n', 1)[-1])[0]
        cb = hit.end()
        offset = inside[0].start()
        text_then = call[:offset] + source[hit.start('b'):hit.end('b')].strip() + call[offset + len(local):]
        text_else = call[:offset] + source[hit.start('a'):hit.end('a')].strip() + call[offset + len(local):]
        moved = source[hit.start('mid'):hit.end('mid')].strip()
        rewrite = ((moved + f'\n{indent}' if moved else '') + f'if ({source[hit.start("c"):hit.end("c")].strip()})\n{indent}{{\n{indent}  {text_then}\n{indent}}}\n'
                   f'{indent}else\n{indent}{{\n{indent}  {text_else}\n{indent}}}')
        text = edit(source, [(hit.start(), cb, rewrite)])
        result.append((FAMILY, text))
        if later:  # the later web's copy above its early-return guard too: alone neither moved the billboard drawer
            result += [(FAMILY, hoisted) for hoisted in guard_return_copy_hoist.copies(text, name, local)]
    return result[:LIMIT]
