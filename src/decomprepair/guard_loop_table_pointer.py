"""A global table read in the body of a `for`/`while` loop inside a guard, read through a pointer the guard's block sets:
`if (..) { for (..) { .. T[i].x ..; } }` as `if (..) { E *tp = T; for (..) { .. tp[i].x ..; } }`.

GCC 2.8.1 (SN64, `-O2`, N64), loop.c: the table address written as `T[i]` is a compiler temporary, so the inner loop moves
its `lui/addiu` pair out (two movables). The enclosing loop then meets that pair again, already moved once, and
`move_movables` doubles `insn_count` for good each time it considers a register `moved_once` (`insn_count *= 2;` is
never undone), so every movable considered after it in the outer loop is judged "not desirable". On a 1585-instruction
collision sweep the outer loop then kept a stack array's address in the loop (the target hoists it and spills it to
the frame, 8 bytes more of frame). With the table read through a pointer the guard sets (a user variable set where the
loop may not reach, `guard_symbol_pointer`'s rule), the inner loop has no such movable, the array address is hoisted and
the frame is the target's: from that function's 10-point source with the table written `T[i]` (1019), the
child that sets the pointer in the innermost guard scored 10 again (the outer guard's child 610).

`guard_symbol_pointer` covers a `do { } while (T[k] == c)` condition; this covers a `for` or `while` loop's body. The
table's element type is read from its declaration (`extern E T[];`, a typedef name too). Each child is one loop: the
pointer declared after the guard block's leading declarations (and, when that differs, first in the block). Declines on
`volatile`.
"""
import re

from .guard_symbol_pointer import _after_declarations, _close, _fresh, _if_blocks
from .integer_repair_support import IDENT, edit, view

FAMILY = 'guard_loop_table_pointer'
FAMILIES = (FAMILY,)
LIMIT = 8
_LOOP = re.compile(r'\b(?:for|while)\s*\(')
_KEYWORDS = {'return', 'sizeof', 'if', 'else', 'while', 'for', 'do', 'switch', 'case', 'goto'}


def _tables(text):
    found = re.finditer(rf'(?m)^[ \t]*extern\s+((?:struct\s+)?{IDENT})\s+({IDENT})\s*\[[^\]]*\]\s*;', text)
    return {m.group(2): m.group(1) for m in found if m.group(1) not in _KEYWORDS}


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(r'\bvolatile\b', clean[lo:hi]):
        return []
    tables = _tables(header + '\n' + source)
    if not tables:
        return []
    out, seen = [], set()
    for opening, closing in _if_blocks(clean, lo, hi):
        for loop in _LOOP.finditer(clean, opening + 1, closing):
            head_open = loop.end() - 1
            head_close = _close(clean, head_open, '(', ')')
            body = re.compile(r'\s*\{').match(clean, head_close + 1) if head_close else None
            if not body:
                continue
            body_open = body.end() - 1
            body_close = _close(clean, body_open, '{', '}')
            if body_close is None or body_close > closing:
                continue
            reads = {}
            for read in re.finditer(rf'(?<![\w.>])({IDENT})\s*\[', clean[body_open:body_close]):
                if read.group(1) in tables:
                    reads.setdefault(read.group(1), []).append(body_open + read.start(1))
            for table, starts in reads.items():
                stem = _fresh(clean, 'tp')
                if not stem:
                    continue
                first = clean.find('\n', opening) + 1
                indent = re.match(r'[ \t]*', clean[first:]).group(0)
                after, _ = _after_declarations(clean, opening, closing)
                uses = [(at, at + len(table), stem) for at in starts]
                for at in dict.fromkeys((after, first)):
                    text = edit(source, [(at, at, f'{indent}{tables[table]} *{stem} = {table};\n'), *uses])
                    if text != source and text not in seen:
                        seen.add(text)
                        out.append((FAMILY, text))
                if len(out) >= LIMIT:
                    return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
