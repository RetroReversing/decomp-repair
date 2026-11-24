"""A reduced induction variable written back as the counter's multiple, and the `goto` chain that stepped it as a `switch`.

GCC's loop pass strength-reduces `base + i * K` into a variable that starts at `base` and steps by K once per
iteration, and it writes that variable's starting value just before the loop label, after the loop invariants it
hoisted. An explicit `y = 0x50; ... y += 10;` in the source is a different program to the compiler: its start sits
before the hoisted invariants, where the target has it after them. m2c reads the target's reduced variable as just that:

    var_s0 = 0;
    if (D > 0) {
        var_s1 = 0x50;
        do {
            use(0xA0, var_s1);
            if (var_s0 != 1) {                         /* a switch (var_s0) the compiler made a compare chain of */
                if (var_s0 < 2) { var_a0 = 0xA4; if (var_s0 != 0) { var_s1 += 0xA; } else { goto block_11; } }
                else            { var_a0 = 0xA7; if (var_s0 != 2) { var_s1 += 0xA; } else { goto block_11; } }
            } else { var_a0 = 0xA6; block_11: var_s1 += 0xA; shown(var_a0); }
            var_s0 += 1;
        } while (var_s0 < D);
    }

The three `var_s1 += 0xA` are one increment of the original: the delay-slot filler copied it into each jump's slot and
m2c read the copies back as three statements. Written the way the game's author did (a `for` over the counter, the
variable computed where it is used, a `switch` for the chain) the function went from 60 to byte-identical (KMC GCC
2.7.2, `-G0 -mips3 -O2`, 111 instructions):

    for (var_s0 = 0; var_s0 < D; var_s0++) {
        use(0xA0, var_s0 * 10 + 0x50);
        switch (var_s0) { case 0: shown(0xA4); break; case 1: shown(0xA6); break; case 2: shown(0xA7); break; }
    }

The module offers the steps that only pay off together as one child, and its parts alone:
- `induction_reverse_reduction`: for a `do { ... i += 1; } while (i < E)` whose counter starts at 0, a variable that
  starts at a literal before the loop and is stepped by one literal exactly once per iteration (a single statement, or
  several copies on the paths of a `goto` chain, counted by running the chain on every counter value that matters) and
  read only before its first step, written as `i * K + C0` at its uses. The loop is written as the `for` it was when
  the guard before it is the loop's own entry test (`if (E > 0)`, or a flag set to it); the chain after the uses as a
  `switch (i)` when every path only calls with constants or flags it set. Children: all of it, the reduction with the
  `do` loop kept, and the reduction with the `for` but not the `switch`, in each spelling of the chain that applies.
- `dispatch_goto_switch`: the same chain read as a `switch` on the counter where nothing needs reducing.

Left alone: a loop with a `break`, `continue` or `return` in its body, a counter that does not start at 0 or step by 1,
a reduced variable read after its step or after the loop, chains that test anything but the counter against literals,
more than 16 cases. Whether a chain reads as a `switch` is decided by running it, not by its shape; a path that steps
the variable twice or never is not one iteration of a reduction and the module offers nothing for it.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'induction_reverse_reduction'
SWITCH_FAMILY = 'dispatch_goto_switch'
FAMILIES = (FAMILY, SWITCH_FAMILY)
MAX_CASES = 16
MAX_STEPS = 400
MAX_CHILDREN = 8
_OPAQUE = ('while', 'for', 'switch', 'do')
_STOP = ('return', 'break', 'continue', 'case', 'default')
_ASSIGN = re.compile(rf'^(?P<v>{IDENT})\s*=\s*(?P<lit>-?{NUMBER})\s*;$')
_STEP = re.compile(rf'^(?P<v>{IDENT})\s*\+=\s*(?P<k>{NUMBER})\s*;$')
_COMPARE = re.compile(rf'^\(*\s*(?P<x>{IDENT})\s*(?P<op>==|!=|<=|>=|<|>)\s*(?P<lit>-?{NUMBER})\s*\)*$')
_DECLARATION = re.compile(rf'^(?:{IDENT}[ \t*]+)+{IDENT}\s*;$')
_CALL = re.compile(rf'^{IDENT}\s*\(.*\)\s*;$', re.S)


class Bail(Exception):
    """The span is not one this module reads."""


def _number(text):
    return int(re.sub(r'[uUlL]+$', '', text), 0)


# ---- a small statement reader for the loop body (if / else / goto / label / blocks; loops and switches are opaque) ----

def _skip(clean, pos, end):
    while pos < end and clean[pos].isspace():
        pos += 1
    return pos


def _statement(clean, pos, end):
    """(node, position after it); a node is (kind, start, stop, ...)."""
    pos = _skip(clean, pos, end)
    if pos >= end:
        raise Bail
    if clean[pos] == '{':
        stop = close(clean, pos, '{', '}')
        if not stop or stop > end:
            raise Bail
        return ('block', pos, stop, _block(clean, pos + 1, stop - 1)), stop
    word = re.match(rf'{IDENT}', clean[pos:end])
    if word and word[0] in _STOP:
        raise Bail
    if word and word[0] == 'goto':
        hit = re.match(rf'goto\s+({IDENT})\s*;', clean[pos:end])
        if not hit:
            raise Bail
        return ('goto', pos, pos + hit.end(), hit[1]), pos + hit.end()
    if word and word[0] not in ('if',) + _OPAQUE:
        label = re.match(rf'({IDENT})\s*:(?!:)', clean[pos:end])
        if label:
            return ('label', pos, pos + label.end(), label[1]), pos + label.end()
    if word and word[0] == 'if':
        paren = _skip(clean, pos + 2, end)
        if paren >= end or clean[paren] != '(':
            raise Bail
        after = close(clean, paren, '(', ')')
        if not after:
            raise Bail
        then, here = _statement(clean, after, end)
        other = None
        look = _skip(clean, here, end)
        if re.match(r'else\b', clean[look:end]):
            other, here = _statement(clean, look + 4, end)
        return ('if', pos, here, clean[paren + 1:after - 1], then, other), here
    if word and word[0] in _OPAQUE:
        return _opaque(clean, pos, end, word[0])
    stop = clean.find(';', pos, end)
    if stop < 0:
        raise Bail
    for ch, mate in (('(', ')'), ('{', '}'), ('[', ']')):
        if clean.count(ch, pos, stop) != clean.count(mate, pos, stop):
            raise Bail
    return ('simple', pos, stop + 1, clean[pos:stop + 1]), stop + 1


def _opaque(clean, pos, end, word):
    if word == 'do':
        brace = _skip(clean, pos + 2, end)
        if clean[brace:brace + 1] != '{':
            raise Bail
        stop = close(clean, brace, '{', '}')
        tail = re.match(r'\s*while\s*\([^;{}]*\)\s*;', clean[stop:end]) if stop else None
        if not tail:
            raise Bail
        return ('opaque', pos, stop + tail.end()), stop + tail.end()
    paren = _skip(clean, pos + len(word), end)
    after = close(clean, paren, '(', ')') if clean[paren:paren + 1] == '(' else None
    if not after:
        raise Bail
    _, here = _statement(clean, after, end)
    return ('opaque', pos, here), here


def _block(clean, pos, end):
    nodes = []
    while _skip(clean, pos, end) < end:
        node, pos = _statement(clean, pos, end)
        nodes.append(node)
    return nodes


def _walk(nodes):
    for node in nodes:
        yield node
        if node[0] == 'block':
            yield from _walk(node[3])
        elif node[0] == 'if':
            yield from _walk([node[4]] + ([node[5]] if node[5] else []))


def _has_jump(nodes):
    return any(node[0] in ('goto', 'label') for node in _walk(nodes))


# ---- running a chain on one counter value ----

def _compile(nodes, ops, fresh):
    """The nodes as a flat program: ('stmt', text), ('jmp', label), ('label', name), ('brf', condition, label)."""
    for node in nodes:
        kind = node[0]
        if kind == 'simple':
            ops.append(('stmt', node[3].strip()))
        elif kind == 'goto':
            ops.append(('jmp', node[3]))
        elif kind == 'label':
            ops.append(('label', node[3]))
        elif kind == 'block':
            _compile(node[3], ops, fresh)
        elif kind == 'if':
            skip, done = f'.else{next(fresh)}', f'.end{next(fresh)}'
            ops.append(('brf', node[3], skip))
            _compile([node[4]], ops, fresh)
            if node[5]:
                ops.append(('jmp', done))
                ops.append(('label', skip))
                _compile([node[5]], ops, fresh)
                ops.append(('label', done))
            else:
                ops.append(('label', skip))
        else:
            raise Bail


def _fresh():
    n = 0
    while True:
        n += 1
        yield n


def _holds(cond, known):
    hit = _COMPARE.match(cond.strip())
    if not hit or hit['x'] not in known:
        raise Bail
    left, right = known[hit['x']], _number(hit['lit'])
    return {'==': left == right, '!=': left != right, '<': left < right, '<=': left <= right,
            '>': left > right, '>=': left >= right}[hit['op']]


def _run(ops, counter, value, stepped):
    """(effects, steps of each reduced variable, temporaries set) of one pass over the program with the counter at
    `value`. The effects are the calls it makes, with the temporaries it set written as the constants they held."""
    labels = {arg: at for at, (kind, arg, *_) in enumerate(ops) if kind == 'label'}
    known, text, effects = {counter: value}, {}, []
    steps, pc, spent = dict.fromkeys(stepped, 0), 0, 0
    while pc < len(ops):
        spent += 1
        kind, arg, *rest = ops[pc]
        pc += 1
        if spent > MAX_STEPS:
            raise Bail
        if kind == 'jmp':
            if arg not in labels:
                raise Bail
            pc = labels[arg]
        elif kind == 'brf':
            if not _holds(arg, known):
                pc = labels[rest[0]]
        elif kind == 'stmt':
            assign, step = _ASSIGN.match(arg), _STEP.match(arg)
            if step and step['v'] in steps:
                steps[step['v']] += 1
            elif assign and assign['v'] != counter and assign['v'] not in steps:
                known[assign['v']], text[assign['v']] = _number(assign['lit']), assign['lit']
            elif _CALL.match(arg) and not set(re.findall(IDENT, arg)) & set(steps):
                effects.append(re.sub(IDENT, lambda m: text.get(m[0], m[0]), arg))
            else:
                raise Bail
    return tuple(effects), steps, set(text)


def _chain(nodes, counter, stepped):
    """(cases {value: effects}, default effects, temporaries) of a chain of nodes read as a function of the counter,
    or Bail. Every value that matters (each compared literal and its neighbours, and the two unbounded ends) is run,
    and each run must step every reduced variable exactly once."""
    ops = []
    _compile(nodes, ops, _fresh())
    marks = set()
    for kind, arg, *_ in ops:
        if kind == 'brf':
            hit = _COMPARE.match(arg.strip())
            if not hit:
                raise Bail
            marks.add(_number(hit['lit']))
    points = sorted({m + d for m in marks for d in (-1, 0, 1)})
    if not points:
        raise Bail
    ends = (points[0] - 5, points[-1] + 5)
    results, temps = {}, set()
    for value in points + list(ends):
        effects, steps, assigned = _run(ops, counter, value, stepped)
        if any(count != 1 for count in steps.values()):
            raise Bail
        results[value] = effects
        temps |= assigned
    if results[ends[0]] != results[ends[1]]:
        raise Bail
    default = results[ends[0]]
    cases = {value: results[value] for value in points if results[value] != default}
    # a value between two tested ones behaves like the tested neighbour: a case that spans untested values is a range
    # (and so is a chain with no case at all): the steps still count, but there is no `switch` to write
    if (not cases or len(cases) > MAX_CASES
            or any(near not in results and ends[0] < near < ends[1] for value in cases for near in (value - 1, value + 1))):
        return None, default, temps
    return cases, default, temps


def _switch(counter, cases, default, indent):
    groups = []
    for value in sorted(cases):
        if groups and groups[-1][1] == cases[value] and groups[-1][0][-1] == value - 1:
            groups[-1][0].append(value)
        else:
            groups.append(([value], cases[value]))
    pad = indent + '    '
    lines = [f'switch ({counter}) {{']
    for values, effects in groups:
        lines.append(pad + ' '.join(f'case {v}:' for v in values) + ' ' + ' '.join(effects) + ' break;')
    if default:
        lines.append(pad + 'default: ' + ' '.join(default) + ' break;')
    lines.append(indent + '}')
    return '\n'.join(lines)


# ---- finding the loop and what starts it ----

def _line_span(source, start, end):
    """The statement's span widened to its whole line when it is alone on it."""
    left = source.rfind('\n', 0, start) + 1
    right = source.find('\n', end)
    right = len(source) if right < 0 else right
    if not source[left:start].strip() and not source[end:right].strip():
        return left, min(right + 1, len(source))
    return start, end


