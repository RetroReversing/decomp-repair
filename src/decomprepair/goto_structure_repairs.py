"""m2c's backward and forward `goto`s written as the loops and `else`s they came from.

m2c recovers the loops and branches it can and leaves the rest as labels and `goto`s. gcc 2.7.2 only applies its loop
optimisations (invariants hoisted, induction variables strength-reduced) to the loops the C writes, from the
NOTE_INSN_LOOP_BEG notes `while`, `do` and `for` leave, never to a backward `goto`, and lays out an `if`/`else`
differently from a jump over a block. So a draft with `loop_2:` ... `if (i < 4) { goto loop_2; }` or with
`if (c) { x; goto block_5; } y; block_5:` stays off by its loop or branch layout however its statements are permuted.

Each rewrite keeps the meaning: only labels every `goto` of which lies in the rewritten region, no `break` or
`continue` whose loop would change, and no `goto` whose target would move into or out of a loop.

- `goto_backward_loop`: `L: S...; if (c) { goto L; }` becomes `do { S... } while (c);`; `L: if (c) { T...; goto L; }`
  becomes `while (c) { T... }`; any other region from `L:` to its last `goto L;` becomes `for (;;) { ... break; }` with
  `goto L;` as `continue;`, and, when the region ends with `if (c) { T...; goto L; }`, also
  `for (;;) { S...; if (!c) break; T... }`.
- `goto_forward_else`: `if (c) { T...; goto B; } M... B: R...` (the only `goto B`) becomes
  `if (c) { T... } else { M... } R...`, or `if (!c) { M... }` when T is empty.
- `goto_shared_tail`: a `goto` into the tail of another arm or case (m2c merged two copies of the same statements)
  gets its own copy of the tail, when the tail ends in `return` or the `goto` is the last thing its path does before
  the `if` holding the label ends.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILIES = ('goto_backward_loop', 'goto_forward_else', 'goto_shared_tail')
IDENT = r'[A-Za-z_]\w*'
LOOPS = ('do', 'while', 'for', 'switch')


class Stmt:
    """A statement of a block: kind, its span in the source, and for compound statements their parts."""

    def __init__(self, kind, start, end, **parts):
        self.kind, self.start, self.end, self.parts = kind, start, end, parts

    def __repr__(self):
        return f'Stmt({self.kind}, {self.start}, {self.end})'


def _skip(text, i, end):
    while i < end and text[i] in ' \t\r\n':
        i += 1
    return i


def _simple_end(text, i, end):
    depth = 0
    while i < end:
        ch = text[i]
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
            if depth < 0:
                return None
        elif ch == ';' and depth == 0:
            return i + 1
        i += 1
    return None


def _body(text, i, end):
    """A block or single statement after a condition: (Stmt-ish dict, end)."""
    i = _skip(text, i, end)
    if i < end and text[i] == '{':
        close_at = close(text, i, '{', '}')
        if not close_at or close_at > end:
            return None
        return {'block': True, 'open': i, 'close': close_at, 'stmts': parse(text, i + 1, close_at - 1)}, close_at
    one = statement(text, i, end)
    if one is None:
        return None
    return {'block': False, 'open': one.start, 'close': one.end, 'stmts': [one]}, one.end


def statement(text, i, end):
    i = _skip(text, i, end)
    if i >= end:
        return None
    rest = text[i:end]
    if m := re.match(r'(case\b[^:\n]*|default)\s*:(?!:)', rest):
        return Stmt('case', i, i + m.end())
    if (m := re.match(r'(' + IDENT + r')\s*:(?!:)', rest)) and m[1] not in ('default',):
        return Stmt('label', i, i + m.end(), name=m[1])
    if m := re.match(r'if\s*\(', rest):
        cond_open = i + m.end() - 1
        cond_close = close(text, cond_open)
        if not cond_close:
            return None
        then = _body(text, cond_close, end)
        if not then:
            return None
        then, after = then
        j = _skip(text, after, end)
        other = None
        if re.match(r'else\b', text[j:end]):
            other = _body(text, j + 4, end)
            if not other:
                return None
            other, after = other
        return Stmt('if', i, after, cond=(cond_open + 1, cond_close - 1), then=then, other=other)
    if m := re.match(r'do\b', rest):
        body = _body(text, i + m.end(), end)
        if not body:
            return None
        body, after = body
        tail = re.match(r'\s*while\s*\(', text[after:end])
        if not tail:
            return None
        cond_open = after + tail.end() - 1
        cond_close = close(text, cond_open)
        semi = re.match(r'\s*;', text[cond_close:end]) if cond_close else None
        if not semi:
            return None
        return Stmt('do', i, cond_close + semi.end(), body=body, cond=(cond_open + 1, cond_close - 1))
    if m := re.match(r'(while|for|switch)\s*\(', rest):
        cond_open = i + m.end() - 1
        cond_close = close(text, cond_open)
        if not cond_close:
            return None
        body = _body(text, cond_close, end)
        if not body:
            return None
        body, after = body
        return Stmt(m[1], i, after, body=body, cond=(cond_open + 1, cond_close - 1))
    if rest[0] == '{':
        close_at = close(text, i, '{', '}')
        if not close_at:
            return None
        return Stmt('block', i, close_at, body={'block': True, 'open': i, 'close': close_at,
                                                  'stmts': parse(text, i + 1, close_at - 1)})
    stop = _simple_end(text, i, end)
    if stop is None:
        return None
    kind = 'goto' if re.match(r'goto\b', rest) else 'jump' if re.match(r'(break|continue)\s*;', rest) else 'simple'
    target = re.match(r'goto\s+(' + IDENT + r')', rest)
    return Stmt(kind, i, stop, target=target[1] if target else None)


def parse(text, start, end):
    stmts, i = [], start
    while True:
        i = _skip(text, i, end)
        if i >= end:
            return stmts
        s = statement(text, i, end)
        if s is None:
            raise ValueError('unparsed')
        stmts.append(s)
        i = s.end


def _children(s):
    for key in ('then', 'other', 'body'):
        part = s.parts.get(key)
        if part:
            yield part


def walk(stmts, inside_loop=False):
    """Every statement with whether it is inside a loop or switch nested in `stmts`."""
    for s in stmts:
        yield s, inside_loop
        for part in _children(s):
            yield from walk(part['stmts'], inside_loop or s.kind in LOOPS)


def blocks(stmts):
    """Every statement list in the tree, outermost first."""
    yield stmts
    for s in stmts:
        for part in _children(s):
            yield from blocks(part['stmts'])


def _gotos(stmts, name):
    return [(s, loop) for s, loop in walk(stmts) if s.kind == 'goto' and s.parts.get('target') == name]


def _labels(stmts):
    return [s for s, _ in walk(stmts) if s.kind == 'label']


def _free_jumps(stmts):
    return any(s.kind == 'jump' and not loop for s, loop in walk(stmts))


def _not(cond):
    return negate(cond.strip()) or f'!({cond.strip()})'


def _indent_of(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:])[0]


def _lines(text, indent):
    """`text` re-indented one level under `indent` (relative indentation kept)."""
    rows = [r for r in text.split('\n')]
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    if not rows:
        return ''
    # (the region's text starts mid-line, at its first statement: the other lines carry its indentation)
    rows[0] = rows[0].lstrip()
    base = min((len(r) - len(r.lstrip()) for r in rows[1:] if r.strip() and not re.match(r'\s*' + IDENT + r':\s*$', r)),
               default=0)
    rows = [rows[0]] + rows[1:]
    out = []
    for r in rows:
        if re.match(r'\s*' + IDENT + r':\s*$', r) and not re.match(r'\s*default:', r):
            out.append(r.strip() + '\n')  # labels stay at the margin, as m2c writes them
        else:
            text = r.lstrip() if r is rows[0] else r[base:]
            out.append(indent + '    ' + text.rstrip() + '\n' if r.strip() else '\n')
    return ''.join(out)


def _span(source, start, end):
    """source[start:end], from the start of its first line when only indentation comes before it there."""
    line = source.rfind('\n', 0, start) + 1
    return source[line if not source[line:start].strip() else start:end]


def _replace_gotos(source, start, end, name, by):
    return re.sub(r'\bgoto\s+' + re.escape(name) + r'\s*;', by, _span(source, start, end))


def _loop_variants(source, clean, function, label_list, i, name):
    label = label_list[i]
    gotos = _gotos(function, name)
    region_idx = [k for k in range(i + 1, len(label_list))
                  if any(g.start >= label_list[k].start and g.end <= label_list[k].end for g, _ in gotos)]
    if not region_idx:
        return []
    j = region_idx[-1]
    region = label_list[i + 1:j + 1]
    inside = [(g, loop) for g, loop in _gotos(region, name)]
    if len(inside) != len(gotos) or any(loop for _, loop in inside):
        return []  # a goto from outside, or one a nested loop would turn into its own continue
    if _free_jumps(region) or any(st.kind == 'case' for st, _ in walk(region)):
        return []  # (a switch's case inside the region would be entered from outside the new loop)
    # a label inside the region that something outside jumps to would be entered mid-loop
    for inner in _labels(region):
        if len(_gotos(region, inner.parts['name'])) != len(_gotos(function, inner.parts['name'])):
            return []
    indent = _indent_of(source, label.start)
    if indent == '' and region:
        indent = _indent_of(source, region[0].start)
    start, end = label.start, region[-1].end
    line_start = source.rfind('\n', 0, start) + 1
    if source[line_start:start].strip():
        line_start = start  # (statements before the label on its line stay where they are)
    head = source[:line_start]
    tail = source[end:]
    found = []

    def emit(text):
        rest = tail[1:] if tail.startswith('\n') else tail
        found.append(('goto_backward_loop', head + text + rest))

    last = region[-1]
    then = last.parts.get('then') if last.kind == 'if' else None
    cond = source[last.parts['cond'][0]:last.parts['cond'][1]].strip() if last.kind == 'if' else None
    simple_tail = (last.kind == 'if' and last.parts.get('other') is None and then['stmts']
                   and then['stmts'][-1].kind == 'goto' and then['stmts'][-1].parts['target'] == name)
    prefix = _span(source, region[0].start, last.start) if len(region) > 1 else ''
    if simple_tail:
        inner = then['stmts'][:-1]
        if not inner and len(inside) == 1:
            emit(f'{indent}do {{\n{_lines(prefix, indent)}{indent}}} while ({cond});\n')
        if not prefix.strip() and inner:
            text = _replace_gotos(source, inner[0].start, inner[-1].end, name, 'continue;')
            emit(f'{indent}while ({cond}) {{\n{_lines(text, indent)}{indent}}}\n')
        if inner or prefix.strip():
            pre = _replace_gotos(source, region[0].start, last.start, name, 'continue;') if prefix.strip() else ''
            mid = _replace_gotos(source, inner[0].start, inner[-1].end, name, 'continue;') if inner else ''
            emit(f'{indent}for (;;) {{\n{_lines(pre, indent)}{indent}    if ({_not(cond)}) {{\n{indent}        break;\n'
                 f'{indent}    }}\n{_lines(mid, indent)}{indent}}}\n')
    generic = _replace_gotos(source, region[0].start, region[-1].end, name, 'continue;')
    emit(f'{indent}for (;;) {{\n{_lines(generic, indent)}{indent}    break;\n{indent}}}\n')
    return found


def _else_variants(source, function, label_list, i):
    s = label_list[i]
    if s.kind != 'if' or s.parts.get('other') is not None:
        return []
    then = s.parts['then']
    if not then['block'] or not then['stmts'] or then['stmts'][-1].kind != 'goto':
        return []
    name = then['stmts'][-1].parts['target']
    k = next((k for k in range(i + 1, len(label_list))
              if label_list[k].kind == 'label' and label_list[k].parts['name'] == name), None)
    if len(_gotos(function, name)) != 1:
        return []
    if k is None:
        return _into_later_arm(source, function, label_list, i, name)
    middle = label_list[i + 1:k]
    if any(st.kind in ('case', 'jump') for st, _ in walk(middle)):
        return []  # (a case would move inside the if; a break of the switch is fine where it is)
    if not middle or _labels(middle) and any(len(_gotos(middle, lab.parts['name'])) != len(_gotos(function, lab.parts['name']))
                                             for lab in _labels(middle)):
        return []
    indent = _indent_of(source, s.start)
    cond = source[s.parts['cond'][0]:s.parts['cond'][1]].strip()
    inner = then['stmts'][:-1]
    mid = _span(source, middle[0].start, middle[-1].end)
    label = label_list[k]
    head = source[:s.start]
    tail = source[label.end:]
    tail = tail[1:] if tail.startswith('\n') else tail
    if inner:
        text = _span(source, inner[0].start, inner[-1].end)
        out = f'if ({cond}) {{\n{_lines(text, indent)}{indent}}} else {{\n{_lines(mid, indent)}{indent}}}\n'
    else:
        out = f'if ({_not(cond)}) {{\n{_lines(mid, indent)}{indent}}}\n'
    return [('goto_forward_else', head + out + tail)]


def _paths(stmts, trail=()):
    """Each statement with its trail of (statement list, index, owner) from the function's body down."""
    for k, st in enumerate(stmts):
        here = trail + ((stmts, k, None),)
        yield st, here
        for part in _children(st):
            yield from _paths(part['stmts'], here[:-1] + ((stmts, k, st),))


