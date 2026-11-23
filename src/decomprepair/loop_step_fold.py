"""A counter stepped at the end of every path of an endless loop, written as the `for` step it was.

m2c writes a counted loop whose test sits at the top as `for (;;) { if (!(i < n)) break; ...; i += 1; }` and, when the
body forks, steps the counter in each arm: one arm steps early (`i += 1; release(p);`), another jumps to a shared
`block_N: i += 1;` that closes the other arm. Those are the same program as `for (;; i += 1) { ... }`, but not the
same RTL: the step of a `for` is emitted once, at the loop's continue label, so the end of the body is one block that
every path joins, where the copies end in as many jumps back to the top. gcc 2.7.2's delay-slot filling (`reorg.c`,
`fill_simple_delay_slots`) then differs in which instruction goes behind the jump back: it takes the instruction
before the jump when the jump follows a step and nothing else, and one from the loop head (`fill_slots_from_thread`)
when a label lies between, and the saved-register allocation orders the counter and the entry pointer by the
references each has, which the copies change too (KMC gcc 2.7.2, a 252-instruction menu builder: 360 -> 0 on this
step alone; the loop head's `move $a0,$zero` sat in the jump's slot instead of the step).

- `loop_step_fold`: in `for (;;)` or `while (1)` with no `continue`, a step `v += k;` (or `v++;`, `v = v + k;`) that
  closes every path of the body (a trailing step, a step followed only by statements that do not read `v`, a `goto`
  to a `L: v += k;` that ends another arm of the same body, or a path that leaves by `break` or `return`) is dropped
  from the arms and written once, as the loop's own step `for (;; v += k)`. It declines when a path ends without a
  step, when `v` has its address taken, and when a label or `goto` it would remove is used from outside the body.

The rewrite keeps the program: every way of reaching the end of the body executed exactly one step before and
executes it, once, now; the statements the step moved past neither read nor write `v` (a call cannot change a local
whose address was never taken).
"""
import re

from .csource import _blank, find
from .goto_structure_repairs import IDENT, _gotos, parse, walk
from .pattern_repairs import close

FAMILIES = ('loop_step_fold',)
_STEP = re.compile(rf'(?P<v>{IDENT})\s*(?:\+=\s*(?P<a>\d+)|=\s*(?P=v)\s*\+\s*(?P<b>\d+)|(?P<inc>\+\+))\s*;')
_PREFIX_STEP = re.compile(rf'\+\+\s*(?P<v>{IDENT})\s*;')


def _step(clean, s):
    """(variable, increment text) when statement `s` is a plain step of a variable, else None."""
    if s.kind != 'simple':
        return None
    text = clean[s.start:s.end].strip()
    if m := _PREFIX_STEP.fullmatch(text):
        return m['v'], '1'
    if m := _STEP.fullmatch(text):
        return m['v'], m['a'] or m['b'] or '1'
    return None


def _mentions(clean, s, v):
    return re.search(rf'\b{re.escape(v)}\b', clean[s.start:s.end]) is not None


def _ends_the_path(clean, s):
    """A statement after which control never reaches the end of the loop body."""
    if s.kind == 'jump':
        return clean[s.start:s.end].lstrip().startswith('break')
    return s.kind == 'simple' and re.match(r'\s*return\b', clean[s.start:s.end]) is not None


def _fold(clean, stmts, v, k, found):
    """Plan the removal of the steps that close the path of `stmts`; False when some path would not be closed.

    `found` collects ('drop', stmt), ('goto', name) and ('label', name) entries."""
    if not stmts:
        return False
    last = stmts[-1]
    if _ends_the_path(clean, last):
        return not any(_step(clean, s) == (v, k) for s in stmts)
    if last.kind == 'goto':
        found.append(('goto', last))
        return True
    if last.kind == 'if':
        arms = [last.parts['then'], last.parts['other']]
        return all(arm is not None and _fold(clean, arm['stmts'], v, k, found) for arm in arms)
    # a step, then only statements that do not read it (a `L:` label right before it goes with it)
    for i in range(len(stmts) - 1, -1, -1):
        s = stmts[i]
        if _step(clean, s) == (v, k):
            after = stmts[i + 1:]
            if any(t.kind != 'simple' or _mentions(clean, t, v) for t in after):
                return False
            found.append(('drop', s))
            if i and stmts[i - 1].kind == 'label':
                found.append(('label', stmts[i - 1]))
            return True
        if s.kind != 'simple' or _mentions(clean, s, v):
            return False
    return False


def _line_span(source, start, end):
    """The statement's span, widened to its whole line when nothing else shares it."""
    line = source.rfind('\n', 0, start) + 1
    if source[line:start].strip():
        return start, end
    stop = end
    while stop < len(source) and source[stop] in ' \t':
        stop += 1
    if stop < len(source) and source[stop] == '\n':
        return line, stop + 1
    return start, end


def _loop_edits(source, clean, function, loop):
    head = loop.parts['cond']
    condition = clean[head[0]:head[1]].strip()
    if not (loop.kind == 'for' and re.fullmatch(r';\s*;', condition)
            or loop.kind == 'while' and condition in ('1', '(1)')):
        return []
    body = loop.parts['body']['stmts']
    inside = list(walk(body))
    if any(s.kind == 'jump' and not nested and clean[s.start:s.end].lstrip().startswith('continue')
           for s, nested in inside):
        return []
    steps = {step for s, _ in inside if (step := _step(clean, s))}
    out = []
    for v, k in sorted(steps):
        if re.search(rf'&\s*{re.escape(v)}\b', clean):
            continue
        found = []
        if not _fold(clean, body, v, k, found):
            continue
        labels = {s.parts['name'] for kind, s in found if kind == 'label'}
        gotos = [s for kind, s in found if kind == 'goto']
        if any(g.parts['target'] not in labels for g in gotos):
            continue
        if any(len(_gotos(function, name)) != sum(g.parts['target'] == name for g in gotos) for name in labels):
            continue
        if not [1 for kind, _ in found if kind == 'drop']:
            continue
        edits = [_line_span(source, s.start, s.end) + ('',) for kind, s in found if kind != 'label']
        edits += [_line_span(source, s.start, s.end) + ('',) for kind, s in found if kind == 'label']
        # the loop's own step, in its header
        text = f'for (;; {v} += {k})'
        edits.append((loop.start, close(clean, clean.index('(', loop.start)), text))
        edits = sorted(set(edits), reverse=True)
        result = source
        for a, b, rep in edits:
            result = result[:a] + rep + result[b:]
        out.append(('loop_step_fold', result))
    return out


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or re.search(r'\b(?:setjmp|longjmp|asm|__asm__)\b', clean[opening:end]):
        return []
    try:
        function = parse(clean, opening + 1, end - 1)
    except ValueError:
        return []
    result = []
    for s, _ in walk(function):
        if s.kind in ('for', 'while'):
            result += _loop_edits(source, clean, function, s)
    seen, out = set(), []
    for family, text in result:
        if text not in seen and text != source:
            seen.add(text)
            out.append((family, text))
    return out[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 93}  # the registry: no caller wiring (registry.py)
