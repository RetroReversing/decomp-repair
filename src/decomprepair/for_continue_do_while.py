"""An outer `for` loop with `continue`s and a nested loop, written as a guarded `do`/`while` whose skips jump to its step.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) 1445-instruction collision query: an object-list walk
`for (; obj != NULL; obj = obj->next) { if (...) continue; ... if (flags & 4) { for (j..) {..} } else { for (j..) {..} } }`
left one difference, the end of the first inner loop: the target has `beqz $v0, exit; nop; j top` where the `for`
gave `bnez $v0, top; nop; j exit`. Traced in cc1 (lldb on reorg.c `mostly_true_jump`): relax_delay_slots swaps a
conditional branch and the unconditional jump after it when the branch is predicted taken, and does so once in each
of its two passes. After the first swap the branch goes to the outer loop's continue label; for a rotated `for`
that label is followed by the NOTE_INSN_LOOP_VTOP duplicate_loop_exit_test leaves, which mostly_true_jump reads as
"a jump to a loop test" (1, taken), so the second pass swaps the pair back. A `do`/`while` has no LOOP_VTOP note,
the branch to its step is predicted not taken (an EQ test, 0) and the first swap stands: 350 -> 0 on that function.

for_continue_do_while
    `for (I; C; S) { B }`, where B holds a nested `for`/`while`/`do` loop, becomes
    `I; if (C) { do { B' next: S; } while (C); }` with every `continue;` that belongs to this loop (not to a nested
    one) in B written `goto next;`. Offered only when C and S read no call.

The exact judge decides every child.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'for_continue_do_while'
FAMILIES = (FAMILY,)
LIMIT = 4
_FOR = re.compile(r'\bfor\s*\(')


def _nested_loop_ranges(clean, low, high):
    """(start, end) of the bodies of loops inside [low, high)."""
    ranges = []
    for hit in re.finditer(r'\b(?:for|while)\s*\(|\bdo\s*\{', clean[low:high]):
        at = low + hit.start()
        if hit[0].startswith('do'):
            brace = low + hit.end() - 1
        else:
            paren = low + hit.end() - 1
            after = close(clean, paren, '(', ')')
            if after is None:
                continue
            rest = clean[after:high]
            stripped = rest.lstrip()
            if not stripped.startswith('{'):
                # A `while (...)` that ends a do-while, or a one-statement body: the statement runs to its `;`.
                end = clean.find(';', after, high)
                if end >= 0 and stripped[:1] != ';':
                    ranges.append((at, end + 1))
                continue
            brace = after + (len(rest) - len(stripped))
        end = close(clean, brace, '{', '}')
        if end is not None:
            ranges.append((at, end))
    return ranges


def _children(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, result = part.clean, []
    for hit in _FOR.finditer(clean, part.opening + 1, part.end):
        paren = hit.end() - 1
        after = close(clean, paren, '(', ')')
        if after is None:
            continue
        header = clean[paren + 1:after - 1]
        pieces = header.split(';')
        if len(pieces) != 3:
            continue
        init, cond, step = (p.strip() for p in pieces)
        if not cond or not step or re.search(rf'{IDENT}\s*\(', cond + ' ' + step):
            continue
        rest = clean[after:part.end]
        if not rest.lstrip().startswith('{'):
            continue
        body_open = after + (len(rest) - len(rest.lstrip()))
        body_close = close(clean, body_open, '{', '}')
        if body_close is None:
            continue
        nested = _nested_loop_ranges(clean, body_open + 1, body_close - 1)
        if not nested:
            continue
        label = 'next_' + (re.match(IDENT, step)[0] if re.match(IDENT, step) else 'step')
        if re.search(rf'\b{re.escape(label)}\b', clean):
            continue
        continues = [m for m in re.finditer(r'\bcontinue\s*;', clean[body_open:body_close])
                     if not any(a <= body_open + m.start() < b for a, b in nested)]
        line_start = source.rfind('\n', 0, hit.start()) + 1
        indent = source[line_start:hit.start()]
        if indent.strip():
            continue
        body = source[body_open + 1:body_close - 1]
        for m in sorted(continues, key=lambda m: -m.start()):
            body = body[:m.start() - 1] + f'goto {label};' + body[m.end() - 1:]
        inner = body.rstrip()
        close_ws = source[source.rfind('\n', 0, body_close - 1) + 1:body_close - 1]
        text = (f'{init};\n{indent}' if init else '') + (
            f'if ({cond})\n{indent}{{\n{indent}do\n{indent}{{{inner}\n'
            f'{indent}{label}:\n{indent}  {step};\n{indent}}}\n{indent}while ({cond});\n{indent}}}')
        if close_ws.strip():
            continue
        result.append((FAMILY, edit(source, [(hit.start(), body_close, text)])))
        if len(result) >= LIMIT:
            break
    return result


def variants(source, name, header=''):
    return _children(source, name)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