def _continuation(source, trail):
    """What runs after the statement a trail ends at: the rest of each enclosing list, outwards, as text, up to the
    nearest enclosing loop or switch (named by its position) or the function's end."""
    rest = []
    for depth in range(len(trail) - 1, -1, -1):
        stmts, idx, _ = trail[depth]
        rest += [' '.join(source[st.start:st.end].split()) for st in stmts[idx + 1:]]
        owner = trail[depth - 1][2] if depth else None
        if owner is not None and owner.kind in LOOPS:
            rest.append(f'<{owner.kind} at {owner.start}>')
            break
    return rest


def _breakable(trail):
    """The innermost loop or switch a trail's statement is in (what its `break` leaves), or None."""
    for _, _, owner in reversed(trail):
        if owner is not None and owner.kind in LOOPS:
            return owner
    return None


def _case_exit(source, trail, tail):
    """A single store whose next executable statement exits its switch by goto."""
    switch = _breakable(trail)
    if switch is None or switch.kind != 'switch' or len(tail) != 1 or tail[0].kind != 'simple':
        return None
    store = _blank(source[tail[0].start:tail[0].end]).strip()
    if not re.fullmatch(r'(?:' + IDENT + r'|\([^;]+\))\s*=(?!=)\s*[^;]+;', store):
        return None
    after = _continuation(source, trail[:-1] + ((trail[-1][0], trail[-1][1] + 1, None),))
    if not after or not re.fullmatch(r'goto\s+' + IDENT + r'\s*;', after[0]):
        return None
    return switch, store, after[0]