class Loop:
    """A `do { ...; i += 1; } while (i < E);`: its brace span, the statements of its body and its counter."""


def _loops(part):
    clean = part.clean
    for hit in re.finditer(r'\bdo\s*{', clean[part.opening:part.end]):
        opening = part.opening + hit.end() - 1
        end = close(clean, opening, '{', '}')
        tail = re.match(r'\s*while\s*\((?P<cond>[^;{}]*)\)\s*;', clean[end:]) if end else None
        if not tail or re.search(r'\b(?:return|break|continue)\b', clean[opening:end]):
            continue
        try:
            body = _block(clean, opening + 1, end - 1)
        except Bail:
            continue
        if not body or body[-1][0] != 'simple':
            continue
        step = re.match(rf'^(?P<i>{IDENT})\s*(?:\+=\s*1|\+\+)\s*;$', body[-1][3].strip())
        cond = re.match(rf'^\s*\(?\s*(?P<i>{IDENT})\s*<\s*(?P<e>[^;{{}}=]+?)\s*\)?\s*$', tail['cond'])
        if not step or not cond or cond['i'] != step['i'] or re.search(rf'\b{step["i"]}\b', cond['e']):
            continue
        loop = Loop()
        loop.keyword, loop.opening, loop.end, loop.tail, loop.body = hit.start() + part.opening, opening, end, tail, body
        loop.counter, loop.limit = step['i'], re.sub(r'\s+', ' ', cond['e'].strip())
        yield loop


