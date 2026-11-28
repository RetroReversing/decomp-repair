"""A loop whose exit is the `else` of its test, so the compiler leaves the test at the top.

GCC 2.x rolls a loop that starts with its exit test to the bottom (`stmt.c`, `expand_end_loop`, and `jump.c`'s
copy of the entry test), so `for (;;) { if (i >= n) break; ... }`, `while (i < n)` and `for` all come out as a guard
plus a test at the foot. A game that keeps `sltu; beqz exit` at the head and a `j` back wrote the exit where the
roller does not look for it: `while (1) { if (c) { body } else break; }`, whose conditional jump goes to the `else`
and not to the loop's end label. That reading of the compiler is a hypothesis for SN's builds (no source); the
measurement is not: an 84-instruction N64 function with two such loops (SN GCC 2.8.1 `-G0 -mips3 -O2`) scored 3170
with `for (;;) { if (i >= count) break; ... }` and 0 with this spelling.

`loop_else_break` rewrites one loop at a time, from `for`, `while`, `for (;;) { if (c) break; ... }`, m2c's
`for (;;) { ...; if (c) { ...; continue; } break; }` and a `label: PRE; if (c) { ...; goto label; }` (PRE goes to the head of the loop body).
`loop_else_break_all` rewrites every such loop at once, nested ones included: copies of one loop in two arms, or
the levels of one nest, only pay off together.
`loop_else_break_arms` also moves a constant set just before an `if`/`else` to the head of both arms, where the loop
that uses it can hoist around it (the same function's counter).

A goto loop with statements between the label and its test needed two families in turn, whose first step (a `for (;;)`
with a `break`) scored worse than where it started; a 31-instruction N64 name-printing loop (SN GCC 2.8.1 `-G0 -mips3
-O2`) reached 0 from this one child and a base pointer inlined (`symbol_base_inline`).

`loop_else_break_base` is every loop rewritten with each `__base_SYM = SYM;` local written out
(`local_load_widths`' `symbol_base_inline`): on that function the loop alone tied the seed's score (500) and the two
together were exact.

A `for` with a `continue` of its own keeps its step: each such `continue` becomes a `goto` to a label ahead of it. An
exit written `if (c) goto done;` with `done:` right after the loop is read as the `break` it is. A 209-instruction
triangle emitter with five nested counted loops (SN GCC 2.8.1 `-G0 -mips3 -O2`) went from the `for` spelling to the
target's head tests and `j` back edges only with both.

Meaning is kept: a `goto` loop with a free `break` or `continue` is declined (they would bind to the new loop)."""
import re

from . import local_load_widths
from .csource import _blank, find
from .goto_structure_repairs import IDENT, _gotos, parse, walk
from .pattern_repairs import close, negate

ONE = 'loop_else_break'
ALL = 'loop_else_break_all'
ARMS = 'loop_else_break_arms'
BASE = 'loop_else_break_base'
FAMILIES = (ONE, ALL, ARMS, BASE)
LIMIT = 6


def _text(source, span):
    return source[span[0]:span[1]].strip()


def _free(stmts, word):
    """A `break`/`continue` in `stmts` that belongs to the loop around them (a `switch` keeps its `break`, not
    its `continue`)."""
    for s in stmts:
        if s.kind == 'jump' and s.parts.get('word') == word:
            return True
        if s.kind in ('do', 'while', 'for') or s.kind == 'switch' and word == 'break':
            continue
        if any(_free(s.parts[key]['stmts'], word) for key in ('then', 'other', 'body') if s.parts.get(key)):
            return True
    return False


def _mark_jumps(clean, stmts):
    for s, _ in walk(stmts):
        if s.kind == 'jump':
            s.parts['word'] = re.match(r'\w+', clean[s.start:s.end].lstrip())[0]


def _between(source, body):
    """The text between a block's braces (or its single statement)."""
    if body['block']:
        return source[body['open'] + 1:body['close'] - 1]
    return source[body['open']:body['close']]


def _is_break(part):
    return part is not None and len(part['stmts']) == 1 and part['stmts'][0].kind == 'jump' \
        and part['stmts'][0].parts['word'] == 'break'


def _not(condition):
    return negate(condition) or f'!({condition})'


def _build(indent, prelude, condition, body, tail=''):
    step = indent + '        '
    rows = [r.rstrip() for r in body.split('\n')]
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    margin = min((len(r) - len(r.lstrip()) for r in rows if r.strip()), default=0)
    lines = [step + r[margin:] if r.strip() else '' for r in rows]
    if tail:
        lines.append(f'{step}{tail};')
    head = [f'{indent}    {r.strip()}' for r in prelude.split('\n') if r.strip()]
    out = ['while (1) {'] + head + [f'{indent}    if ({condition}) {{'] + lines
    out += [f'{indent}    }} else {{', f'{indent}        break;', f'{indent}    }}', f'{indent}}}']
    return '\n'.join(out)


def _indent(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:])[0]