def _case_scope_allows_copy(source, trail, switch, store):
    # Nested declarations can shadow a name used by the store. Ignore the function's outer
    # declarations and inspect each intervening lexical block up to the switch.
    names = set(re.findall(IDENT, store))
    declaration = re.compile(r'\s*' + IDENT + r'(?:\s+|\s*\*\s*)' + IDENT)

    def may_shadow(stmt):
        text = _blank(source[stmt.start:stmt.end])
        return declaration.match(text) and names.intersection(re.findall(IDENT, text))

    for depth in range(len(trail) - 1, 0, -1):
        stmts, index, _ = trail[depth]
        if any(st.kind == 'simple' and may_shadow(st)
               for st in stmts[:index]):
            return False
        if trail[depth - 1][2] is switch:
            return True
    return False


def _tail_variants(source, function):
    found = []
    trails = {id(st): trail for st, trail in _paths(function)}
    for label, trail in _paths(function):
        if label.kind != 'label':
            continue
        stmts, k, _ = trail[-1]
        tail = stmts[k + 1:]
        # (in a switch the case labels share the list: the tail is the label's own case, up to its `break;` or `return`)
        cut = next((n for n, st in enumerate(tail)
                    if (st.kind == 'jump' and source[st.start:st.end].lstrip().startswith('break')
                        or st.kind == 'simple' and re.match(r'return\b', source[st.start:st.end].lstrip()))
                    and (n + 1 == len(tail) or tail[n + 1].kind == 'case')), None)
        if cut is not None and _breakable(trail) is not None and _breakable(trail).kind == 'switch':
            tail = tail[:cut + 1]
        gotos = _gotos(function, label.parts['name'])
        # (copying statements binds no break or continue, so a goto inside a switch or loop may take a copy; a tail
        # ending in `break;` may be copied too where every goto leaves the same loop or switch as the label: m2c's
        # `case A: v = x * 2; L: r = v + K; break; case B: v = y * 2; goto L;` was a switch whose cases each ended so,
        # gcc having merged the copies; written out again an N64 function was exact)
        case_exit = _case_exit(source, trail, tail)
        if case_exit:
            switch, store, jump = case_exit
            sites = [trail, *(trails[id(goto)] for goto, _ in gotos)]
            if (jump[4:].strip().removesuffix(';').strip() == label.parts['name']
                or any(_breakable(site) is not switch or not _case_scope_allows_copy(source, site, switch, store)
                       for site in sites)):
                case_exit = None
        breaks = bool(tail) and tail[-1].kind == 'jump' and source[tail[-1].start:tail[-1].end].lstrip().startswith('break')
        body = tail[:-1] if breaks else tail
        if not tail or not gotos or _labels(tail) \
                or any(st.kind in ('case', 'goto', 'jump') or st.kind in LOOPS for st, _ in walk(body)):
            continue
        if breaks and any(_breakable(trails[id(goto)]) is not _breakable(trail) for goto, _ in gotos):
            continue
        ends = case_exit or breaks or tail[-1].kind == 'simple' and re.match(r'return\b', source[tail[-1].start:tail[-1].end])
        # without a return, each goto must continue as the tail's end does: the same statements follow, level by
        # level, out to the same enclosing loop or switch (or the function's end)
        after_tail = _continuation(source, trail[:-1] + ((stmts, len(stmts) - 1, None),))
        if not ends and any(_continuation(source, trails[id(goto)]) != after_tail for goto, _ in gotos):
            continue
        text = _span(source, tail[0].start, tail[-1].end)
        out = source
        line = source.rfind('\n', 0, label.start) + 1
        if source[line:label.start].strip():
            line = label.start
        drop_end = label.end + (1 if source[label.end:label.end + 1] == '\n' else 0)
        edits = [(line, drop_end, '')]
        for goto, _ in gotos:
            indent = _indent_of(source, goto.start)
            copy = _lines(text, indent[:-4] if len(indent) >= 4 else '')
            replacement = copy.strip('\n').lstrip()
            if case_exit:
                # Copy the terminating jump as well, so the new site cannot fall
                # through into its own case continuation.
                replacement = '{ ' + replacement + ' ' + case_exit[2] + ' }'
            edits.append((goto.start, goto.end, replacement))
        for a, b, rep in sorted(edits, reverse=True):
            out = out[:a] + rep + out[b:]
        found.append(('goto_shared_tail', out))
    return found


def _into_later_arm(source, function, stmts, i, name):
    """`if (c) { T...; goto B; } M... if (d) { ... B: R... }` as `if (c) { T... R... } else { M... if (d) { ... R... } }`:
    after the later `if`, both ways go on to the same statements."""
    s = stmts[i]
    for k in range(i + 1, len(stmts)):
        later = stmts[k]
        if later.kind != 'if':
            continue
        for part in (later.parts['then'], later.parts.get('other')):
            if not part or not part['block']:
                continue
            arm = part['stmts']
            at = next((n for n, st in enumerate(arm) if st.kind == 'label' and st.parts['name'] == name), None)
            if at is None:
                continue
            tail, middle = arm[at + 1:], stmts[i + 1:k]
            if not tail or _labels(tail) or _labels(middle) \
                    or any(st.kind in ('case', 'goto', 'jump') or st.kind in LOOPS for st, _ in walk(tail + middle)):
                return []
            indent = _indent_of(source, s.start)
            cond = source[s.parts['cond'][0]:s.parts['cond'][1]].strip()
            inner = s.parts['then']['stmts'][:-1]
            label = arm[at]
            line = source.rfind('\n', 0, label.start) + 1
            if source[line:label.start].strip():
                line = label.start
            drop_end = label.end + (1 if source[label.end:label.end + 1] == '\n' else 0)
            rest = _span(source, stmts[i + 1].start, line) + source[drop_end:later.end]
            then_text = (_span(source, inner[0].start, inner[-1].end) + '\n' if inner else '') \
                + _span(source, tail[0].start, tail[-1].end)
            out = f'if ({cond}) {{\n{_lines(then_text, indent)}{indent}}} else {{\n{_lines(rest, indent)}{indent}}}'
            return [('goto_forward_else', source[:s.start] + out + source[later.end:])]
        return []
    return []


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or 'goto' not in clean[opening:end]:
        return []
    try:
        function = parse(clean, opening + 1, end - 1)
    except ValueError:
        return []
    result = []
    for stmts in blocks(function):
        for i, s in enumerate(stmts):
            if s.kind == 'label':
                result += _loop_variants(source, clean, function, stmts, i, s.parts['name'])
            elif s.kind == 'if':
                result += _else_variants(source, function, stmts, i)
    result += _tail_variants(source, function)
    seen, out = set(), []
    for family, text in result:
        if text not in seen and text != source:
            seen.add(text)
            out.append((family, text))
    return out[:8]
