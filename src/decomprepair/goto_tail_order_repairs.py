"""Arms that end in the same two statements and the same `goto`, written in two orders so the compiler keeps both.

m2c folds a switch whose cases all finish by storing one value through one pointer into a shared label:

    case 3:  call(a);  ptr = state->slot;  v = 4;  goto block_9;
    case 8:  call(b);  ptr = state->slot;  v = 4;  goto block_9;
    ...
    block_9: *(ptr + 0x7A) = v;

GCC 2.7.2's second jump pass cross-jumps arms whose last instructions are identical: two arms that end in the same
two moves and the same jump collapse into one, and the other arm becomes `j` to it. When the game's code still has
each arm's own `lw`/`li`/`j` tail (a function whose arms were 3685 and 3015 points off with the arms merged and
split), the source never had identical arms: the two statements were written in another order in one of them. The
instructions are independent, so the scheduler puts them in the target's order either way, but the cross-jump
compares them before it does.

Offered for every set of two or more `goto LABEL;` that follow the same two assignments (in the same order), when the
two assignments don't read each other's target and call nothing: one variant swaps the pair in every arm but the
first, and one swaps it in a single arm (each of the first six). The score decides which arm.
"""
import re

from .csource import _blank, find

FAMILY = 'goto_tail_order'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
_STATEMENT = re.compile(r'(?P<indent>[ \t]*)(?P<lhs>[^;{}=]+?)\s*=(?!=)\s*(?P<rhs>[^;{}]*);[ \t]*\n')
_GOTO = re.compile(r'(?m)^[ \t]*goto\s+(?P<label>' + IDENT + r')\s*;')
_PLAIN_LHS = re.compile(r'\s*' + IDENT + r'\s*')
LIMIT = 8


def _tail(clean, goto):
    """The two assignments written right before `goto`, as match objects, or None."""
    found = []
    at = goto.start()
    for _ in range(2):
        # the previous statement ends with `;` + newline just before `at`; walk back to its start line
        end = at
        line_start = clean.rfind('\n', 0, end - 1) + 1 if end else 0
        hit = _STATEMENT.fullmatch(clean, line_start, end)
        if not hit:
            return None
        found.append(hit)
        at = line_start
    return found[::-1]


def _independent(first, second):
    for one, two in ((first, second), (second, first)):
        if '(' in one['rhs'] and re.search(IDENT + r'\s*\(', one['rhs']):
            return False  # a call: its order is the program's
        if not _PLAIN_LHS.fullmatch(one['lhs']):
            return False
        if re.search(r'(?<![\w.>])' + re.escape(one['lhs'].strip()) + r'\b', two['rhs']):
            return False
    return first['lhs'].strip() != second['lhs'].strip()


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    text = source[span[0]:span[1]]
    clean = _blank(text)
    groups = {}
    for goto in _GOTO.finditer(clean):
        pair = _tail(clean, goto)
        if not pair or not _independent(*pair):
            continue
        key = (goto['label'], pair[0].group(0).strip(), pair[1].group(0).strip())
        groups.setdefault(key, []).append(pair)
    result = []
    for pairs in groups.values():
        if len(pairs) < 2:
            continue

        def swapped(chosen):
            out, last = [], 0
            for first, second in sorted(chosen, key=lambda p: p[0].start()):
                out.append(text[last:first.start()])
                out.append(text[second.start():second.end()] + text[first.start():first.end()])
                last = second.end()
            out.append(text[last:])
            return source[:span[0]] + ''.join(out) + source[span[1]:]
        result.append((FAMILY, swapped(pairs[1:])))
        for pair in pairs[:6]:
            if len(pairs) > 2 or pair is not pairs[1]:
                result.append((FAMILY, swapped([pair])))
        if len(result) >= LIMIT:
            break
    seen, unique = set(), []
    for family, fixed in result:
        if fixed not in seen and fixed != source:
            seen.add(fixed)
            unique.append((family, fixed))
    return unique[:LIMIT]
