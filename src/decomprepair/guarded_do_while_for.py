"""m2c's guarded `do { } while` with the code after it copied into the guard's `else`, written as the `for` it was.

    i = 0; ... if (n != 0) { off = 0; do { BODY i += 1; off += 0x1A0; } while (i < n); r = 0; } else { r = 0; }
 -> ... off = 0; for (i = 0; i < n; i++, off += 0x1A0) { BODY } r = 0;

GCC 2.x compiles `for (i = 0; i < n; i++)` as a test at the top and the loop at the bottom; m2c reads that back as an
`if` around a `do`/`while` and copies what follows the loop into both ways out. Written that way the copies are two
blocks that cross-jumping merges with other arms' tails in another order, and the loop pass sees a loop whose
entry test it did not make. On a 1315-instruction KMC GCC 2.7.2 sound-sequence interpreter (`-G0 -mips3 -mgp32
-mfp32 -O2`) the `for` took 8280 -> 6141.

`guarded_do_while_for`
    `if (N != 0)` (or `N > 0`, `0 < N`) whose block is `[J = A;] do { BODY I += 1; [J += K;] } while (I < N); TAIL`
    (`I++` / `++I` too), with an `else` whose block is `TAIL` (optionally followed by `break;`) or no `else` when
    `TAIL` is empty, `I = 0;` earlier in the same block with no use of `I` in between, and no `continue` in `BODY`:
    `[J = A;] for (I = 0; I < N; I++[, J += K]) { BODY } TAIL`. The judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'guarded_do_while_for'
FAMILIES = (FAMILY,)


def _norm(text):
    return re.sub(r'\s+', '', text)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    results = []
    guard = r'\bif\s*\(\s*(?:(' + IDENT + r')\s*(?:!=\s*0[uU]?|>\s*0)|0\s*<\s*(' + IDENT + r'))\s*\)\s*\{'
    for hit in re.finditer(guard, clean[part.opening:part.end]):
        start = part.opening + hit.start()
        bound = hit[1] or hit[2]
        opening = part.opening + hit.end() - 1
        block_end = close(clean, opening, '{', '}')
        if not block_end:
            continue
        inside = clean[opening + 1:block_end - 1]
        loop = re.match(r'\s*(?:(' + IDENT + r')\s*=\s*([^;]+);\s*)?do\s*\{', inside)
        if not loop:
            continue
        do_open = opening + 1 + loop.end() - 1
        do_close = close(clean, do_open, '{', '}')
        if not do_close:
            continue
        cond = re.compile(r'\s*while\s*\(\s*(' + IDENT + r')\s*<\s*' + re.escape(bound) + r'\s*\)\s*;').match(clean, do_close)
        if not cond:
            continue
        counter = cond[1]
        body = clean[do_open + 1:do_close - 1]
        steps = r'(?:\s*(?:' + re.escape(counter) + r'\s*\+=\s*1|' + re.escape(counter) + r'\s*\+\+|\+\+\s*' + re.escape(counter) + r')\s*;)'
        second = loop[1]
        tail_steps = re.search(steps + (r'(?:\s*' + re.escape(second) + r'\s*\+=\s*(' + NUMBER + r')\s*;)?' if second else '')
                               + r'\s*$', body)
        if not tail_steps or re.search(r'\bcontinue\b', body):
            continue
        stride = tail_steps.group(1) if second and tail_steps.lastindex else None
        if second and not stride:
            continue
        loop_body = source[do_open + 1:do_open + 1 + tail_steps.start()]
        if re.search(r'\b' + re.escape(counter) + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + re.escape(counter),
                     clean[do_open + 1:do_open + 1 + tail_steps.start()]):
            continue
        tail = source[cond.end():block_end - 1]
        rest = block_end
        otherwise = re.compile(r'\s*else\s*\{').match(clean, rest)
        statement_end = rest
        if otherwise:
            else_open = otherwise.end() - 1
            else_close = close(clean, else_open, '{', '}')
            if not else_close:
                continue
            other = clean[else_open + 1:else_close - 1]
            other = re.sub(r'\bbreak\s*;\s*$', '', other.rstrip())
            if _norm(other) != _norm(clean[cond.end():block_end - 1]):
                continue
            statement_end = else_close
        elif _norm(tail):
            continue
        # `I = 0;` earlier in the enclosing code, with no use of `I` between it and the guard
        before = clean[part.opening + 1:start]
        init = None
        for found in re.finditer(r'\b' + re.escape(counter) + r'\s*=\s*0\s*;', before):
            init = found
        if not init or re.search(r'\b' + re.escape(counter) + r'\b', before[init.end():]):
            continue
        init_start = part.opening + 1 + init.start()
        init_end = part.opening + 1 + init.end()
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:]).group(0)
        update = f'{counter}++' + (f', {second} += {stride}' if second else '')
        lines = []
        if second:
            lines.append(f'{second} = {loop[2].strip()};\n{indent}')
        lines.append(f'for ({counter} = 0; {counter} < {bound}; {update})\n{indent}{{')
        lines.append(_reindent(loop_body, indent + '  '))
        lines.append(f'{indent}}}')
        text = ''.join(lines[:1]) + '\n'.join(lines[1:]) if second else '\n'.join(lines)
        if tail.strip():
            text += '\n' + _reindent(tail, indent)
        edits = [(start, statement_end, text)]
        line_start = source.rfind('\n', 0, init_start) + 1
        line_end = source.find('\n', init_end)
        if not source[line_start:init_start].strip() and not source[init_end:line_end].strip():
            edits.append((line_start, line_end + 1, ''))
        else:
            edits.append((init_start, init_end, ''))
        results.append((FAMILY, edit(source, edits)))
    return results


def _reindent(text, indent):
    lines = [line.rstrip() for line in text.split('\n')]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    width = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
    return '\n'.join(indent + line[width:] if line.strip() else '' for line in lines)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
