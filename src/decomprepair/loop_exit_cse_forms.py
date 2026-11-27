"""Three loop and cse spellings that GCC 2.7.2 at `-O1` keeps apart, each a step of one N64 function (560 -> 10, then 0).

1. `do { body } while (a < K && b);` is folded to one `and` of two flags (fold-const.c turns `&&` of plain comparisons
   into a bit operation), where the target has two branches: write `if (!(a < K)) { break; }` at the end of the body and
   keep `b` as the loop's test (`loop_and_break`).
2. `x = E; while (x != K) { ...; x = E; }` duplicates the load where the game assigned in the test,
   `while ((x = E) != K)` (`loop_test_assignment`): 335 -> 105 on the same function.
3. `if (i <= v) { table[i] = a; }` reuses the test's zero-extension of the narrow `i` for the subscript. The target
   extends it again: an empty `do { } while (0);` at the head of the arm leaves a loop note, and cse stops its extended
   block at a loop's end (`arm_head_loop_note`): 105 -> 0.

Every child keeps the program's meaning; `loop_exit_cse_combined` applies all that fit at once, since the function above
needed all three. A candidate: the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

AND_BREAK = 'loop_and_break'
ASSIGN = 'loop_test_assignment'
NOTE = 'arm_head_loop_note'
COMBINED = 'loop_exit_cse_combined'
FAMILIES = (AND_BREAK, ASSIGN, NOTE, COMBINED)
LIMIT = 8
_DO = re.compile(r'\bdo\s*{')
_TAIL = re.compile(r'\s*while\s*\(')
_PRIMED = re.compile(rf'(?<![\w.>\]])(?P<var>{IDENT})\s*=(?!=)\s*(?P<expr>[^;{{}}]+);(?P<gap>\s*)while\s*\(\s*(?P=var)\s*'
                     r'(?P<op>!=|==|<=|>=|<(?!<)|>(?!>))\s*(?P<limit>-?\w+)\s*\)\s*{')
_IF = re.compile(r'\bif\s*\(')


def _indent(source, offset):
    return re.match(r'[ \t]*', source[source.rfind('\n', 0, offset) + 1:offset])[0]


def _split_and(condition):
    """The condition's first operand and the rest, when it is an `&&` chain with no `||` or `?` beside it."""
    depth = 0
    cut = None
    for offset, char in enumerate(condition):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif not depth:
            if condition.startswith('||', offset) or char in '?,':
                return None
            if cut is None and condition.startswith('&&', offset):
                cut = offset
    if cut is None:
        return None
    return condition[:cut].strip(), condition[cut + 2:].strip()


def _and_break(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    result = []
    for hit in _DO.finditer(clean, part.opening, part.end):
        opening = hit.end() - 1
        end = close(clean, opening, '{', '}')
        tail = end and _TAIL.match(clean, end)
        if not tail or re.search(r'\bcontinue\b', clean[opening:end]):
            continue
        paren = tail.end() - 1
        stop = close(clean, paren, '(', ')')
        halves = stop and _split_and(source[paren + 1:stop - 1])
        if not halves:
            continue
        outer = _indent(source, hit.start())
        inner = outer + '    '
        break_test = f'    if (!({halves[0]})) {{\n{inner}    break;\n{inner}}}\n{outer}'
        result.append(edit(source, [(end - 1, end - 1, break_test), (paren + 1, stop - 1, halves[1])]))
    return result


def _assign(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    result = []
    for hit in _PRIMED.finditer(clean, part.opening, part.end):
        opening = hit.end() - 1
        end = close(clean, opening, '{', '}')
        if not end or re.search(r'\bcontinue\b', clean[opening:end]):
            continue
        var = hit['var']
        last = re.search(rf'(?<![\w.>\]]){var}\s*=(?!=)\s*(?P<expr>[^;{{}}]+);\s*}}$', clean[opening:end])
        if not last or ''.join(last['expr'].split()) != ''.join(hit['expr'].split()):
            continue
        before = clean[:hit.start()].rstrip()
        if not before.endswith((';', '{', '}')):
            continue
        start = opening + last.start()
        line = source.rfind('\n', 0, start) + 1
        if not source[line:start].strip():
            start = line - 1
        expression = source[hit.start('expr'):hit.end('expr')].strip()
        test = f'while (({var} = {expression}) {hit["op"]} {hit["limit"]}) {{'
        stop = opening + clean[opening:end].rindex(';') + 1
        result.append(edit(source, [(hit.start(), hit.end(), test), (start, stop, '')]))
    return result


def _noted(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    result = []
    for hit in _IF.finditer(clean, part.opening, part.end):
        paren = hit.end() - 1
        stop = close(clean, paren, '(', ')')
        brace = stop and re.compile(r'\s*{').match(clean, stop)
        if not brace:
            continue
        opening = brace.end() - 1
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        inside = clean[opening + 1:end - 1]
        if re.match(r'\s*do\s*{\s*}', inside):
            continue
        tested = set(re.findall(rf'(?<![\w.>]){IDENT}', clean[paren:stop]))
        indexed = set(re.findall(rf'\[\s*(?:\([^()\[\]]*\)\s*)?({IDENT})\b[^\[\]]*\]', inside))
        if not tested & indexed:
            continue
        indent = _indent(source, hit.start()) + '    '
        result.append((opening + 1, f'\n{indent}do {{ }} while (0);'))
    return result


def _note(source, name):
    return [edit(source, [(offset, offset, text)]) for offset, text in _noted(source, name)]


def variants(source, name):
    result = [(family, child)
              for family, make in ((AND_BREAK, _and_break), (ASSIGN, _assign), (NOTE, _note))
              for child in make(source, name)[:LIMIT]]
    combined = source
    applied = 0
    for make in (_assign, _and_break):
        children = make(combined, name)
        if children:
            combined, applied = children[0], applied + 1
    notes = _noted(combined, name)
    if notes:
        combined = edit(combined, [(offset, offset, text) for offset, text in notes])
        applied += 1
    if applied > 1:
        result.insert(0, (COMBINED, combined))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
