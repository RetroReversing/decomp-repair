"""A switch that only filters which values reach the code after it, which m2c leaves empty.

    if (busy != 0) {
        switch (id) {
        case 1: case 6: case 10: break;
        default: return;
        }
    }
    rest();

compiles to a jump table whose case entries all go to one place, the start of `rest()`, which the other path of the
`if` falls into. m2c writes that as `if (busy != 0) { switch (id); } else { rest(); }` with the case labels inside
the `else`; its compilable form drops the labels, so the draft has an empty switch and the values it let through are
gone. Case values aren't in the assembly's instructions, only in the table, so this reads `tables` (the function's
jump tables: lowest case value and the address each case enters).

A table with exactly two destinations says it: one is the code the listed values reach, the other leaves. Which is
which isn't known from the table alone, so both are offered (the smaller set first), and so are labels counted from 0
when the table's lowest value was read from a subtraction the draft already made in a temporary. The rewrite only
applies in a `void` function where nothing follows the `if`, so `default: return;` is the same program."""
import re

from .integer_repair_support import view
from .pattern_repairs import close

FAMILY = 'filter_switch_cases'
FAMILIES = (FAMILY,)
LIMIT = 8
_IF = re.compile(r'\bif\s*\(')
_EMPTY = re.compile(r'\s*switch\s*\(')


def _block(clean, at):
    """(opening brace, index past its closing brace) of the block starting at or after `at`, else None."""
    brace = at + len(clean[at:]) - len(clean[at:].lstrip())
    if clean[brace:brace + 1] != '{' or not (end := close(clean, brace, '{', '}')):
        return None
    return brace, end


def _empty_switch(clean, block):
    """(start, end) of the expression of `switch (E);` when that is the block's only statement, else None."""
    head = _EMPTY.match(clean, block[0] + 1, block[1] - 1)
    if not head or not (end := close(clean, head.end() - 1)):
        return None
    if clean[end:block[1] - 1].strip() != ';':
        return None
    return head.end(), end - 1


def _leaves_the_function(clean, opening, at):
    """Whether `return;` at `at` skips only what follows in the function: the `if` is a whole statement (not the
    body of an `else` or a braceless `if`) and no block around it is a loop or a switch."""
    if clean[opening:at].rstrip()[-1:] not in ('{', '}', ';', ':'):
        return False
    heads, last = [], opening + 1
    for hit in re.finditer(r'[{};]', clean[opening + 1:at]):
        position = opening + 1 + hit.start()
        if hit[0] == '{':
            heads.append(clean[last:position])
        elif hit[0] == '}' and heads:
            heads.pop()
        last = position + 1
    return not any(re.search(r'\b(?:for|while|do|switch)\b', head) for head in heads)


def _case_sets(tables):
    found = []
    for low, targets in tables:
        destinations = list(dict.fromkeys(targets))
        if len(destinations) != 2 or not 2 <= len(targets) <= 256:
            continue
        sets = sorted(([i for i, to in enumerate(targets) if to == wanted] for wanted in destinations), key=len)
        for values in sets:
            for base in dict.fromkeys((low, 0)):
                labels = tuple(base + i for i in values)
                if labels not in found:
                    found.append(labels)
    return found


def variants(source, name, tables=()):
    sets = _case_sets(tables or ())
    part = view(source, name) if sets else None
    if not part or not re.search(r'\bvoid\s+' + re.escape(name) + r'\s*\(', part.clean):
        return []
    clean, result = part.clean, []
    for hit in _IF.finditer(clean, part.opening, part.end):
        if not _leaves_the_function(clean, part.opening, hit.start()):
            continue
        condition_end = close(clean, hit.end() - 1)
        first = condition_end and _block(clean, condition_end)
        other = first and re.compile(r'\s*else\b').match(clean, first[1])
        second = other and _block(clean, other.end())
        if not second or not re.fullmatch(r'(?:\s|\}|\breturn\s*;)*', clean[second[1]:part.end]):
            continue
        for empty, rest, negate in ((first, second, False), (second, first, True)):
            expression = _empty_switch(clean, empty)
            if not expression:
                continue
            indent = source[source.rfind('\n', 0, hit.start()) + 1:hit.start()]
            indent = indent if not indent.strip() else '    '
            condition = source[hit.end():condition_end - 1]
            if negate:
                condition = '!(%s)' % condition
            body = source[rest[0] + 1:rest[1] - 1].rstrip()
            for values in sets:
                cases = ''.join('%s    case %d:\n' % (indent, value) for value in values)
                text = (f'if ({condition}) {{\n{indent}    switch ({source[expression[0]:expression[1]]}) {{\n'
                        f'{cases}{indent}        break;\n{indent}    default:\n{indent}        return;\n'
                        f'{indent}    }}\n{indent}}}\n{indent}{{{body}\n{indent}}}')
                result.append((FAMILY, source[:hit.start()] + text + source[second[1]:]))
                if len(result) >= LIMIT:
                    return result
    return result


REPAIR = {
    'families': FAMILIES,
    'variants': variants,
    'needs': ('source', 'name', 'tables'),
}