def _simple_run(clean, stop, floor):
    """The run of simple statements that ends at `stop`, reading back to `floor`: [(start, end, text)]."""
    run = []
    while True:
        text = clean[floor:stop].rstrip()
        end = floor + len(text)
        if not text.endswith(';'):
            return run
        begin = max(text.rfind(';', 0, len(text) - 1), text.rfind('{'), text.rfind('}')) + 1
        raw = clean[floor + begin:end]
        statement = raw.strip()
        if not statement or statement.startswith(('#', 'else')) or re.match(r'(?:if|while|for|do)\b', statement):
            return run
        run.insert(0, (floor + begin + len(raw) - len(raw.lstrip()), end, statement))
        stop = floor + begin
        if begin == 0:
            return run


def _entry(part, loop):
    """What stands before the loop: (guard match or None, guard start, the statements that start it), the statements
    before the guard and those inside its braces together, in order. The guard is an `if (...) {` that holds only
    simple statements before the `do`."""
    clean = part.clean
    floor = part.opening + 1
    inside = _simple_run(clean, loop.keyword, floor)
    top = inside[0][0] if inside else loop.keyword
    brace = clean[floor:top].rstrip()
    if not brace.endswith('{') or not brace[:-1].rstrip().endswith(')'):
        return None, loop.keyword, inside
    shut = floor + len(brace[:-1].rstrip()) - 1
    depth, at = 0, shut
    while at >= floor:
        depth += {')': 1, '(': -1}.get(clean[at], 0)
        if depth == 0:
            break
        at -= 1
    head = re.search(r'\bif\s*$', clean[floor:at])
    if at < floor or not head:
        return None, loop.keyword, inside
    guard = {'c': clean[at + 1:shut]}
    start = floor + head.start()
    return guard, start, _simple_run(clean, start, floor) + inside


