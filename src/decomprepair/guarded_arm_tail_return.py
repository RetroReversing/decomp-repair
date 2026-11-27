"""A one-armed `if` before a short tail that returns, written as two paths that each end with that tail.

Matched on an SN64 gcc 2.8.1 (`-G0 -mips3 -O2`) 160-instruction N64 timer update. The draft wrote

    if (phase != 0) { state = 1; }
    play(0x96);  timer = 0;  self->mode = 3;  return;

and the target had `beqz phase` with `li $a0,0x96` in its delay slot, then a second `li $a0,0x96`, the store, and one
shared `jal`. That is the call written twice: with the guard inverted (`if (!(C)) { T return; } S T return;`) the
object is exact (460 -> 0); with the arm first (`if (C) { S T return; } T return;`) reorg deletes the second `li` as
redundant (100, one instruction short). Why reorg keeps it in one order and not the other is a hypothesis (it deletes
redundant copies only in a thread it owns); jump2 cross-jumps the two tails back into one either way.

guarded_arm_tail_return
    `if (C) { S } T return ...;` (S and T plain statements, T with a call) becomes
    `if (!(C)) { T return; } S T return;` and `if (C) { S T return; } T return;`.

The exact judge decides every child.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'guarded_arm_tail_return'
FAMILIES = (FAMILY,)
LIMIT = 8
MAX_ARM = 4
MAX_TAIL = 8
_CONTROL = re.compile(r'[{}]|\b(?:if|else|for|while|do|switch|case|default|goto|break|continue|return|asm)\b'
                      rf'|(?:^|;)\s*{IDENT}\s*:(?!:)')
_DECLARATION = re.compile(rf'(?:^|;)\s*(?:(?:const|volatile|static|register)\s+)*(?:(?:struct|union|enum|unsigned|signed)\s+)?'
                          rf'{IDENT}\s+\**\s*{IDENT}\s*(?:\[[^\]]*\]\s*)?[=;]')
_CALL = re.compile(rf'\b(?!sizeof\b){IDENT}\s*\(')


def _statements(clean, start, end):
    """The (start, end) of each `;`-ended statement from `start`, stopping after `end` or the first brace."""
    depth, begin = 0, start
    for pos in range(start, end):
        char = clean[pos]
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif char in '{}':
            return
        elif char == ';' and depth == 0:
            while clean[begin].isspace():
                begin += 1
            yield begin, pos + 1
            begin = pos + 1


def _plain(text):
    return not (_CONTROL.search(text) or _DECLARATION.search(text))


def _negated(condition):
    """`a != b` as `a == b` and back; any other condition under `!`."""
    simple = re.fullmatch(r'\s*([^!=<>&|?()]+?)\s*(==|!=)\s*([^!=<>&|?()]+?)\s*', condition)
    if simple:
        return f'{simple[1]} {"!=" if simple[2] == "==" else "=="} {simple[3]}'
    if re.fullmatch(rf'\s*{IDENT}\s*', condition):
        return f'!{condition.strip()}'
    return f'!({condition.strip()})'


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, result = part.clean, []
    for hit in re.finditer(r'\bif\s*\(', clean[part.opening + 1:part.end]):
        start = part.opening + 1 + hit.start()
        if re.search(r'\belse\s*$', clean[:start]):
            continue
        paren = part.opening + 1 + hit.end() - 1
        paren_end = close(clean, paren, '(', ')')
        if paren_end is None:
            continue
        brace = re.compile(r'\s*\{').match(clean, paren_end)
        if not brace:
            continue
        opening = brace.end() - 1
        closing = close(clean, opening, '{', '}')
        if closing is None or re.compile(r'\s*else\b').match(clean, closing):
            continue
        body = clean[opening + 1:closing - 1]
        if not body.rstrip().endswith(';') or body.count(';') > MAX_ARM or not _plain(body):
            continue
        tail, returned = [], None
        for begin, end in _statements(clean, closing, part.end):
            text = clean[begin:end]
            if re.match(r'return\b', text):
                returned = (begin, end)
                break
            if len(tail) >= MAX_TAIL or not _plain(text):
                break
            tail.append((begin, end))
        if not returned or not tail or not any(_CALL.search(clean[a:b]) for a, b in tail):
            continue
        indent = source[source.rfind('\n', 0, start) + 1:start]
        if indent.strip():
            continue
        inner = indent + '  '
        shared = [source[a:b] for a, b in tail] + [source[returned[0]:returned[1]]]
        arm = [source[a:b] for a, b in _statements(clean, opening + 1, closing - 1)]

        def block(statements, pad):
            return ''.join(f'{pad}{s}\n' for s in statements)

        condition = source[paren + 1:paren_end - 1]
        tail_first = (f'if ({_negated(condition)})\n{indent}{{\n{block(shared, inner)}{indent}}}\n'
                      + block(arm + shared, indent))
        arm_first = f'if ({condition})\n{indent}{{\n{block(arm + shared, inner)}{indent}}}\n' + block(shared, indent)
        for text in (tail_first, arm_first):
            # `start` follows the indent already in the source; the last line's newline is the source's own.
            result.append((FAMILY, edit(source, [(start, returned[1], text[:-1].lstrip())])))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
