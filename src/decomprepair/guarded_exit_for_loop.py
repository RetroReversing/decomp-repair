"""A guarded loop that m2c left by a `goto` or a `do { } while`, written as the `for` loop that walks it.

m2c ends a counted search loop with its exit test inside a guard, and a saved best that was searched from it often
keeps it as

    i = 4;
    p = base;
    if (count > 4) {
        q = p;
        for (;;) {
            if (q->active == 0) { ...  return q->id; }
            i += 1;
            if (q->owner != NULL) { ... }
            q += 0x13C;
            p += 0x13C;
            if (i >= count) {
                goto block_12;
            }
            continue;
            break;
        }
    }
block_12:

The game wrote `for (i = 4, q = p; i < count; i++, q++) { ... }`. jump.c copies a `for` loop's top test in front of
the loop and the loop pass sees the counter step at the end, which moves the allocation of the walked pointer and the
bound's reload: an N64 voice allocator (KMC GCC 2.7.2 `-G0 -mips3 -mgp32 -mfp32 -O2`) went 75 -> 15 with this step
alone, and was exact after two more families (callee_arity_trim, dead_value_store_chain). Why the register order
differs is a hypothesis, not read in the compiler source; the exact judge decides.

guarded_exit_for_loop
    The shape above, or `if (n > K) { [q = p;] do { ... i += 1; ... } while (i < n); }`, with `i = K` before the
    guard (K a number, or a local assigned that number): the loop becomes
    `for (i = K, p = base, q = p; i < n; i += 1, q += S, ...)`, the steps that end the body and the walked pointers'
    starts moved into the header with it.
    The meaning is kept: the same iterations run, so the counter is not read after its step in the body, the body has
    no `break`, `continue` or `goto`, and a local set inside the guard is used nowhere else."""
import re

from .integer_repair_support import IDENT, NUMBER
from .line_scan import apply, block_end, lines, mentions

FAMILY = 'guarded_exit_for_loop'
FAMILIES = (FAMILY,)

_GUARD = re.compile(rf'if\s*\(\s*(?:(?P<n>{IDENT})\s*>\s*(?P<k>{IDENT}|{NUMBER})|(?P<k2>{IDENT}|{NUMBER})\s*<\s*(?P<n2>{IDENT}))\s*\)\s*\{{?')
_COPY = re.compile(rf'(?P<to>{IDENT})\s*=\s*(?P<from>{IDENT})\s*;')
_STEP = re.compile(rf'(?P<var>{IDENT})\s*\+=\s*(?P<by>{NUMBER})\s*;')
_JUMPS = re.compile(r'(?<![\w.>])(?:break|continue|goto)\b')


def _number(text):
    return int(text.rstrip('uUlL'), 0) if re.fullmatch(NUMBER, text) else None


def _set_to(body, name, before):
    """(line, value) of the last `name = NUMBER;` above line `before`, or None."""
    for at in range(before - 1, -1, -1):
        hit = re.fullmatch(rf'{re.escape(name)}\s*=\s*({NUMBER})\s*;', body[at].stripped)
        if hit:
            return at, _number(hit[1])
        if re.match(rf'{re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', body[at].stripped):
            return None
    return None


def _initialiser(body, name, before):
    """(line, `name = value`) of the assignment above `before` that can move down to it: nothing after it names `name`
    or assigns what its value reads."""
    for at in range(before - 1, -1, -1):
        hit = re.fullmatch(rf'(?P<set>{re.escape(name)}\s*=\s*(?P<value>&?{IDENT}))\s*;', body[at].stripped)
        if hit:
            read = hit['value'].lstrip('&')
            for between in body[at + 1:before]:
                if mentions(between.stripped, name) or re.match(rf'{re.escape(read)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', between.stripped):
                    return None
                if '(' in between.stripped:
                    return None
            return at, hit['set']
        if mentions(body[at].stripped, name) or body[at].stripped in ('{', '}'):
            return None
    return None


def _close(body, at):
    """(open line, close line) of the block the statement at `at` opens, `{` on its own line or at its end."""
    if body[at].stripped.endswith('{'):
        opening = at
    elif at + 1 < len(body) and body[at + 1].stripped == '{':
        opening = at + 1
    else:
        return None
    closing = block_end(body, opening)
    return None if closing is None else (opening, closing)


def _loop(body, first, last, bound):
    """(the loop body's line indexes, the counter) of the loop that fills lines first..last, or None."""
    head = body[first].stripped
    if re.fullmatch(r'for\s*\(\s*;\s*;\s*\)\s*\{?', head):
        block = _close(body, first)
        if not block or block[1] != last:
            return None
        inner = [i for i in range(block[0] + 1, block[1]) if body[i].stripped]
        if inner and body[inner[-1]].stripped == 'break;':
            inner.pop()
        if inner and body[inner[-1]].stripped == 'continue;':
            inner.pop()
        else:
            return None
        text = ' '.join(body[i].stripped for i in inner)
        exit_ = re.search(rf'if \(({IDENT}) >= ({IDENT})\) \{{ ?goto ({IDENT}); ?\}}$', text)
        if not exit_ or exit_[2] != bound:
            return None
        # the label the loop leaves to is the first statement after the guard
        count = 3 if body[inner[-1]].stripped == '}' else 1
        return inner[:-count], exit_[1], exit_[3]
    if re.fullmatch(r'do\s*\{?', head):
        block = _close(body, first)
        if not block:
            return None
        tail = ' '.join(body[i].stripped for i in range(block[1], last + 1)).lstrip('} ')
        test = re.fullmatch(rf'while \(\s*({IDENT})\s*<\s*({IDENT})\s*\);', tail)
        if not test or test[2] != bound:
            return None
        return [i for i in range(block[0] + 1, block[1]) if body[i].stripped], test[1], None
    return None


