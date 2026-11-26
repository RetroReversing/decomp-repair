"""The code after a `do`/`while` walk, written inside the loop on its exit.

m2c writes a loop that ends by running something once as `do { body } while (c); tail;`. The game often had
`for (;;) { body; if (!c) { tail; break; } }`, which compiles to the same branches but is another program to GCC's loop
pass: the tail's call is now inside the loop, so `loop_has_call` is set and loop.c's threshold for moving an invariant
is halved, and a single-use invariant such as the `andi` of a `u16` start index in the exit test stays in the body
(hypothesis from the dumps; the effect is measured). A 131-instruction box walk over a linked table (KMC GCC 2.7.2,
`-G0 -mips3 -mgp32 -mfp32 -O1`): 600 -> 305, then `call_arity` and `statement_slide` to 0.

Offered for each `do`/`while` whose following statements (up to the next label, `return` or closing brace) hold a call.
Refused when the body has a `break` or `continue` (they would skip the moved tail or the test), or the tail has one.
A candidate for the exact judge, never a verdict.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'do_exit_into_loop'
FAMILIES = (FAMILY,)
LIMIT = 6
_DO = re.compile(r'\bdo\s*\{')
_WHILE = re.compile(r'\s*while\s*\(')
_JUMPS = re.compile(r'\b(?:break|continue)\b')
_CALL = re.compile(rf'\b(?!(?:if|while|for|switch|return|sizeof)\b){IDENT}\s*\(')
_STOP = re.compile(rf'\s*(?:\}}|return\b|case\b|default\b|goto\b|{IDENT}\s*:(?!:))')


def _statement_end(clean, start, end):
    """Where the statement that begins at `start` ends (past its `;` or its block and `else` arms), or None."""
    pos, depth = start, 0
    while pos < end:
        char = clean[pos]
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif depth == 0 and char == ';':
            stop = pos + 1
            break
        elif depth == 0 and char == '{':
            closing = close(clean, pos, '{', '}')
            if closing is None:
                return None
            stop = closing if clean[closing - 1] == '}' else closing + 1
            break
        pos += 1
    else:
        return None
    other = re.compile(r'\s*else\b').match(clean, stop)
    return _statement_end(clean, other.end(), end) if other else stop


def _negated(condition):
    found = re.fullmatch(r'\s*([\w.\[\]>-]+)\s*(==|!=)\s*([\w.\[\]>-]+)\s*', condition)
    if found and found[1].count('>') == found[1].count('->') and found[3].count('>') == found[3].count('->'):
        return f'{found[1]} {"==" if found[2] == "!=" else "!="} {found[3]}'
    return f'!({condition.strip()})'


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    result = []
    for loop in _DO.finditer(clean, part.opening, part.end):
        brace = loop.end() - 1
        body_end = close(clean, brace, '{', '}')
        if body_end is None:
            continue
        if clean[body_end - 1] != '}':
            body_end += 1
        test = _WHILE.match(clean, body_end)
        if not test:
            continue
        paren = close(clean, test.end() - 1, '(', ')')
        if paren is None:
            continue
        if clean[paren - 1] != ')':
            paren += 1
        semi = clean.find(';', paren)
        condition = source[test.end():paren - 1]
        body = clean[brace + 1:body_end - 1]
        if semi < 0 or clean[paren:semi].strip() or condition.strip() in ('0', '1') or _JUMPS.search(body):
            continue
        pos = stop = semi + 1
        while pos < part.end and not _STOP.match(clean, pos):
            pos = _statement_end(clean, pos, part.end)
            if pos is None:
                break
            stop = pos
        tail = clean[semi + 1:stop]
        if not _CALL.search(tail) or _JUMPS.search(tail):
            continue
        inside = source[brace + 1:body_end - 1].rstrip()
        moved = source[semi + 1:stop].strip()
        text = f'for (;;) {{{inside}\nif ({_negated(condition)}) {{\n{moved}\nbreak;\n}}\n}}'
        result.append((FAMILY, edit(source, [(loop.start(), stop, text)])))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring
