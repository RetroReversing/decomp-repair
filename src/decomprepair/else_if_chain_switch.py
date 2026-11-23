"""m2c's braceless `else if` chain on one value, with a range arm that repeats the default, written as the `switch` it was.

gcc lowers `switch (x) { case 1: A; case 2: B; case 3: C; case 0: default: D; }` to the compare tree
`x == 1`, `x < 2`, `x == 2`, `x == 3`, and m2c reads that tree back as

    if (arg2 == 1) {
        v = A;
    } else if (arg2 < 2) {
        v = D;
    } else if (arg2 == 2) {
        v = B;
    } else if (arg2 == 3) {
        v = C;
    } else {
        v = D;
    }

Compiled as written it is a different branch tree with different delay slots and a different place for each arm's
tail (a 392-instruction object allocator: 6131 -> 5877 with the `switch` alone, the first of the changes that made the
allocation block exact). The `x < N` arm repeats the default's code, so the values below N go to the default: the
`switch` gets one `case v:` label for each value from 0 up to N - 1 that is not a case of its own, in front of
`default:` (the labels are what make the tree; a plain `default` alone compiles to another tree), and `if_tree_switch`
does not read `else if` chains. Only chains over one plain variable with `==` and `<` tests whose arms are one
statement or one block without `break`, `continue`, `goto` or `case` are read; anything else is left alone. The
`case 0:` labels are a hypothesis read off one compiler's tree (KMC GCC 2.7.2); a child without them comes last. The
first child writes `default:` as the first label of the `switch`: gcc places the code of the labels in source order, and
the target's default arm follows the compare chain directly (1252 -> 502 on the object allocator above, the single
largest step of its match); with `default:` last the children are the second and third."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'else_if_chain_switch'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?\s*(?:0[xX][0-9a-fA-F]+|\d+)'
HEAD = re.compile(rf'(?<![\w])if\s*\(\s*({IDENT})\s*(==|<)\s*({NUMBER})[uUlL]*\s*\)')
LIMIT = 3
LABELS = 4  # (how many `case v:` labels to write for the values below the range arm's limit)


def _number(text):
    return int(re.sub(r'\s+', '', text), 0)


def _statement(clean, start):
    """(end, is_block) of the statement at `start`: one `{ ... }` block or one plain statement ending at `;`."""
    while start < len(clean) and clean[start] in ' \t\r\n':
        start += 1
    if start >= len(clean):
        return None
    if clean[start] == '{':
        end = close(clean, start, '{', '}')
        return (start, end) if end else None
    stop = clean.find(';', start)
    if stop < 0 or re.search(r'[{}]|\bif\b|\belse\b', clean[start:stop]):
        return None
    return start, stop + 1


def _chain(clean, start):
    """[(op, value, (a, b))] of the arms from the `if` at `start`, the default's span and the chain's end."""
    arms, pos, variable = [], start, None
    while True:
        head = HEAD.match(clean, pos)
        if not head or (variable and head[1] != variable):
            return None
        variable = head[1]
        body = _statement(clean, head.end())
        if not body:
            return None
        arms.append((head[2], _number(head[3]), body))
        tail = body[1]
        while tail < len(clean) and clean[tail] in ' \t\r\n':
            tail += 1
        if not clean.startswith('else', tail) or re.match(r'\w', clean[tail + 4:tail + 5] or ' '):
            return None
        after = tail + 4
        while after < len(clean) and clean[after] in ' \t\r\n':
            after += 1
        if HEAD.match(clean, after):
            pos = after
            continue
        default = _statement(clean, after)
        return (variable, arms, default) if default else None


def _flat(text):
    return re.sub(r'\s+', ' ', text).strip()


def _arm(source, indent, label, body):
    code = source[body[0]:body[1]].strip()
    return f'{indent}  {label}\n{indent}    {code}\n{indent}    break;\n'


def _build(source, variable, cases, labels, default, indent, first=False):
    """The `switch` text: the cases in value order, the labels of the low values and `default:` last (or first)."""
    default_label = ''.join(f'case {v}:\n{indent}  ' for v in labels)
    lines = ''.join(_arm(source, indent, f'case {value:#x}:' if abs(value) > 9 else f'case {value}:', body)
                    for value, body in cases)
    fallback = (f'{indent}  {default_label}default:\n{indent}    {source[default[0]:default[1]].strip()}\n'
                f'{indent}    break;\n')
    return f'switch ({variable})\n{indent}{{\n' + (fallback + lines if first else lines + fallback) + f'{indent}}}'


def variants(source, name):
    """Proposals: each qualifying chain as a `switch`, with the `case v:` labels first and without them second."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = []
    for hit in HEAD.finditer(clean, span[0], span[1]):
        before = clean[max(span[0], hit.start() - 8):hit.start()].rstrip()
        if before.endswith('else') or hit[2] != '==':
            continue
        chain = _chain(clean, hit.start())
        if not chain:
            continue
        variable, arms, default = chain
        end = default[1]
        text = ' '.join(source[a:b] for _, _, (a, b) in arms) + source[default[0]:default[1]]
        if re.search(r'\b(?:break|continue|goto|case|default|switch)\b', text):
            continue
        ranges = [(op, value, body) for op, value, body in arms if op == '<']
        exact = [(value, body) for op, value, body in arms if op == '==']
        if len(ranges) != 1 or len(exact) < 2 or len({value for value, _ in exact}) != len(exact):
            continue
        _, limit, range_body = ranges[0]
        if _flat(source[range_body[0]:range_body[1]]) != _flat(source[default[0]:default[1]]):
            continue
        # (an arm after the range arm must lie at or above the limit, or it was unreachable)
        position = {id(body): i for i, (_, _, body) in enumerate(arms)}
        if any(value < limit and position[id(body)] > position[id(range_body)] for value, body in exact):
            continue
        line = source.rfind('\n', 0, hit.start()) + 1
        indent = re.match(r'[ \t]*', source[line:hit.start()])[0] if not source[line:hit.start()].strip() else ''
        cases = sorted(exact)
        taken = {value for value, _ in cases}
        labels = [v for v in range(0, min(limit, LABELS)) if v not in taken]
        if limit <= 0 or limit > LABELS + 1:
            labels = []

        for with_labels, first in (((True, True), (True, False), (False, False)) if labels else ((False, True), (False, False))):
            built = _build(source, variable, cases, labels if with_labels else [], default, indent, first)
            out.append(source[:hit.start()] + built + source[end:])
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 56}
