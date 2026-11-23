"""A byte global tested by an `if` and passed to the call inside it, read once earlier into a word local.

`if (G != 0) { call(a, G); }` loads `G` once for both uses (cse), at the place the first scheduler decides: with the
branch the last instruction of its block, the load is one of the later instructions in the ready list and ends up behind
the address arithmetic that the stores before the `if` need. The target loads it first, beside the previous global read
(`lbu $a1,G` right after `lbu $v0,cursor` and before the `xori`), which is the order a read written earlier gives: the
read is an ordinary instruction at the top of the straight-line run, with the same register pressure and an `lbu` that
writes `$a1` (the call's second argument register) from its first use.

The local is a `u32` (a `u8` local would carry its own `andi 0xff` before the call: a word local takes the
zero-extension at the load, as the global's own uses do). `variants` finds `if (G != 0)`, `if (G)` or `if (G == 0)` over
an `extern u8 G;` (or `s8`/`char`) whose arm passes `G` to a call, and for each earlier statement line that every path to the
`if` executes (the same block, or the tail of an unconditional `{ }` / `do { } while (0)` block opened just before it)
within a few lines, with no call, store through a pointer or write to `G` between it and the `if`, a child that declares
`u32 __repair_early_N;` at the top of the function, reads `G` into it after that line and uses it in the guard and the
call. Measured on a 370-instruction mixing-buffer function (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`): 220 -> 100
with the read after the cursor flip that opens the straight-line run, the rows the load's position moved gone; the
judge decides each child (a read placed after the stores changed nothing).
"""
import re

from .integer_repair_support import IDENT, edit, view
from .line_scan import block_end, lines

FAMILY = 'early_global_byte_copy'
FAMILIES = (FAMILY,)
LIMIT = 8
BACK = 12  # statement lines to look back over
EXTERN_BYTE = re.compile(rf'(?m)^[ \t]*extern\s+(?:u8|s8|char|unsigned\s+char)\s+(?P<name>{IDENT})\s*;[ \t]*$')
CONDITIONAL = re.compile(r'^\s*(?:if|else|for|while|switch|case|default)\b')


def _depth_path(body, index):
    """For each line before `index`, the openers still open at `index`: lines whose `{` encloses `index`."""
    stack = []
    for k in range(index):
        text = body[k].text
        stack += [k] * text.count('{')
        for _ in range(text.count('}')):
            if stack:
                stack.pop()
    return stack


def _unconditional(body, opener):
    """Whether the `{` on line `opener` is a bare block or the body of a `do`, not an arm of a condition."""
    if body[opener].text.strip() != '{':
        return not re.match(r'^\s*(?:if|else|for|while|switch)\b', body[opener].text)
    k = opener - 1
    while k >= 0 and not body[k].text.strip():
        k -= 1
    return k < 0 or not CONDITIONAL.match(body[k].text) or bool(re.match(r'^\s*do\b', body[k].text))


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile|goto)\b', part.body) or '__repair_early_' in part.clean:
        return []
    start = max(part.clean.rfind(ch, 0, part.opening) for ch in ';}') + 1
    globals_ = {m['name'] for m in EXTERN_BYTE.finditer(part.clean[:start])}
    if not globals_:
        return []
    body = lines(part, source)
    results = []
    for index, line in enumerate(body):
        guard = re.match(rf'^[ \t]*if\s*\(\s*(?P<g>{IDENT})\s*(?:(?:!=|==)\s*0\s*)?\)\s*$', line.text)
        if not guard or guard['g'] not in globals_ or index + 1 >= len(body) or body[index + 1].text.strip() != '{':
            continue
        g = guard['g']
        close = block_end(body, index + 1)
        if close is None:
            continue
        arm = body[index + 2:close]
        write = re.compile(rf'(?<![\w.>]){g}\s*(?:[-+*&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{g}\b|{g}\s*(?:\+\+|--)')
        first_write = next((k for k, w in enumerate(arm) if write.search(w.text)), len(arm))
        arm = arm[:first_write]  # reads after the first write stay the global's own
        uses = [k for k, w in enumerate(arm) if re.search(rf'(?<![\w.>]){g}\b', w.text)]
        if not uses or not any(re.search(rf'\w\s*\([^;]*(?<![\w.>]){g}\b', arm[k].text) for k in uses):
            continue
        local = f'__repair_early_{len(results)}'
        open_stack = _depth_path(body, index)
        candidates = []
        for k in range(index - 1, max(-1, index - 1 - BACK), -1):
            text = body[k].text
            between = '\n'.join(b.text for b in body[k + 1:index])
            if re.search(rf'(?<![\w.>])(?!(?:if|while|for|switch|sizeof|return)\b){IDENT}\s*\(', between) or \
                    re.search(r'->|\]\s*=(?!=)|(?:(?<=[;{}])|^)\s*\*\s*\(?\w+[^;=]*=(?!=)', between) or \
                    re.search(rf'(?<![\w.>]){g}\s*(?:[-+*&|^]|<<|>>)?=(?!=)|\+\+|--', between):
                break
            if not text.strip().endswith(';') or re.search(r'[{}]|\breturn\b|\bbreak\b|\bcontinue\b', text):
                continue
            # every block that encloses line k but not the `if` must be unconditional
            stack = _depth_path(body, k + 1)
            inside = [o for o in stack if o not in open_stack]
            if all(_unconditional(body, o) for o in inside):
                candidates.append(k)
        for k in candidates:
            indent = body[k].indent
            insert_at = body[k].start + len(body[k].source)
            edits = [(insert_at, insert_at, f'\n{indent}{local} = {g};')]
            edits.append((line.start, line.start + len(line.source), re.sub(rf'(?<![\w.>]){g}\b', local, line.source)))
            for w in arm:
                if re.search(rf'(?<![\w.>]){g}\b', w.text):
                    edits.append((w.start, w.start + len(w.source), re.sub(rf'(?<![\w.>]){g}\b', local, w.source)))
            declaration = part.opening + 1
            edits.append((declaration, declaration, f'\n  u32 {local};'))
            text = edit(source, edits)
            if text != source and (FAMILY, text) not in results:
                results.append((FAMILY, text))
            if len(results) >= LIMIT:
                return results
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}  # the registry: no caller wiring (registry.py)