def _rewrite(source, body, at):
    guard = _GUARD.fullmatch(body[at].stripped)
    if not guard:
        return None
    bound, floor = guard['n'] or guard['n2'], guard['k'] or guard['k2']
    block = _close(body, at)
    if not block:
        return None
    opening, closing = block
    inside = [i for i in range(opening + 1, closing) if body[i].stripped]
    copies = []
    while inside and _COPY.fullmatch(body[inside[0]].stripped):
        copies.append(_COPY.fullmatch(body[inside.pop(0)].stripped))
    if not inside:
        return None
    found = _loop(body, inside[0], inside[-1], bound)
    if not found:
        return None
    statements, counter, label = found
    start = _set_to(body, counter, at)
    low = _number(floor)
    if low is None:
        held = _set_to(body, floor, at)
        low = held[1] if held else None
    if not start or low is None or start[1] != low:
        return None
    if any(mentions(body[i].stripped, counter) or any(mentions(body[i].stripped, c['to']) for c in copies)
           for i in range(start[0] + 1, at)):
        return None
    # the label is only reached from this loop, and follows the guard
    drop = []
    if label:
        after = next((i for i in range(closing + 1, len(body)) if body[i].stripped), None)
        if after is None or not body[after].stripped.startswith(f'{label}:'):
            return None
        if sum(len(re.findall(rf'\bgoto\s+{label}\b', line.stripped)) for line in body) != 1:
            return None
        if body[after].stripped == f'{label}:':
            drop.append(after)
    outside = [i for i in range(len(body)) if i < at or i > closing]
    for copy in copies:
        declared = re.compile(rf'(?:[A-Za-z_]\w*[\s*]+)+\*?{re.escape(copy["to"])}\s*;')
        if any(mentions(body[i].stripped, copy['to']) and not declared.fullmatch(body[i].stripped) for i in outside):
            return None
    if any(_JUMPS.search(body[i].stripped) for i in statements):
        return None
    step = re.compile(rf'{re.escape(counter)}\s*(?:\+=\s*1|\+\+)\s*;|{re.escape(counter)}\s*=\s*{re.escape(counter)}\s*\+\s*1\s*;')
    depth, steps = 0, []
    for i in statements:
        if step.fullmatch(body[i].stripped) and depth == 0:
            steps.append(i)
        elif steps and mentions(body[i].stripped, counter):
            return None
        elif re.match(rf'{re.escape(counter)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', body[i].stripped):
            return None
        depth += body[i].text.count('{') - body[i].text.count('}')
    if len(steps) != 1:
        return None
    kept = [i for i in statements if i != steps[0]]
    cursors = []
    while kept and _STEP.fullmatch(body[kept[-1]].stripped):
        cursor = _STEP.fullmatch(body[kept[-1]].stripped)
        if cursor['var'] in (counter, bound):
            break
        cursors.insert(0, f'{cursor["var"]} += {cursor["by"]}')
        kept.pop()
    if not kept:
        return None
    # the walked pointers' own starts go into the header with the counter's
    names = [c['from'] for c in copies] + [c.split()[0] for c in cursors]
    starts = []
    for name in dict.fromkeys(names):
        held = _initialiser(body, name, at)
        if held and held[0] != start[0]:
            starts.append(held)
    first = [f'{counter} = {start[1]}', *(text for _, text in sorted(starts))] + [f'{c["to"]} = {c["from"]}' for c in copies]
    indent = body[at].indent
    cut = min(len(body[i].indent) for i in kept) - len(indent) - 4
    text = [f'{indent}for ({", ".join(first)}; {counter} < {bound}; {", ".join([f"{counter} += 1", *cursors])}) {{']
    for i in kept:
        line = body[i].source
        text.append(line[cut:] if cut > 0 and not line[:cut].strip() else line)
    text.append(f'{indent}}}')
    edits = [(body[at].start, body[closing].end, '\n'.join(text) + '\n')]
    edits += [(body[i].start, body[i].end, '') for i in [start[0], *drop, *(i for i, _ in starts)]]
    return apply(source, edits)


def variants(source, name):
    """[(family, source)]: each guarded loop of the function that can be written as a `for`."""
    from .integer_repair_support import view

    part = view(source, name)
    if not part or re.search(r'\bvolatile\b', part.body):
        return []
    body = lines(part, source)
    out = []
    for at in range(len(body)):
        text = _rewrite(source, body, at)
        if text and text != source:
            out.append((FAMILY, text))
    return out[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
