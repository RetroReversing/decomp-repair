"""A `do`/`while`/`for` loop written as a backward `goto`, so gcc 2.7.2's loop pass leaves it alone.

gcc only runs loop.c (invariant hoisting, strength reduction) on the loops `while`, `do` and `for` mark with
NOTE_INSN_LOOP_BEG; a backward `goto` loop gets none of it. A 32-bit constant stored each iteration (`li` of a display
list word, then `sw`) is a loop invariant to loop.c: it is hoisted into a saved register before the loop, which grows
the frame by a register and moves the constants out of the body. A target whose body still builds the constant where it
stores it was written without a loop statement. Every `while`-shaped source stays at that frame however its statements
are ordered (a KMC 2.7.2 display-list function: 1554 as a `do`/`while` with the exact literals, exact once the same
body was `loop_N: ... if (c) goto loop_N;`).

This is the opposite of `goto_structure_repairs.goto_backward_loop` (a `goto` back to `do`/`while`); a deep pass that
keeps the better of the two scores both. Offered for one loop at a time:

- `do { B } while (c);`  ->  `L: { B } if (c) goto L;`
- `while (c) { B }`      ->  `L: if (c) { B goto L; }`
- `for (i; c; s) { B }`  ->  `i; L: if (c) { B s; goto L; }`

A `break` of the loop becomes `goto L_end;` (`L_end:;` follows the loop). A loop with a `continue`, or one holding
a label or a `case`, is left alone: the rewrite would change where they land.
"""
import re

from .csource import _blank, find
from .goto_structure_repairs import _indent_of, blocks, parse, walk
from .pattern_repairs import close

FAMILY = 'loop_goto_form'
FAMILIES = (FAMILY,)
KINDS = ('do', 'while', 'for')


def _fresh(source, stem):
    n = 1
    while re.search(r'\b' + stem + str(n) + r'\b', source):
        n += 1
    return f'{stem}{n}'


def _top_level_semicolons(text):
    parts, depth, last = [], 0, 0
    for i, ch in enumerate(text):
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
        elif ch == ';' and depth == 0:
            parts.append(text[last:i])
            last = i + 1
    parts.append(text[last:])
    return parts


def _breaks(body):
    """The `break` statements that leave this loop (not a nested loop or switch), or None for a `continue`/label/case."""
    found = []
    for s, nested in walk(body['stmts']):
        if s.kind == 'label' or (s.kind == 'case' and not nested):
            return None
        if s.kind == 'jump' and not nested:
            if s.parts.get('target') is None and s.end - s.start >= 5:
                found.append(s)
    return found


def _inner(source, clean, body):
    """Where the body's statements start and end in the source, without the braces."""
    start, end = (body['open'] + 1, body['close'] - 1) if body['block'] else (body['stmts'][0].start, body['stmts'][0].end)
    return start, end


def _variant(source, clean, s):
    body = s.parts['body']
    jumps = _breaks(body)
    if jumps is None:
        return None
    for j in jumps:
        if clean[j.start:j.end].strip().startswith('continue'):
            return None
    start, end = _inner(source, clean, body)
    label = _fresh(source, 'loop_goto_')
    done = _fresh(source, 'loop_goto_end_')
    text = source[start:end]
    for j in sorted(jumps, key=lambda j: -j.start):
        text = text[:j.start - start] + f'goto {done};' + text[j.end - start:]
    cond_text = source[s.parts['cond'][0]:s.parts['cond'][1]]
    indent = _indent_of(source, s.start)
    inner = text.strip('\n').rstrip() + '\n'
    if not body['block']:
        inner = f'{indent}    {text.strip()}\n'
    tail = f'{indent}{done}:;\n' if jumps else ''
    if s.kind == 'do':
        out = f'{label}:\n{indent}{{\n{inner}{indent}}}\n{indent}if ({cond_text.strip()})\n{indent}{{\n{indent}    goto {label};\n{indent}}}\n{tail}'
    else:
        step = ''
        init = ''
        cond = cond_text.strip()
        if s.kind == 'for':
            pieces = _top_level_semicolons(cond_text)
            if len(pieces) != 3:
                return None
            init, cond, step = (p.strip() for p in pieces)
            cond = cond or '1'
            if init:
                init = f'{init};\n{indent}'
            if step:
                step = f'{indent}    {step};\n'
        out = (f'{init}{label}:\n{indent}if ({cond})\n{indent}{{\n{inner}{step}{indent}    goto {label};\n{indent}}}\n{tail}')
    first = source.rfind('\n', 0, s.start) + 1
    lead = source[first:s.start]
    head = source[:s.start] if lead.strip() else source[:first] + lead
    rest = source[s.end:]
    rest = rest[1:] if rest.startswith('\n') else rest
    return head + out + rest


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    if not re.search(r'\b(do|while|for)\b', body):
        return []
    try:
        function = parse(clean, opening + 1, end - 1)
    except ValueError:
        return []
    found = []
    for stmts in blocks(function):
        for s in stmts:
            if s.kind in KINDS:
                text = _variant(source, clean, s)
                if text and text != source:
                    found.append((FAMILY, text))
    return found[:6]
