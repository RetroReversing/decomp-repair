"""A byte string walked by a pointer written as the index loop it came from.

m2c reads a loop over a buffer as a pointer that starts at the base and steps until it reaches the base plus the length
(`p = text; do { c = *p; ...; p += 1; ... } while (p < (char *) ((u32) n + (u32) text));`), with extra steps in the
arms that consume a following byte (an escape or a colour code, a skipped pad byte), and hands the pointer itself to a
callee. A text measuring function of a KMC (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) 82-instruction font routine
sat at 360: the draft's loop was the same program, but the target had the jump table's address, the pointer's start and
the end address emitted in the order `la, move, addu`, while the walked pointer gave `move, la, addu`. The source the
game had indexed the buffer by a counter (`for`-style: `c = text[i]`, `i++` in the arms that consume a byte, the
callee given `text + i`, the loop test `i < n`) and the compiler's loop pass made the pointer itself, as a derived
induction variable, with its initial value emitted among the hoisted loop invariants. Written that way the function
scored 0 with no other edit (a `u32` counter; the compare against the length as an unsigned `sltu`).

This is `loop_pointer_to_index`'s sibling for a pointer that has *no* counter beside it: the pointer's own end test
names the length. `loop_pointer_to_index` needs a counter the pointer is stepped with; here the counter is made.
The mechanism (the derived induction variable's initial value is emitted with the hoisted invariants) is a hypothesis
from the measured order, not read from loop.c; the exact judge decides.

Rewrites, for one pointer `p` that a statement `p = base;` sets, walked by a `do { } while (p < END)` or
`for (p = base; p < END; p++)` loop whose END is `base + N` (in either order, with integer or pointer casts):
`p = base;` is `i = 0;`, `*p` is `base[i]`, `p[k]` is `base[i + k]`, any other read of `p` is `(base + i)`, each step
(`p++;`, `++p;`, `p += 1;`, `p = p + 1;`) is `i++;`, the test is `i < N`, and the pointer's declaration becomes the
`u32` counter's. Nothing is offered when `p` is used outside the loop or its set, assigned any other way, stepped in an
expression, has its address taken, or `base` is assigned inside the loop."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'string_walk_index'
FAMILIES = (FAMILY,)
CASTS = re.compile(r'\(\s*(?:(?:const|unsigned|signed|struct)\s+)*[A-Za-z_]\w*(?:\s+\w+)*\s*\**\s*\)')
STEP = r'(?:{p}\s*\+\+|\+\+\s*{p}|{p}\s*\+=\s*1|{p}\s*=\s*{p}\s*\+\s*1)'
NAMES = ('i', 'index', 'pos', 'n_index')


def _uses(text, name):
    return [m for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', text)]


def _terms(text):
    """The top-level `+` terms of an expression with its casts and outer parentheses removed."""
    text = CASTS.sub('', text).strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = CASTS.sub('', text[1:-1]).strip()
    depth, terms, last = 0, [], 0
    for at, char in enumerate(text):
        depth += char in '(' or -(char in ')')
        if char == '+' and depth == 0 and text[at + 1:at + 2] != '+' and text[at - 1:at] != '+':
            terms.append(text[last:at])
            last = at + 1
    terms.append(text[last:])
    return [CASTS.sub('', t).strip() for t in terms]


def _limit(test, pointer, base):
    """N of a loop test `pointer < base + N`, or None when the test is any other shape."""
    hit = re.fullmatch(rf'\s*\(*\s*{re.escape(pointer)}\s*\)*\s*<\s*(.+?)\s*', test, re.S)
    if not hit:
        return None
    terms = _terms(hit[1])
    if len(terms) != 2:
        return None
    rest = [t for t in terms if t.strip('() ') != base]
    if len(rest) != 1 or len(rest) == len(terms):
        return None
    limit = rest[0]
    return limit if re.fullmatch(rf'{IDENT}|\d+|\(.+\)', limit, re.S) else f'({limit})'


def _loops(clean, opening, end):
    """(loop start, init span or None, test span, step span or None, body span, loop end) of every do/while and for loop."""
    for hit in re.finditer(r'\bdo\s*\{', clean[opening:end]):
        body_open = opening + hit.end() - 1
        body_end = close(clean, body_open, '{', '}')
        tail = re.compile(r'\s*while\s*\(').match(clean, body_end) if body_end else None
        test_end = close(clean, tail.end() - 1) if tail else None
        after = re.compile(r'\s*;').match(clean, test_end) if test_end else None
        if after:
            yield opening + hit.start(), None, (tail.end(), test_end - 1), None, (body_open + 1, body_end - 1), after.end()
    for hit in re.finditer(r'\bfor\s*\(', clean[opening:end]):
        head = opening + hit.end() - 1
        head_end = close(clean, head)
        brace = re.compile(r'\s*\{').match(clean, head_end) if head_end else None
        parts = clean[head + 1:head_end - 1].split(';') if head_end else []
        body_end = close(clean, brace.end() - 1, '{', '}') if brace else None
        if body_end and len(parts) == 3:
            first = head + 1
            second = first + len(parts[0]) + 1
            third = second + len(parts[1]) + 1
            yield (opening + hit.start(), (first, first + len(parts[0])), (second, third - 1), (third, head_end - 1),
                   (brace.end(), body_end - 1), body_end)


def _unary(text):
    """True when a `*` that follows `text` dereferences (rather than multiplies): after an operator, `(`, `return`, or a cast."""
    text = text.rstrip()
    if not text or text[-1] in '(,=!<>+-*/%&|^?:;{}[~' or re.search(r'\breturn$', text):
        return True
    if text.endswith(')'):
        depth = 0
        for at in range(len(text) - 1, -1, -1):
            depth += text[at] == ')' or -(text[at] == '(')
            if depth == 0:
                return bool(CASTS.fullmatch(text[at:]))
    return False


def _fresh(clean):
    return next((n for n in NAMES if not _uses(clean, n)), None)


def _decl(clean, opening, end, pointer):
    hit = re.search(rf'(?m)^([ \t]*)(?:[A-Za-z_]\w*[ \t]+)*[A-Za-z_]\w*[ \t]*\*[ \t]*{re.escape(pointer)}[ \t]*;[ \t]*\n', clean[opening:end])
    return (opening + hit.start(), opening + hit.end(), hit[1]) if hit else None


def _keep(clean, span, text):
    """`text` with the leading blanks of the span it replaces (a `for` header's spacing is kept)."""
    return clean[span[0]:span[1]][:len(clean[span[0]:span[1]]) - len(clean[span[0]:span[1]].lstrip())] + text


def _rewrite(source, part, loop, pointer, counter, decl):
    clean = part.clean
    start, init, test, step, body, stop = loop
    if init is not None:
        hit = re.fullmatch(rf'\s*{re.escape(pointer)}\s*=\s*({IDENT})\s*', clean[init[0]:init[1]])
        if not hit:
            return None
        base, init_edit, init_stmt = hit[1], (init[0], init[1], _keep(clean, init, f'{counter} = 0')), init
    else:
        sets = list(re.finditer(rf'(?<![\w.>]){re.escape(pointer)}\s*=\s*({IDENT})\s*;', clean[part.opening:start]))
        if len(sets) != 1:
            return None
        found = sets[0]
        base = found[1]
        init_stmt = (part.opening + found.start(), part.opening + found.end())
        init_edit = (*init_stmt, f'{counter} = 0;')
    limit = _limit(clean[test[0]:test[1]], pointer, base)
    inside = clean[body[0]:body[1]]
    if limit is None or re.search(
            rf'(?<![\w.>]){re.escape(base)}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(base)}\b|(?<![\w.>]){re.escape(base)}\s*(?:\+\+|--)', inside):
        return None
    edits = [init_edit, (test[0], test[1], _keep(clean, test, f'{counter} < {limit}'))]
    claimed = [init_stmt, test, decl[:2]]
    if step is not None:
        if not re.fullmatch(r'\s*' + STEP.format(p=re.escape(pointer)) + r'\s*', clean[step[0]:step[1]]):
            return None
        edits.append((step[0], step[1], _keep(clean, step, f'{counter}++')))
        claimed.append(step)
    for use in re.finditer(STEP.format(p=re.escape(pointer)) + r'\s*;', inside):
        if not re.search(r'(?:[;{}:)]|\belse|\bdo)\s*$', clean[:body[0] + use.start()]):
            continue
        span = (body[0] + use.start(), body[0] + use.end())
        edits.append((*span, f'{counter}++;'))
        claimed.append(span)
    for use in _uses(inside, pointer):
        at, to = body[0] + use.start(), body[0] + use.end()
        if any(a <= at < b for a, b in claimed):
            continue
        before = clean[:at].rstrip()
        after = clean[to:]
        if re.match(r'\s*(?:\+\+|--|[-+*/|&^]?=(?!=)|<<=|>>=)', after) or (before.endswith(('++', '--', '&')) and not before.endswith('&&')):
            return None
        subscript = re.match(r'\s*\[', after)
        if subscript:
            end = close(clean, to + subscript.end() - 1, '[', ']')
            if end is None:
                return None
            edits.append((at, end, f'{base}[{counter} + {clean[to + subscript.end():end - 1].strip()}]'))
            claimed.append((at, end))
        elif before.endswith('*') and _unary(before[:-1]):
            edits.append((len(before) - 1, to, f'{base}[{counter}]'))
        else:
            edits.append((at, to, f'({base} + {counter})'))
    outside = [m for m in _uses(clean[part.opening:part.end], pointer)
               if not any(a <= part.opening + m.start() < b for a, b in claimed)
               and not any(e[0] <= part.opening + m.start() < e[1] for e in edits)]
    if outside:
        return None
    edits.append((decl[0], decl[1], f'{decl[2]}u32 {counter};\n'))
    return edit(source, edits)


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    if re.search(r'\b(?:asm|__asm__|goto|volatile)\b|^\s*#', clean[part.opening:part.end], re.M):
        return []
    counter = _fresh(clean[part.opening:part.end])
    out = []
    for loop in _loops(clean, part.opening, part.end):
        head = re.match(rf'\s*\(*\s*({IDENT})\s*\)*\s*<', clean[loop[2][0]:loop[2][1]])
        decl = _decl(clean, part.opening, part.end, head[1]) if head else None
        if counter and decl:
            text = _rewrite(source, part, loop, head[1], counter, decl)
            if text and text != source:
                out.append((FAMILY, text))
    return list(dict.fromkeys(out))[:3]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 80}  # the registry: no caller wiring (registry.py)