def _guard_flag(part, guard, run, loop):
    """How the guard relates to the loop's own entry test: 'own' for `if (E > 0)`, (start, end) of the statement that
    set the flag it tests, or None when it is anything else."""
    cond = re.sub(r'\s+', ' ', guard['c'].strip())
    limit = re.escape(loop.limit)
    test = rf'\(?\s*(?:{limit}\s*>\s*0|0\s*<\s*{limit})\s*\)?'
    if re.fullmatch(rf'\(?\s*{test}\s*\)?', cond):
        return 'own'
    if not re.fullmatch(IDENT, cond):
        return None
    for begin, end, text in run:
        if re.fullmatch(rf'{cond}\s*=\s*{test};', re.sub(r'\s+', ' ', text)):
            uses = len(re.findall(rf'\b{cond}\b', part.clean[part.opening:part.end]))
            return (begin, end) if uses == 3 else None  # its declaration, this set, and the `if`
    return None


def _reductions(part, loop, run, body):
    """({variable: (step, step nodes)}, chain nodes or None): the variables the loop steps by one literal exactly once
    per iteration (started at a literal before it, read only before the step, never after the loop), and the
    `goto` chain that carries the steps, when there is one."""
    clean = part.clean
    starts = {m['v']: m for m in (_ASSIGN.match(text) for _, _, text in run) if m}
    after = clean[loop.end + loop.tail.end():part.end]
    steps = {}
    for node in _walk(body):
        step = _STEP.match(node[3].strip()) if node[0] == 'simple' else None
        if step and step['v'] != loop.counter and step['v'] in starts:
            steps.setdefault(step['v'], []).append(node)
    reduced = {}
    for var, nodes in steps.items():
        ks = {_number(_STEP.match(n[3].strip())['k']) for n in nodes}
        if (len(ks) == 1 and not re.search(rf'\b{var}\b', after) and not re.search(rf'\b{var}\b', loop.tail['cond'])
                and not _written(clean, loop, var, nodes)):
            reduced[var] = (ks.pop(), nodes)
    first = next((i for i, node in enumerate(body) if _has_jump([node])), None)
    chain = body[first:] if first is not None else None
    if chain and any(n[0] == 'label' for n in _walk(body[:first])):
        raise Bail
    place = chain[0][1] if chain else None
    for var in list(reduced):
        k, nodes = reduced[var]
        inside = [n for n in nodes if chain and chain[0][1] <= n[1] < chain[-1][2]]
        top = [n for n in body if n in nodes]
        uses = [loop.opening + 1 + m.start() for m in re.finditer(rf'\b{var}\b', clean[loop.opening + 1:loop.end])
                if not any(n[1] <= loop.opening + 1 + m.start() < n[2] for n in nodes)]
        # a chain steps it on all its paths (checked by running it); otherwise one statement of the body does
        ok = len(inside) == len(nodes) if chain else len(top) == 1 == len(nodes)
        if not ok or any(use >= (place if chain else nodes[0][1]) for use in uses):
            del reduced[var]
    return reduced, chain


_WRITE = re.compile(r'\s*(?:=(?!=)|[-+*/%&|^]=|<<=|>>=|\+\+|--|\[|\.)')


def _written(clean, loop, var, steps):
    """The loop body writes `var` (or takes its address, or indexes it) anywhere but in its own steps."""
    for use in re.finditer(rf'\b{var}\b', clean[loop.opening + 1:loop.end]):
        at = loop.opening + 1 + use.start()
        if any(n[1] <= at < n[2] for n in steps):
            continue
        if _WRITE.match(clean[at + len(var):]) or re.search(r'(?:&|\+\+|--)\s*$', clean[:at]):
            return True
    return False


def _expression(counter, k, base, whole):
    scaled = counter if k == 1 else f'{counter} * {k}'
    text = scaled if _number(base) == 0 else f'{scaled} + {base}'
    return text if whole or text == counter else f'({text})'


def _outside_uses(part, names, spans):
    """Names that appear in the function outside `spans` and its declarations."""
    clean = part.clean
    cut = list(spans) + [m.span() for name in names for m in re.finditer(
        rf'(?m)^[ \t]*[A-Za-z_][\w ]*?[ \t*]+{re.escape(name)}\s*;', clean)]
    return [name for name in names for m in re.finditer(rf'\b{re.escape(name)}\b', clean[part.opening:part.end])
            if not any(a <= part.opening + m.start() < b for a, b in cut)]


def _dedent(text, header, indent):
    """The `for` the edit wrote, its body one level out (the `do` and its guard are gone) and its brace at `indent`."""
    at = text.find(header)
    if at < 0:
        return text
    opened = at + len(header) - 1
    stop = close(text, opened, '{', '}')
    if not stop:
        return text
    lines = text[opened + 1:stop - 1].split('\n')
    inner = [line for line in lines[1:] if line.strip()]
    if inner and all(line.startswith(indent + ' ' * 8) for line in inner):
        lines = [lines[0]] + [line[4:] if line.strip() else line for line in lines[1:]]
    tail = lines[-1]
    lines[-1] = indent if not tail.strip() else tail
    return text[:opened + 1] + '\n'.join(lines) + text[stop - 1:]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    result, seen = [], {source}
    for loop in _loops(part):
        try:
            made = _children(source, part, loop)
        except Bail:
            continue
        for family, text in made:
            if text not in seen and len(result) < MAX_CHILDREN:
                seen.add(text)
                result.append((family, text))
    return result


