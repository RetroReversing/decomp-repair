"""A local m2c assigned the same expression in several places, read only where it is used: the expression, written there.

m2c keeps one name for a value the game computed where it was needed, when gcc copied the computation into branch
delay slots (the copies are what m2c read as several assignments):

    if (kind) { var_a0 = base - 0x28; } else { var_a0 = base - 0x28; }
    if (kind >= 2) { ... var_a0 = base - 0x28; goto draw; }
    ...
    draw:  paint(var_a0, base, ...);
    other: erase(var_a0, base, ...);

The game wrote `base - 0x28` as the first argument of `paint` and of `erase`, once each. A named local is a user
variable to GCC 2.7.2 and each assignment is a reference of `base`; `base` had nine references where the original had
seven, which put its allocation priority above a constant's (0.122 against 0.107) and swapped two saved registers
(60 -> 0 on a 490-instruction KMC function once the local was gone). `delay_slot_duplicate` handles the copy before
an `if`, `paired_call_argument_inline` an assignment followed by its call; this is the several-places shape.

The local qualifies when every assignment is a statement of its own with the same plain expression (names, numbers,
arithmetic: no call, load or step), the expression's names are parameters or locals assigned at most once and before
the local's first assignment, and every other mention of the local is a read. The reads become the expression, the
assignments and the declaration go, and an `if`/`else` left empty (pure condition) goes with them. Offered both with
and without the empty `if` dropped, since the two are different programs to cse in principle.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'shared_assignment_inline'
FAMILIES = (FAMILY,)

LIMIT = 6
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*'


def _plain(expression):
    """Arithmetic on names and numbers: no assignment, step, call, load, address or dereference."""
    spaced = expression.replace(' * ', ' MUL ')
    if re.search(r'\+\+|--|\w\s*\(|(?<![=!<>])=(?!=)|(?<!&)&(?![&\s\d(])|\[|->|\*', spaced):
        return False
    return bool(re.fullmatch(r'[\w\s()+\-*/%&|^~<>!]+', expression))


def _names(expression):
    return {n for n in re.findall(IDENT, re.sub(rf'(?<![\w.]){_NUMBER}(?!\w)', ' ', expression)) if n not in ('MUL',)}


def _mentions(clean, local, start, end):
    return [m for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', clean[start:end])]


def _assignments_to(clean, name, start, end):
    """Every place `name` is written: plain, compound or stepped assignment, or its address taken."""
    pattern = (rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(name)}\b|'
               rf'(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)|&\s*{re.escape(name)}\b')
    return [m.start() + start for m in re.finditer(pattern, clean[start:end])]


def _drop_empty_ifs(text, name):
    """Remove `if (pure) {}` and `if (pure) {} else {}` left behind, innermost first."""
    while True:
        part = view(text, name)
        if not part:
            return text
        clean = part.clean
        for hit in re.finditer(r'(?m)^[ \t]*if[ \t]*\(', clean[part.opening:part.end]):
            start = part.opening + hit.start()
            opening = part.opening + hit.end() - 1
            closing = close(clean, opening)
            if not closing:
                continue
            condition = clean[opening:closing]
            if re.search(r'\w\s*\(|(?<![=!<>])=(?!=)|\+\+|--', condition[1:-1]):
                continue
            tail = re.match(r'\s*\{\s*\}(?:\s*else\s*\{\s*\}|(?!\s*else))', clean[closing:part.end])
            if not tail:
                continue
            stop = closing + tail.end()
            line_end = clean.find('\n', stop)
            text = text[:start] + text[(line_end + 1 if line_end >= 0 and not clean[stop:line_end].strip() else stop):]
            break
        else:
            return text


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.clean):
        return []
    clean, base, end = part.clean, part.opening + 1, part.end
    head = clean[:part.opening]
    signature = head[head.rfind('(', 0, head.rfind(')') + 1) + 1:head.rfind(')')] if ')' in head else ''
    parameters = set(re.findall(IDENT, signature))
    declared = {}
    for hit in re.finditer(rf'(?m)^[ \t]*[A-Za-z_][\w \t*]*?[ \t*]({IDENT})[ \t]*;[ \t]*\n', clean[base:end]):
        declared.setdefault(hit[1], []).append((base + hit.start(), base + hit.end()))
    known = set(declared) | parameters
    result = []
    for local, lines in declared.items():
        if len(lines) != 1:
            continue
        pattern = re.compile(rf'(?m)^[ \t]*{re.escape(local)}[ \t]*=(?!=)[ \t]*([^;{{}}=\n][^;{{}}\n]*);[ \t]*\n')
        assigns = [m for m in pattern.finditer(clean, base, end)]
        if len(assigns) < 2:
            continue
        expressions = {' '.join(m[1].split()) for m in assigns}
        if len(expressions) != 1:
            continue
        expression = expressions.pop()
        if not _plain(expression) or not _names(expression) or local in _names(expression):
            continue
        names = _names(expression)
        first = min(m.start() for m in assigns)
        if not names <= known:
            continue
        ok = True
        for n in names:
            writes = _assignments_to(clean, n, base, end)
            if len(writes) > 1 or (writes and writes[0] > first):
                ok = False
        if not ok:
            continue
        spans = {(m.start(), m.end()) for m in assigns}
        reads = []
        for m in _mentions(clean, local, base, end):
            at = base + m.start()
            if any(s <= at < e for s, e in spans) or any(s <= at < e for s, e in lines):
                continue
            tail = clean[at + len(local):at + len(local) + 3]
            if re.match(r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\s*(?:\+\+|--)', tail) or re.search(r'(?:\+\+|--|&)\s*$', clean[max(0, at - 3):at]):
                ok = False
            reads.append((at, at + len(local)))
        if not ok or not reads:
            continue
        bare = re.fullmatch(r'\w+', expression)

        def whole_argument(s, e):
            return re.search(r'[(,]\s*$', clean[:s]) and re.match(r'\s*[,)]', clean[e:])

        edits = [(s, e, expression if bare or whole_argument(s, e) else f'({expression})') for s, e in reads]
        edits += [(s, e, '') for s, e in spans] + [(s, e, '') for s, e in lines]
        inlined = edit(source, edits)
        cleaned = _drop_empty_ifs(inlined, name)
        for text in (cleaned, inlined):
            if text != source and all(text != t for _, t in result):
                result.append((FAMILY, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 40}  # the registry: no caller wiring (registry.py)