def _for_parts(condition):
    parts, depth, last = [], 0, 0
    for i, ch in enumerate(condition):
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
        elif ch == ';' and not depth:
            parts.append(condition[last:i].strip())
            last = i + 1
    parts.append(condition[last:].strip())
    return parts if len(parts) == 3 else None


def _prelude(source, stmts):
    """The statements before the test, one a line, with `do { ... } while (0);` fences and bare blocks opened."""
    out = []
    for s in stmts:
        if s.kind == 'simple':
            out.append(source[s.start:s.end])
            continue
        if s.kind == 'block' or s.kind == 'do' and _text(source, s.parts['cond']) == '0':
            body = s.parts['body']
            inner = _prelude(source, body['stmts']) if body['block'] else None
            if inner is not None:
                out.append(inner)
                continue
        return None
    return '\n'.join(out)


def _loop(source, clean, function, loop):
    """(start, end, replacement) for one `for`/`while` loop, or None."""
    body = loop.parts['body']
    stmts = body['stmts']
    head = _text(source, loop.parts['cond'])
    indent = _indent(source, loop.start)
    if loop.kind == 'for':
        parts = _for_parts(head)
        if not parts:
            return None
        init, condition, step = parts
    else:
        init, condition, step = '', '' if head in ('1', '(1)') else head, ''
    if condition:
        inner = _between(source, body)
        if step and _free(stmts, 'continue'):
            inner = _to_step(source, clean, body, loop.start)
            if inner is None:
                return None
        text = _build(indent, '', condition, inner, step)
    else:
        if init or step or not body['block'] or not stmts:
            return None
        first = stmts[0]
        exit_label = _exit_goto(clean, loop, first)
        if first.kind == 'if' and first.parts.get('other') is None \
                and (_is_break(first.parts['then']) or exit_label):
            if exit_label and _free(stmts[1:], 'break'):
                return None
            rest = source[first.end:body['close'] - 1]
            if not rest.strip():
                return None
            text = _build(indent, '', _not(_text(source, first.parts['cond'])), rest)
        else:
            # m2c: PRE; if (c) { B; continue; } break;
            if len(stmts) < 2 or not (stmts[-1].kind == 'jump' and stmts[-1].parts['word'] == 'break'):
                return None
            test = stmts[-2]
            if test.kind != 'if' or test.parts.get('other') is not None:
                return None
            then = test.parts['then']
            if not then['block'] or len(then['stmts']) < 2:
                return None
            last = then['stmts'][-1]
            if not (last.kind == 'jump' and last.parts['word'] == 'continue'):
                return None
            pre = _prelude(source, stmts[:-2])
            if pre is None:
                return None
            text = _build(indent, pre, _text(source, test.parts['cond']), source[then['open'] + 1:last.start])
    if init:
        text = f'{init};\n{indent}{text}'
        before = clean[:loop.start].rstrip()
        if not before.endswith(('{', '}', ';', ':')):  # the unbraced body of an `if` or `else`
            text = f'{{\n{indent}{text}\n{indent}}}'
    return loop.start, loop.end, text


def _exit_goto(clean, loop, first):
    """The label of `if (c) goto L;` when `L:` directly follows the loop: the same exit a `break` takes."""
    if first.kind != 'if' or first.parts.get('other') is not None:
        return None
    then = first.parts['then']
    if len(then['stmts']) != 1 or then['stmts'][0].kind != 'goto':
        return None
    target = then['stmts'][0].parts['target']
    return target if re.match(rf'\s*{target}\s*:(?!:)', clean[loop.end:]) else None


def _to_step(source, clean, body, at):
    """The body of a `for` with each `continue` of its own written as a `goto` to a label ahead of the step, or None
    when a `continue` cannot be told from an inner loop's."""
    if not body['block']:
        return None
    spots = []

    def collect(stmts):
        for s in stmts:
            if s.kind == 'jump' and s.parts.get('word') == 'continue':
                spots.append((s.start, s.end))
            if s.kind in ('do', 'while', 'for'):
                continue
            for key in ('then', 'other', 'body'):
                if s.parts.get(key):
                    collect(s.parts[key]['stmts'])

    collect(body['stmts'])
    label, number = 'repair_step', 1
    while re.search(rf'\b{label}\b', clean):
        number += 1
        label = f'repair_step{number}'
    label = f'{label}_{at}'
    low, high = body['open'] + 1, body['close'] - 1
    text = source[low:high]
    for start, end in sorted(spots, reverse=True):
        word = source[start:end]
        lead = len(word) - len(word.lstrip())
        text = text[:start - low] + word[:lead] + f'goto {label};' + text[end - low:]
    indent = _indent(source, body['stmts'][-1].start)
    return f'{text.rstrip()}\n{indent}{label}:;'