def _children(source, part, loop):
    clean, counter, body = part.clean, loop.counter, loop.body[:-1]
    guard, guard_at, run = _entry(part, loop)
    starts = {m['v']: (b, e, m['lit']) for b, e, text in run if (m := _ASSIGN.match(text))}
    if counter not in starts or _number(starts[counter][2]) != 0:
        raise Bail
    if _written(clean, loop, counter, [loop.body[-1]]):
        raise Bail
    reduced, chain = _reductions(part, loop, run, body)
    switch = None
    if chain:
        # the steps are counted by running the chain: a chain it cannot run is not shown to step once per iteration
        cases, default, temps = _chain(chain, counter, set(reduced))
        if cases:
            span = (chain[0][1], chain[-1][2])
            if not _outside_uses(part, temps, [span]):
                indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, span[0]) + 1:]).group(0)
                switch = (*span, _switch(counter, cases, default, indent))
    if (chain and not reduced and not switch) or not (reduced or switch):
        raise Bail
    if reduced:
        # between a start and the loop nothing else may read what the loop will compute
        names = set(reduced) | {counter}
        for begin, end, text in run:
            if not _ASSIGN.match(text) and not _DECLARATION.match(text) and set(re.findall(IDENT, text)) & names:
                raise Bail
    family = FAMILY if reduced else SWITCH_FAMILY
    reduce = []
    for var, (k, nodes) in reduced.items():
        begin, end = _line_span(source, starts[var][0], starts[var][1])
        reduce.append((begin, end, ''))
        for node in nodes:
            begin, end = _line_span(source, node[1], node[2])
            reduce.append((begin, end, ''))
        for use in re.finditer(rf'\b{var}\b', clean[loop.opening + 1:loop.end]):
            at = loop.opening + 1 + use.start()
            if any(n[1] <= at < n[2] for n in nodes):
                continue
            before, after = clean[:at].rstrip()[-1:], clean[at + len(var):].lstrip()[:1]
            reduce.append((at, at + len(var), _expression(counter, k, starts[var][2], before in '(,' and after in '),')))
    chained = [e for e in reduce if not (switch and switch[0] <= e[0] < switch[1])] + ([switch and (
        switch[0], switch[1], switch[2])] if switch else [])
    loops = _for_edits(source, part, loop, guard, guard_at, run, starts, reduced)
    header = f'for ({counter} = 0; {counter} < {loop.limit}; {counter}++) {{'
    indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, guard_at) + 1:]).group(0)
    children = []
    for edits, wanted in ((chained, bool(switch)), (reduce, True)):
        if not wanted or (edits is chained and not reduced and not switch):
            continue
        for extra in ([loops] if loops else []) + [[]]:
            children.append((family, edits + extra, bool(extra)))
    out = []
    for fam, edits, as_for in children:
        try:
            text = _apply(source, edits)
        except Bail:
            continue
        out.append((fam, _dedent(text, header, indent) if as_for else text))
    return out


def _for_edits(source, part, loop, guard, guard_at, run, starts, reduced):
    """The edits that write the guarded `do` loop as a `for`, or None when the guard is not the loop's entry test."""
    if not guard:
        return None
    flag = _guard_flag(part, guard, run, loop)
    tail_end = loop.end + loop.tail.end()
    shut = re.match(r'\s*}', part.clean[tail_end:])
    if not flag or not shut:
        return None
    consumed = [starts[loop.counter][:2]] + ([flag] if flag != 'own' else [])
    edits = [(*_line_span(source, begin, end), '') for begin, end in consumed]
    # anything else inside the guard before the loop would run once per call, not per iteration: not a plain `for`
    spare = [p for p in run if p[0] >= guard_at and not _ASSIGN.match(p[2])]
    if spare:
        return None
    step = loop.body[-1]
    edits.append((*_line_span(source, step[1], step[2]), ''))
    edits.append((guard_at, loop.opening + 1, f'for ({loop.counter} = 0; {loop.counter} < {loop.limit}; {loop.counter}++) {{'))
    edits.append((loop.end - 1, tail_end + shut.end(), '}'))
    return edits


def _apply(source, edits):
    ordered = sorted(set(edits))
    for (_, stop, _), (start, _, _) in zip(ordered, ordered[1:]):
        if start < stop:
            raise Bail
    return edit(source, ordered)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
