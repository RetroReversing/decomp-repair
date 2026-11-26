"""A local stepped by a constant in a loop (`y = 0x37;` before it, `y += 0xE;` once per pass), written as a product of a
zero-based row counter (`y = row * 0xE + 0x37;` at the top of the body, `row++;` before the loop counter's step).

SN64 GCC 2.8.1 (`-G0 -mips3 -O2`, loop.c), a 258-instruction N64 menu that draws nine rows: the loop preheader held
the target's instructions with every register right except that `li $s0, 0x37` came second (after the counter's `sll`)
where the target has it last, after loop.c's reduced pointers. Read in the `-dL`/`-dS` dumps:

- A stepped local is a biv of its own; its initial `li` is an ordinary insn placed where the source sets it, before
  the guard's fall-through, so it precedes every giv initialisation that strength_reduce emits before `loop_start`.
  sched1 (2.8.1's sched.c, scheduling backwards) gives all those preheader insns priority 1, and the multi-set biv is
  no `birthing_insn_p`, so `rank_for_schedule` keeps the RTL order (INSN_LUID): the `li` stays at the top.
- Written as `y = row * K + C;` with a separate counter `row = 0; ... row++;`, `y` is a giv of `row`. `row` has no
  other use, so it is eliminated (`biv N can be eliminated`), and `y` is reduced to a new register whose
  initialisation `row0 * K + C` cse2 folds to the constant: one `li`, now emitted by strength_reduce. bivs are kept on
  `loop_iv_list` newest first (record_biv prepends), so the biv whose increment the scan meets last is reduced first:
  with `row++;` *before* the loop counter's step, the counter's pointers are emitted first and `y`'s `li` last, the
  target's order (60 -> 0). With `row++;` after the step the order flips (250).
- The reduced register's increment sits at `row++`, once per pass; reorg copies it into the delay slot of the `then`
  arm's jump, which is why the target shows `addiu $s0, $s0, 0xE` at the end of both arms of an `if`/`else`.

Offered when the local is set once to an integer literal before a `do { } while` or `for` loop (optionally inside a
`do { } while (0)` fence), is otherwise written only by `+= K` with one literal `K`, either one top-level statement of
the body or the last statement of each arm of one top-level `if`/`else` (a fence around it is allowed), is not read
after the step or after the loop, and its address is never taken; and the body has no `goto`, label, `continue` or
`return`, and no `break` of its own (one inside a `switch` or an inner loop leaves only that statement), so every pass
steps it exactly once. A three-row options menu whose body is a `switch` on the counter (SN64 GCC 2.8.1, `-G0 -mips3
-O2`) went 525 -> 205 this way with no do-while fence: `y = 0x50;` set where the source wrote it was floated to the top
of the entry block by sched1 (a multi-set biv with priority 1 and a later INSN_LUID than the hoisted address of the
table the arms update), where the target has the table's `lui` first and `y`'s `li` beside the cosine chain. Children: `row++;` before the counter's step;
`row++;` last in the body; `row = 0;` right before the loop where the literal was set further up; and, when the loop's
own counter is 0 on entry (its init or the last top-level write before the loop says so) and the body writes it only
by its step, `y = i * K + C;` with no row variable, at the top of the body and after the body's leading givs of the
counter (the options menu's second stepped local, a spilled `yoff = 0; ... yoff += 10`, went 85 -> 25 that way, after
`y = i * 10 + 0x50;`; first, 1465; through a row counter, 85).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'stepped_constant_row_giv'
FAMILIES = (FAMILY,)
LIMIT = 8

_IDENT = r'[A-Za-z_]\w*'
_INT = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'
_WORD = {'int', 's32', 'u32', 'signed int', 'unsigned int', 'unsigned', 'short', 's16', 'u16', 'long', 'signed'}
_CONTROL = re.compile(r'\b(?:goto|break|continue|return|switch|case|default)\b')
_LABEL = re.compile(r'(?:^|[;{}])\s*' + _IDENT + r'\s*:(?!:)')
_INNER = re.compile(r'\b(switch|for|while|do)\b\s*(?:\(|\{)')


def _own_control(clean, lo, hi):
    """clean[lo:hi] with the bodies of the switches and loops inside it blanked, after checking them: a `break` (or a
    switch's `case`/`default:`) in there leaves only that statement, and every pass still reaches the step after it.
    None when an inner part could leave the loop or skip the step (`goto`, `continue`, `return`, a label)."""
    out, at = [], lo
    while True:
        m = _INNER.search(clean, at, hi)
        if not m:
            break
        brace = clean.find('{', m.start(), hi)
        if m[1] != 'do':
            paren = clean.index('(', m.start())
            cond = close(clean, paren)
            if cond is None:
                return None
            brace = _skip(clean, cond, hi)
        if brace < 0 or brace >= hi or clean[brace] != '{':
            return None
        stop = close(clean, brace, '{', '}')
        if stop is None or stop > hi:
            return None
        inner = re.sub(r'\b(?:case\b[^:;{}]*|default\s*):(?!:)', ' ', clean[brace + 1:stop - 1]) if m[1] == 'switch' \
            else clean[brace + 1:stop - 1]
        if re.search(r'\b(?:goto|continue|return)\b', inner) or _LABEL.search(inner):
            return None
        if m[1] == 'do':
            tail = re.compile(r'\s*while\s*\([^;]*\)\s*;').match(clean, stop)
            if not tail or tail.end() > hi:
                return None
            stop = tail.end()
        out.append(clean[at:m.start()])
        out.append(' ' * (stop - m.start()))
        at = stop
    out.append(clean[at:hi])
    return ''.join(out)


def _skip(clean, at, end):
    while at < end and clean[at].isspace():
        at += 1
    return at


def _statements(clean, start, end):
    """(start, end) of each statement directly inside clean[start:end], or None for a shape this module does not read
    (an unbraced `if`/loop body, an unbalanced bracket)."""
    result, at = [], _skip(clean, start, end)
    while at < end:
        rest = clean[at:end]
        head = re.match(r'(if|for|while|switch)\s*\(', rest)
        if head:
            cond = close(clean, at + head.end() - 1)
            brace = _skip(clean, cond or end, end)
            if cond is None or brace >= end or clean[brace] != '{':
                return None
            stop = close(clean, brace, '{', '}')
            if stop is None:
                return None
            if head[1] == 'if':
                while True:
                    other = re.match(r'\s*else\s*', clean[stop:end])
                    if not other:
                        break
                    nxt = stop + other.end()
                    if re.match(r'if\s*\(', clean[nxt:end]):
                        cond = close(clean, nxt + clean[nxt:end].index('('))
                        nxt = _skip(clean, cond or end, end)
                    if nxt >= end or clean[nxt] != '{':
                        return None
                    stop = close(clean, nxt, '{', '}')
                    if stop is None:
                        return None
            result.append((at, stop))
        elif re.match(r'do\s*\{', rest):
            brace = clean.index('{', at)
            stop = close(clean, brace, '{', '}')
            tail = re.compile(r'\s*while\s*\([^;]*\)\s*;').match(clean, stop) if stop else None
            if not tail or tail.end() > end:
                return None
            result.append((at, tail.end()))
        elif clean[at] == '{':
            stop = close(clean, at, '{', '}')
            if stop is None:
                return None
            result.append((at, stop))
        else:
            depth, i = 0, at
            while i < end:
                c = clean[i]
                if c in '([{':
                    depth += 1
                elif c in ')]}':
                    depth -= 1
                elif c == ';' and depth == 0:
                    break
                i += 1
            if i >= end:
                return None
            result.append((at, i + 1))
        at = _skip(clean, result[-1][1], end)
    return result


def _unfence(text):
    """The statement inside `do { S; } while (0);`, or the text itself."""
    m = re.fullmatch(r'do\s*\{\s*([^{};]*;)\s*\}\s*while\s*\(\s*0\s*\)\s*;', text.strip())
    return m[1].strip() if m else text.strip()


def _step_of(text):
    m = re.fullmatch(r'(?:(' + _IDENT + r')\s*(?:\+\+|\+=\s*1)|\+\+\s*(' + _IDENT + r')|(' + _IDENT + r')\s*=\s*('
                     + _IDENT + r')\s*\+\s*1)\s*;', _unfence(text))
    if not m:
        return None
    if m[3] and m[3] != m[4]:
        return None
    return m[1] or m[2] or m[3]


def _loops(clean, lo, hi):
    """Each counted loop: (start, end, body_open, body_close, step) where `step` is the (start, end) of the do-while's
    last statement counting its condition's variable, or None for a `for` (whose step follows the body)."""
    found = []
    for m in re.finditer(r'\bdo\s*\{', clean[lo:hi]):
        brace = lo + m.end() - 1
        stop = close(clean, brace, '{', '}')
        tail = re.compile(r'\s*while\s*\(([^;]*)\)\s*;').match(clean, stop) if stop else None
        if not tail or re.fullmatch(r'\s*0\s*', tail[1]):
            continue
        statements = _statements(clean, brace + 1, stop - 1)
        if not statements:
            continue
        counter = _step_of(clean[statements[-1][0]:statements[-1][1]])
        if not counter or not re.search(r'\b' + counter + r'\b', tail[1]):
            continue
        found.append((lo + m.start(), tail.end(), brace, stop - 1, statements[-1], counter))
    for m in re.finditer(r'\bfor\s*\(', clean[lo:hi]):
        paren = lo + m.end() - 1
        cond = close(clean, paren)
        brace = _skip(clean, cond or hi, hi)
        if cond is None or brace >= hi or clean[brace] != '{':
            continue
        parts = clean[paren + 1:cond - 1].split(';')
        if len(parts) != 3:
            continue
        counter = _step_of(parts[2] + ';')
        if not counter:
            continue
        stop = close(clean, brace, '{', '}')
        found.append((lo + m.start(), stop, brace, stop - 1, None, counter))
    return found


def _line_start(text, at):
    return text.rfind('\n', 0, at) + 1


def _indent(text, at):
    line = _line_start(text, at)
    return re.match(r'[ \t]*', text[line:])[0]


def _remove(text, start, end):
    """The span of a whole statement with its line, when it stands alone on it."""
    line = _line_start(text, start)
    after = text.find('\n', end)
    if not text[line:start].strip() and (after < 0 or not text[end:after].strip()):
        return line, (after + 1 if after >= 0 else len(text))
    return start, end


def _increments(clean, statements, var):
    """[(start, end)] of the `var += K` statements and K, when every pass of the body steps `var` once, at its end."""
    step = re.compile(re.escape(var) + r'\s*\+=\s*(' + _INT + r')\s*;')
    top = [(s, e) for s, e in statements if step.fullmatch(_unfence(clean[s:e]))]
    if len(top) == 1:
        s, e = top[0]
        if any(re.search(r'\b' + re.escape(var) + r'\b', clean[a:b]) for a, b in statements if a >= e):
            return None
        return top, step.fullmatch(_unfence(clean[s:e]))[1]
    if top:
        return None
    for s, e in statements:
        if not re.match(r'if\s*\(', clean[s:e]) or not re.search(r'\b' + re.escape(var) + r'\s*\+=', clean[s:e]):
            continue
        cond = close(clean, s + clean[s:e].index('('))
        arms, at = [], _skip(clean, cond, e)
        while at < e:
            stop = close(clean, at, '{', '}')
            arms.append((at + 1, stop - 1))
            other = re.match(r'\s*else\s*(?:if\s*\([^{]*\)\s*)?', clean[stop:e])
            if not other:
                break
            at = _skip(clean, stop + other.end(), e)
            if re.match(r'if\s*\(', clean[stop + len(re.match(r'\s*else\s*', clean[stop:e])[0]):e]):
                return None  # an `else if` chain: keep to one if/else
        if len(arms) != 2:
            return None
        found, constant = [], None
        for a, b in arms:
            inner = _statements(clean, a, b)
            if not inner:
                return None
            last = step.fullmatch(_unfence(clean[inner[-1][0]:inner[-1][1]]))
            if not last or (constant is not None and int(last[1].rstrip('uUlL'), 0) != int(constant.rstrip('uUlL'), 0)):
                return None
            if re.search(r'\b' + re.escape(var) + r'\s*(?:[-+*/%&|^]?=(?!=)|\+\+|--)', clean[a:inner[-1][0]]):
                return None
            constant = last[1]
            found.append(inner[-1])
        if any(re.search(r'\b' + re.escape(var) + r'\b', clean[a:b]) for a, b in statements if a >= e):
            return None
        return found, constant
    return None


def _fresh(clean, base='row'):
    name, n = base, 2
    while re.search(r'\b' + name + r'\b', clean):
        name, n = f'{base}{n}', n + 1
    return name


def _zero_start(clean, opening, start, body_open, body_close, last, counter):
    """The loop counter is 0 on entry and written in the body only by its step: the loop's own init says
    `counter = 0`, or the last write before the loop is a top-level `counter = 0;`."""
    write = re.compile(r'(?<![\w.>])' + re.escape(counter) + r'\s*(?:[-+*/%&|^]?=(?!=)|\+\+|--)|(?:\+\+|--)\s*'
                       + re.escape(counter) + r'\b')
    body = clean[body_open + 1:body_close]
    if last is not None:
        body = clean[body_open + 1:last[0]] + ' ' * (last[1] - last[0]) + clean[last[1]:body_close]
    if write.search(body):
        return False
    head = re.match(r'for\s*\(([^;]*);', clean[start:body_open])
    if head and re.search(r'\b' + re.escape(counter) + r'\b', head[1]):
        return any(re.fullmatch(re.escape(counter) + r'\s*=\s*0[uUlL]*', item.strip()) for item in head[1].split(','))
    writes = list(write.finditer(clean, opening, start))
    if not writes:
        return False
    hit = writes[-1]
    zero = re.compile(re.escape(counter) + r'\s*=\s*0[uUlL]*\s*;').match(clean, hit.start())
    return bool(zero) and clean.count('{', opening, hit.start()) - clean.count('}', opening, hit.start()) == 1


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    results = []
    for start, stop, body_open, body_close, last, counter in _loops(clean, opening + 1, end - 1):
        body = clean[body_open + 1:body_close]
        own = _own_control(clean, body_open + 1, body_close)
        if own is None or _CONTROL.search(own) or _LABEL.search(own):
            continue
        statements = _statements(clean, body_open + 1, body_close)
        if not statements:
            continue
        for var in dict.fromkeys(re.findall(r'\b(' + _IDENT + r')\s*\+=\s*' + _INT + r'\s*;', body)):
            if var == counter:
                continue
            refs = [m.start() for m in re.finditer(r'(?<![\w.>])' + re.escape(var) + r'\b', clean[opening:end])]
            refs = [opening + r for r in refs]
            decl = re.search(r'(?:^|[;{}])\s*((?:unsigned\s+|signed\s+)?\w+)\s+' + re.escape(var) + r'\s*;',
                             clean[opening:end])
            if not decl or decl[1] not in _WORD or re.search(r'&\s*' + re.escape(var) + r'\b', clean[opening:end]):
                continue
            declared = opening + decl.end()
            outside = [r for r in refs if not (start <= r < stop) and r >= declared]
            if len(outside) != 1 or outside[0] > start:
                continue
            init = re.compile(re.escape(var) + r'\s*=\s*(' + _INT + r')\s*;').match(clean, outside[0])
            if not init:
                continue
            init_start, init_end = outside[0], init.end()
            wrap = re.search(r'do\s*\{\s*$', clean[max(opening, init_start - 40):init_start])
            tail = re.compile(r'\s*\}\s*while\s*\(\s*0\s*\)\s*;').match(clean, init_end)
            if wrap and tail:  # `do { y = 0x37; } while (0);`: the fence goes with it
                init_start, init_end = max(opening, init_start - 40) + wrap.start(), tail.end()
            steps = _increments(clean, statements, var)
            if not steps:
                continue
            places, stride = steps
            inside = [r for r in refs if start <= r < stop]
            if any(re.match(re.escape(var) + r'\s*(?:[-*/%&|^]?=(?!=)|\+\+|--)', clean[r:])
                   or re.search(r'(?:\+\+|--)\s*$', clean[r - 3:r]) for r in inside):
                continue
            row = _fresh(clean)
            body_indent = _indent(source, statements[0][0])
            common = [(a, b, '') for a, b in (_remove(source, a, b) for a, b in places)]
            common.append((statements[0][0], statements[0][0],
                           f'{var} = {row} * {stride} + {init[1]};\n' + body_indent))
            common.append((opening + 1, opening + 1, f'\n    s32 {row};'))
            tail_line = _line_start(source, body_close)
            at_end = (tail_line, tail_line, f'{body_indent}{row}++;\n')
            in_place = (init_start, init_end, f'{row} = 0;')
            moved = [(*_remove(source, init_start, init_end), ''),
                     (start, start, f'{row} = 0;\n' + _indent(source, start))]
            if last is None:  # a `for`: the end of the body comes before its step
                before = at_end
                choices = [[before, in_place]]
            else:
                before = (last[0], last[0], f'{row}++;\n' + _indent(source, last[0]))
                choices = [[before, in_place], [at_end, in_place]]
            if clean[init_end:start].strip():
                choices.append([before, *moved])
            edits = [common + extra for extra in choices]
            if _zero_start(clean, opening, start, body_open, body_close, last, counter):
                # the loop's own counter is the row: `y = i * K + C;`, no new variable (a three-row options menu,
                # SN64 GCC 2.8.1: a second stepped local as a giv of a row counter left it at 85, of `i` 85 -> 25)
                # at the top of the body, and after the body's leading givs of the counter when it has some (the
                # menu's second one went after `y = i * 10 + 0x50;`: before it, 1465)
                tops = [statements[0][0]]
                after = 0
                while after < len(statements) and re.fullmatch(
                        _IDENT + r'\s*=\s*' + re.escape(counter) + r'\s*\*\s*' + _INT + r'(?:\s*\+\s*' + _INT + r')?\s*;',
                        clean[statements[after][0]:statements[after][1]].strip()):
                    after += 1
                if 0 < after < len(statements):
                    tops.append(statements[after][0])
                for top in tops:
                    own = [(a, b, '') for a, b in (_remove(source, a, b) for a, b in places)]
                    value = f'{counter} * {stride}' + ('' if int(init[1].rstrip('uUlL'), 0) == 0 else f' + {init[1]}')
                    own.append((top, top, f'{var} = {value};\n' + body_indent))
                    own.append((*_remove(source, init_start, init_end), ''))
                    edits.append(own)
            for each in edits:
                text = source
                for a, b, new in sorted(each, key=lambda e: (e[0], e[1]), reverse=True):
                    text = text[:a] + new + text[b:]
                if text != source and (FAMILY, text) not in results:
                    results.append((FAMILY, text))
    return results[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
