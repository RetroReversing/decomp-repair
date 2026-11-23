"""A cursor stepped beside a loop counter, written as a fixed base indexed by the counter (GCC 2.7.2, KMC, N64).

m2c and a hand search write a record walk with a cursor of its own:

    q = p + 2;
    i = 0;
    if (p[1]) do {
        x = q[0]; y = q[1]; z = q[2];
        ...
        ++i;
        q += 3;
    } while (i < p[1]);

The game kept `q` as the loop's base and indexed it by the counter (`q[i * 3 + 1]`). The two compile differently, and the
difference is in the loop pass (loop.c): a stepped `q` is a basic induction variable that the loop keeps as it is, so the
loop's own address register is `q` itself (`addiu $s0,$s1,2` straight into the saved register); an invariant `q` that the
loop indexes by `i * 3 + k` is a *derived* address (a giv), and the pass makes a register of its own for it, started from
`q` in the preheader (`addiu $v1,$s1,2` ... `move $s0,$v1`) and stepped by the same amount at the loop's end. Every other
row of the loop is the same, so the saved best reads right and is off by a copy, a register and the scheduling that
follows. Measured on a 559-instruction N64 display-list builder (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`): four such
loops, 2375 -> 1970 in the isolated judge (the `move` row of each loop matched, and the loop's loads and stores followed).

`variants` offers the function with every such loop rewritten at once (`cursor_base_index_loop`), and the same with each
rewritten loop whose entry is `i = 0; if (E) do { ... ++i; } while (i < E);` written as `for (i = 0; i < E; i++)`
(`cursor_base_index_for`): jump.c copies a `for` loop's top test and the pseudos that copy leaves claim frame slots in
reload, which the guarded `do` form does not give (the frame of the function above came out 0x20 bytes short without it).
The rewrite is offered only where it keeps the program's meaning:

  * the cursor is set before the loop by `q = EXPR;` (kept as it is) and inside the loop is only read as `q[index]` (an
    index that does not mention it) and stepped once, by a literal, by a statement `q += S;` of the loop body's own level
    (no `continue`, `break` or `goto` in the body);
  * the counter is set to 0 before the loop (and not touched in between), stepped once by 1 at the body's level, and is
    what the loop's own test compares (`i < E`);
  * every read of the cursor is before its step, and after the loop the cursor is next only assigned (the rewritten
    loop leaves it at its start value, not at the end).
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'cursor_base_index_loop'
FOR_FAMILY = 'cursor_base_index_for'
FAMILIES = (FAMILY, FOR_FAMILY)
MAX_CHILDREN = 6

_DO = re.compile(r'\bdo\s*\{')
_STEP_Q = re.compile(rf'(?<![\w.>])(?P<q>{IDENT})\s*\+=\s*(?P<s>0[xX][0-9a-fA-F]+|\d+)\s*;')
_JUMPS = re.compile(r'\b(?:continue|break|goto|return|switch|case|default)\b')
_IMPURE = re.compile(r'\+\+|--|[^=!<>]=[^=]|\(|\bsizeof\b')


def _is_step(text, counter):
    return re.fullmatch(rf'\s*(?:\+\+\s*{re.escape(counter)}|{re.escape(counter)}\s*\+\+|{re.escape(counter)}\s*\+=\s*1)\s*;\s*', text)


def _plain(text):
    return re.sub(r'\s+', '', text)


def _loops(source, part):
    """Every `[if (E)] do { body } while (i < E2);` that could be indexed, as dicts of positions in `source`."""
    clean = part.clean
    found = []
    for match in _DO.finditer(clean, part.opening + 1, part.end):
        body_open = match.end() - 1
        body_end = close(clean, body_open, '{', '}')
        if not body_end:
            continue
        tail = re.match(r'\s*while\s*\(', clean[body_end:part.end])
        if not tail:
            continue
        cond_open = body_end + tail.end() - 1
        cond_end = close(clean, cond_open)
        if not cond_end or not re.match(r'\s*;', clean[cond_end:]):
            continue
        compare = re.fullmatch(rf'\s*(?P<c>{IDENT})\s*<\s*(?P<bound>[\s\S]+?)\s*', clean[cond_open + 1:cond_end - 1])
        if not compare:
            continue
        semi = cond_end + re.match(r'\s*;', clean[cond_end:]).end()
        found.append({'do': match.start(), 'body_open': body_open, 'body_end': body_end, 'end': semi,
                      'counter': compare['c'], 'bound': compare['bound'], 'cond': (cond_open + 1, cond_end - 1)})
    return found


def _guard(clean, loop, floor):
    """The `if (E)` (optionally with braces around the `do`) that directly opens the loop: (start, end, E) or None."""
    before = clean[floor:loop['do']].rstrip()
    brace = before.endswith('{')
    if brace:
        before = before[:-1].rstrip()
    if not before.endswith(')'):
        return None
    depth = 0
    for at in range(len(before) - 1, -1, -1):
        depth += {')': 1, '(': -1}.get(before[at], 0)
        if depth == 0:
            start = at
            break
    else:
        return None
    head = before[:start].rstrip()
    if not head.endswith('if') or (len(head) > 2 and re.match(r'\w', head[-3])):
        return None
    condition = before[start + 1:-1].strip()
    guard_start = floor + len(head) - 2
    end = loop['end']
    if brace:
        rest = clean[loop['end']:]
        shut = re.match(r'\s*\}', rest)
        if not shut:
            return None
        end = loop['end'] + shut.end()
    return guard_start, end, condition


def _rewrite(source, part, loop):
    """The edits that index this loop's cursor by its counter, or None."""
    clean = part.clean
    body = clean[loop['body_open'] + 1:loop['body_end'] - 1]
    counter = loop['counter']
    if _JUMPS.search(body):
        return None
    # the cursor step is a statement of the body's own level, and the only one of them
    steps = [hit for hit in _STEP_Q.finditer(body) if body[:hit.start()].count('{') == body[:hit.start()].count('}')]
    if len(steps) != 1:
        return None
    step = steps[0]
    q, size = step['q'], int(step['s'], 0)
    if size <= 0 or q == counter:
        return None
    # the counter: one step of 1 at the body's level, no other write
    increments = [m for m in re.finditer(rf'(?:\+\+\s*{re.escape(counter)}|(?<![\w.>]){re.escape(counter)}\s*\+\+|(?<![\w.>]){re.escape(counter)}\s*\+=\s*1)\s*;', body)]
    if len(increments) != 1 or body[:increments[0].start()].count('{') != body[:increments[0].start()].count('}'):
        return None
    if re.search(rf'(?<![\w.>]){re.escape(counter)}\s*(?:=(?!=)|[-*/|&^%]=|<<=|>>=|\+=(?!\s*1\s*;))|--\s*{re.escape(counter)}\b|(?<![\w.>]){re.escape(counter)}\s*--|&\s*{re.escape(counter)}\b', body):
        return None
    # the cursor: only q[...] reads and the step, every read before the step
    reads = []
    for use in re.finditer(rf'(?<![\w.>]){re.escape(q)}\b', body):
        if use.start() == step.start('q'):
            continue
        wrapped = re.match(r'(?:\s*\))*', body[use.end():])
        indexed = re.match(r'\s*\[', body[use.end() + wrapped.end():])
        if not indexed:
            return None
        first = use.start()  # `((q))[k]`: the parentheses that close right after the cursor go with their openers
        for _ in range(body[use.end():use.end() + wrapped.end()].count(')')):
            held = body[:first].rstrip()
            if not held.endswith('('):
                return None
            first = len(held) - 1
        at = use.end() + wrapped.end() + indexed.end() - 1
        shut = close(body, at, '[', ']')
        if not shut:
            return None
        index = body[at + 1:shut - 1]
        if re.search(rf'(?<![\w.>]){re.escape(q)}\b', index):
            return None
        if use.start() > step.start():
            return None
        reads.append((first, shut, index))
    if not reads:
        return None
    # the cursor is set before the loop and the counter starts at 0 just before it
    floor = part.opening + 1
    before = clean[floor:loop['do']]
    assigned = list(re.finditer(rf'(?<![\w.>]){re.escape(q)}\s*=(?!=)[^;]*;', before))
    zero = list(re.finditer(rf'(?<![\w.>]){re.escape(counter)}\s*=\s*0\s*;', before))
    if not assigned or not zero:
        return None
    if re.search(rf'(?<![\w.>]){re.escape(counter)}\b', before[zero[-1].end():]) and \
            not _guard(clean, loop, floor):
        return None
    after = clean[loop['end']:part.end]
    later = re.search(rf'(?<![\w.>]){re.escape(q)}\b', after)
    if later and not re.match(r'\s*=(?!=)', after[later.end():]):
        return None
    base = loop['body_open'] + 1
    edits = []
    for start, shut, index in reads:
        text = source[base + start:base + shut]
        inner = index.strip()
        scaled = f'{counter} * {size}' if size != 1 else counter
        new = f'{q}[{scaled}]' if inner == '0' else f'{q}[{scaled} + {inner}]'
        edits.append((base + start, base + shut, new))
        del text
    edits.append((base + step.start(), base + step.end(), ''))
    return edits, (q, counter, zero[-1], size)


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    plain, forms = [], []
    for loop in _loops(source, part):
        if loop['counter'] == loop['bound'].strip():
            continue
        done = _rewrite(source, part, loop)
        if not done:
            continue
        edits, (q, counter, zero, size) = done
        plain.append(edits)
        guard = _guard(part.clean, loop, part.opening + 1)
        body = part.clean[loop['body_open'] + 1:loop['body_end'] - 1]
        steps = list(re.finditer(rf'(?:\+\+\s*{re.escape(counter)}|(?<![\w.>]){re.escape(counter)}\s*\+\+|(?<![\w.>]){re.escape(counter)}\s*\+=\s*1)\s*;', body))
        if not guard or not steps:
            continue
        rest = body[steps[0].end():]
        if re.search(r'\S', _STEP_Q.sub('', rest)):
            continue
        condition = guard[2]
        bound = loop['bound'].strip()
        zero_test = re.fullmatch(r'(?P<e>[\s\S]+?)\s*(?:>\s*0|!=\s*0)', condition)
        equal = _plain(zero_test['e'] if zero_test else condition) == _plain(bound)
        if not equal or _IMPURE.search(re.sub(r'\[[^\]]*\]', '', bound)):
            continue
        base = loop['body_open'] + 1
        zero_start = part.opening + 1 + zero.start()
        zero_end = part.opening + 1 + zero.end()
        keep = [e for e in edits]
        step_edit = (base + steps[0].start(), base + steps[0].end(), '')
        inside = edit(source[base:loop['body_end'] - 1], [(s - base, e - base, r) for s, e, r in keep + [step_edit]])
        forms.append([(zero_start, zero_end, ''), (guard[0], guard[1],
                      f'for ({counter} = 0; {counter} < {bound}; {counter}++) {{{inside}}}')])
    out = []
    if plain:
        out.append((FAMILY, edit(source, [e for group in plain for e in group])))
    if forms:
        out.append((FOR_FAMILY, edit(source, [e for group in forms for e in group])))
    for group in plain[:2] if len(plain) > 1 else []:
        out.append((FAMILY, edit(source, group)))
    return list(dict.fromkeys(out))[:MAX_CHILDREN]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
