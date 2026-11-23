"""Two arms that each end in the same `return`, written as an if/else and one `return` after it.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) voice-picker whose last statements counted the voice into
one of two tables: m2c wrote `if (flag) { a += 1; return best; } b += 1; return best;`. The target has no `move
$v0,best` hoisted above the branch: each arm ends in its own `j epilogue` with the move in the jump's delay slot after
its table update, while the source with a `return best;` in both arms put one copy of the move in front of the branch
for both. `if (flag) { a += 1; } else { b += 1; } return best;` gave that arrangement (4265 -> 2640; the whole function
was then 2640 -> 2415 -> 1550 -> ... from further edits).

shared_return_tail
    `if (C) { A return V; } B return V;` becomes `if (C) { A } else { B } return V;` when `V` is a name or a number,
    `return V;` is the last statement of the enclosing block, `A` and `B` hold no other `return`, `goto`, label, `case`
    or declaration, and the `if` has no `else` of its own and is not itself an `else if`. Hypothesis from the match,
    not from the compiler source: with one `return` after the join the epilogue's move is part of the join block, so
    the scheduler and reorg treat each arm's last insn as the jump's delay slot candidate.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .c_scan import close, enclosing_block, normal
from .integer_repair_support import edit, view

FAMILY = 'shared_return_tail'
FAMILIES = (FAMILY,)
LIMIT = 6
_IF = re.compile(r'\bif\s*\(')
_RETURN = re.compile(r'\breturn\s+(-?\s*[A-Za-z_0-9]\w*)\s*;')
_BLOCKED = re.compile(
    r'\breturn\b|\bgoto\b|\bcase\b|\bdefault\b|^\s*[A-Za-z_]\w*\s*:(?!:)'
    r'|^\s*(?:unsigned|signed|const|static|register|volatile|char|short|int|long|float|double|void|[su](?:8|16|32|64)|f(?:32|64))\b[^;=()]*[;=]',
    re.M)


def _ends_with_return(text):
    """The `return V;` closing `text` as a whole statement (not the body of an `if`/`else`), as (start, V)."""
    for hit in _RETURN.finditer(text):
        if text[hit.end():].strip():
            continue
        before = text[:hit.start()].rstrip()
        if not before or before[-1] in ';{}:' and not before.endswith('else'):
            return hit.start(), normal(hit[1])
    return None


def _children(source, clean, low, high):
    out = []
    for hit in _IF.finditer(clean, low, high):
        opening = hit.end() - 1
        closing = close(clean, opening, '(', ')')
        if closing < 0 or re.search(r'\belse\s*$', clean[:hit.start()]):
            continue
        block = re.match(r'\s*\{', clean[closing + 1:])
        if not block:
            continue
        body_open = closing + 1 + block.end() - 1
        body_close = close(clean, body_open)
        if body_close < 0 or re.match(r'\s*else\b', clean[body_close + 1:]):
            continue
        tail = _ends_with_return(clean[body_open + 1:body_close])
        if not tail:
            continue
        ret_start, value = tail
        owner = enclosing_block(clean, hit.start(), low)
        owner_close = close(clean, owner) if owner >= 0 else high - 1
        rest = clean[body_close + 1:owner_close]
        last = _ends_with_return(rest)
        if not last or last[1] != value or not rest[:last[0]].strip():
            continue
        then_text = clean[body_open + 1:body_open + 1 + ret_start]
        else_text = rest[:last[0]]
        if _BLOCKED.search(then_text) or _BLOCKED.search(else_text):
            continue
        line = source.rfind('\n', 0, hit.start()) + 1
        indent = re.match(r'[ \t]*', source[line:hit.start()])[0] if not source[line:hit.start()].strip() else ''
        then_source = source[body_open + 1:body_open + 1 + ret_start].rstrip()
        else_source = '\n'.join(('  ' + line if line.strip() else line)
                                for line in source[body_close + 1:body_close + 1 + last[0]].strip('\n').rstrip().split('\n'))
        final = source[body_close + 1 + last[0]:body_close + 1 + len(rest)]
        final = final.rstrip() + final[len(final.rstrip()):]
        new = (f'{source[hit.start():body_open + 1]}{then_source}\n{indent}}}\n{indent}else\n{indent}{{\n'
               f'{else_source}\n{indent}}}\n{indent}{final.strip()}{final[len(final.rstrip()):]}')
        out.append((hit.start(), body_close + 1 + len(rest), new))
    return out


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    return [(FAMILY, edit(source, [item])) for item in _children(source, part.clean, part.opening + 1, part.end)[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