def _goto_loops(source, clean, function):
    """(start, end, replacement) for each `label: PRE; if (c) { ...; goto label; }`; PRE, which the loop repeats,
    may be empty and holds only plain statements (m2c's `temp = i & 0xFFFF;` before the test)."""
    out = []
    for block in _blocks(function):
        for at, label in enumerate(block):
            if label.kind != 'label':
                continue
            found = next((i for i in range(at + 1, len(block)) if block[i].kind == 'if'), None)
            if found is None:
                continue
            test, prelude = block[found], _prelude(source, block[at + 1:found])
            between = block[at + 1:found]
            if prelude is None or test.parts.get('other') is not None or _free(between, 'break') \
                    or _free(between, 'continue'):
                continue
            name, then = label.parts['name'], test.parts['then']
            if not then['block'] or len(then['stmts']) < 2:
                continue
            last = then['stmts'][-1]
            if last.kind != 'goto' or last.parts['target'] != name or len(_gotos(function, name)) != 1:
                continue
            kept = then['stmts'][:-1]
            if _free(kept, 'break') or _free(kept, 'continue'):
                continue
            body = source[then['open'] + 1:last.start]
            indent = _indent(source, test.start)
            text = _build(indent, prelude, _text(source, test.parts['cond']), body)
            line = source.rfind('\n', 0, label.start) + 1
            if not source[line:label.start].strip():
                out.append((line, test.end, indent + text))
            else:
                out.append((label.start, test.end, text))
    return out


def _blocks(stmts):
    yield stmts
    for s, _ in walk(stmts):
        for key in ('then', 'other', 'body'):
            if s.parts.get(key):
                yield s.parts[key]['stmts']


def _edits(source, name):
    """The non-overlapping loop rewrites of `name`: [(start, end, replacement)]."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or re.search(r'\b(?:setjmp|longjmp|asm|__asm__)\b', clean[opening:end]):
        return None
    try:
        function = parse(clean, opening + 1, end - 1)
    except ValueError:
        return None
    _mark_jumps(clean, function)
    found = [e for s, _ in walk(function) if s.kind in ('for', 'while') if (e := _loop(source, clean, function, s))]
    found += _goto_loops(source, clean, function)
    return sorted(found), clean, function, (opening, end)


def _apply(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def _disjoint(edits):
    kept, reach = [], -1
    for edit in edits:
        if edit[0] >= reach:
            kept.append(edit)
            reach = edit[1]
    return kept


def _into_arms(source, name):
    """`v = K;` right before an `if`/`else` that does not test `v`, moved to the head of both arms."""
    parsed = _edits(source, name)
    if not parsed:
        return None
    _, clean, function, (opening, end) = parsed
    for block in _blocks(function):
        for store, test in zip(block, block[1:]):
            if store.kind != 'simple' or test.kind != 'if' or not test.parts.get('other'):
                continue
            m = re.fullmatch(rf'({IDENT})\s*=\s*(-?(?:0x[0-9A-Fa-f]+|\d+))\s*;', clean[store.start:store.end])
            if not m:
                continue
            v = m[1]
            then, other = test.parts['then'], test.parts['other']
            if not (then['block'] and other['block']) or re.search(rf'\b{v}\b', _text(clean, test.parts['cond'])) \
                    or re.search(rf'&\s*{v}\b', clean[opening:end]) \
                    or not re.search(rf'\n\s*[^\n;{{}}()=]*\b{v}\s*(?:=[^=;]*)?;', clean[opening:store.start]):
                continue  # not a plain local declared in this function
            statement = source[store.start:store.end]
            edits = [(store.start, test.start, '')]
            for arm in (then, other):
                indent = _indent(source, arm['stmts'][0].start) if arm['stmts'] else _indent(source, test.start) + '    '
                edits.append((arm['open'] + 1, arm['open'] + 1, f'\n{indent}{statement}'))
            return _apply(source, edits)
    return None


def _unbased(source, name):
    """Every search symbol base (`__base_SYM = SYM;`) written out."""
    for _ in range(LIMIT):
        child = next((text for family, text in local_load_widths.variants(source, name)
                      if family == local_load_widths.FAMILY_BASE), None)
        if child is None:
            break
        source = child
    return source


def _every(source, name):
    """Every loop rewritten, the ones nested in a rewritten loop too: one round per depth."""
    for _ in range(LIMIT):
        parsed = _edits(source, name)
        if not parsed or not parsed[0]:
            break
        source = _apply(source, _disjoint(parsed[0]))
    return source


def variants(source, name):
    parsed = _edits(source, name)
    if not parsed:
        return []
    found = _disjoint(parsed[0])
    if not found:
        return []
    out = []
    every = _every(source, name)
    moved = _into_arms(every, name)
    if len(found) > 1 or every != _apply(source, found):
        out.append((ALL, every))
    unbased = _unbased(every, name)
    if unbased != every:
        out.append((BASE, unbased))
    if moved:
        out.append((ARMS, moved))
    out += [(ONE, _apply(source, [edit])) for edit in found]
    seen, kept = {source}, []
    for family, text in out:
        if text not in seen:
            seen.add(text)
            kept.append((family, text))
    return kept[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 94}  # registry.py
