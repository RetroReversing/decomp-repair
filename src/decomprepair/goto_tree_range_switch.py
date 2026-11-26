"""m2c's `if`/`goto` tree of range tests over one variable that leads to a shared tail, written as a `switch`.

GCC 2.7.2 compiles a `switch` with `case lo ... hi:` ranges into a balanced tree of `slti` tests (and a `bltz` for the
lower bound), which m2c reads back as nested `if`s with `goto`s into one arm's tail, where each leaf assigns a few
constants and every one but the default runs on into the same code:

    if (v < 0xA0) { if (v < 0x8C) { r = 0xC8; if (v < 0x78) { r = 0xFF; if (v >= 0) { g = 0xFF; goto draw; }
    goto bad; } g = 0xC8; goto draw; } ... draw: use(r, g); return; }
    bad: report();

The nested `if`s compiled as written lay the tests and arms out differently. This runs the tree for every interval of
the variable's value and writes the arms as `switch (v) { case 0 ... 0x77: r = 0xFF; g = 0xFF; break; ...
default: report(); return; } use(r, g);`. A colour ladder of 96 instructions (KMC GCC 2.7.2 `-O1`) was 5781 from m2c's
draft. The case ranges are GNU C; the exact judge decides.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'goto_tree_range_switch'
FAMILIES = (FAMILY,)

MIN_ARMS = 3
STEPS = 500
TEST = re.compile(r'\s*(?:\(\s*s32\s*\)\s*)?([A-Za-z_]\w*)\s*(==|!=|<=|>=|<|>)\s*(0[xX][0-9a-fA-F]+|\d+)\s*\Z')
CONSTANT = re.compile(r'([A-Za-z_]\w*)\s*=\s*(-?(?:0[xX][0-9a-fA-F]+|\d+))\s*;\Z')
LABEL = re.compile(r'\s*([A-Za-z_]\w*)\s*:(?!:)')
OPS = {'==': lambda a, b: a == b, '!=': lambda a, b: a != b, '<': lambda a, b: a < b,
       '<=': lambda a, b: a <= b, '>': lambda a, b: a > b, '>=': lambda a, b: a >= b}


class _Unsupported(Exception):
    pass


def _flatten(clean, at, end, code):
    """The statements in clean[at:end] as a flat list with jumps: (kind, data, start offset, end of its block)."""
    while True:
        while at < end and clean[at].isspace():
            at += 1
        if at >= end:
            return
        at = _statement(clean, at, end, code)


def _statement(clean, at, end, code):
    """Appends the statement at `at` and returns the offset after it. `end` is where its block ends."""
    label = LABEL.match(clean, at)
    if label and label[1] not in ('case', 'default'):
        code.append(('label', label[1], at, end))
        return label.end()
    if clean[at] == '{':
        shut = close(clean, at, '{', '}')
        if not shut:
            raise _Unsupported
        _flatten(clean, at + 1, shut - 1, code)
        return shut
    if clean[at] == ';':
        return at + 1
    if re.compile(r'(?:for|while|do|switch|case|default)\b').match(clean, at):
        raise _Unsupported
    head = re.compile(r'if\s*\(').match(clean, at)
    if head:
        shut = close(clean, head.end() - 1)
        if not shut:
            raise _Unsupported
        jump = len(code)
        code.append(None)
        after = _skip(clean, shut)
        after = _statement(clean, after, end, code)
        other = re.compile(r'\s*else\b').match(clean, after)
        if other:
            leave = len(code)
            code.append(None)
            code[jump] = ('ifnot', (clean[head.end():shut - 1], len(code)), at, end)
            after = _statement(clean, _skip(clean, other.end()), end, code)
            code[leave] = ('jump', len(code), at, end)
        else:
            code[jump] = ('ifnot', (clean[head.end():shut - 1], len(code)), at, end)
        return after
    stop = clean.find(';', at, end)
    if stop < 0:
        raise _Unsupported
    text = clean[at:stop + 1]
    jump = re.match(r'goto\s+([A-Za-z_]\w*)\s*;\Z', text)
    if jump:
        code.append(('goto', jump[1], at, end))
    elif '{' in text:
        raise _Unsupported
    else:
        code.append(('statement', text, at, end))
    return stop + 1


def _skip(clean, at):
    while at < len(clean) and clean[at].isspace():
        at += 1
    return at


def _run(code, labels, var, value, at):
    """(constant assignments in the order of their last write, index of the first other statement) for `var` = value."""
    state = {}
    for _ in range(STEPS):
        if at >= len(code):
            return state, at
        kind, data = code[at][:2]
        if kind == 'label':
            at += 1
        elif kind == 'goto':
            if data not in labels:
                raise _Unsupported
            at = labels[data]
        elif kind == 'jump':
            at = data
        elif kind == 'ifnot':
            test = TEST.match(data[0])
            if not test or test[1] != var:
                return state, at
            at = at + 1 if OPS[test[2]](value, int(test[3], 0)) else data[1]
        else:
            constant = CONSTANT.match(data)
            if not constant or constant[1] == var:
                return state, at
            state.pop(constant[1], None)
            state[constant[1]] = constant[2]
            at += 1
    raise _Unsupported


def _tail(source, clean, code, at, closing):
    """The source that runs from statement `at` to its return, or to the end of the function."""
    if at >= len(code):
        return ''
    start, end = code[at][2], code[at][3]
    text, plain = source[start:end].rstrip(), clean[start:end].rstrip()
    returns = re.search(r'\breturn\b\s*;', plain)
    depth_zero = [hit for hit in re.finditer(r'\breturn\s*;', plain)
                  if plain[:hit.start()].count('{') == plain[:hit.start()].count('}')]
    if depth_zero:
        text, plain = text[:depth_zero[0].start()].rstrip(), plain[:depth_zero[0].start()]
    elif returns or end != closing:
        raise _Unsupported  # it runs on past its block: where it goes is not told here
    if re.search(r'\b(?:goto|return|break|continue)\b|(?m:^\s*[A-Za-z_]\w*\s*:(?!:))', plain):
        raise _Unsupported
    return text


def _indented(text, indent):
    lines = text.strip('\n').split('\n')
    # the first line starts at the statement itself; the rest keep their own indentation
    rest = [line for line in lines[1:] if line.strip()]
    common = min((len(line) - len(line.lstrip()) for line in rest), default=0)
    return '\n'.join([indent + lines[0].strip()] + [indent + line[common:] if line.strip() else '' for line in lines[1:]])


def _label(low, high):
    def number(n):
        return str(n) if n < 10 else f'0x{n:X}'
    return f'case {number(low)}:' if low == high else f'case {number(low)} ... {number(high)}:'


def variants(source, name):
    part = view(source, name)
    if not part or not re.search(r'\bvoid\s+' + re.escape(name) + r'\s*\(', part.clean):
        return []
    clean = part.clean
    closing = clean.rfind('}', 0, part.end)
    if 'goto' not in part.body:
        return []
    first = re.compile(r'\bif\s*\(').search(clean, part.opening + 1, closing)
    if not first or clean[part.opening + 1:first.start()].count('{'):
        return []
    shut = close(clean, first.end() - 1)
    test = TEST.match(clean[first.end():shut - 1]) if shut else None
    if not test:
        return []
    var = test[1]
    code = []
    try:
        _flatten(clean, first.start(), closing, code)
        labels = {data: i for i, (kind, data, *_) in enumerate(code) if kind == 'label'}
        edges = set()
        for kind, data, *_ in code:
            found = TEST.match(data[0]) if kind == 'ifnot' else None
            if found and found[1] == var:
                value = int(found[3], 0)
                edges.update({'<': (value,), '>=': (value,), '<=': (value + 1,), '>': (value + 1,)}
                             .get(found[2], (value, value + 1)))
        edges = sorted(edges)
        if not edges:
            return []
        spans = [(None, edges[0] - 1)] + [(a, b - 1) for a, b in zip(edges, edges[1:])] + [(edges[-1], None)]
        runs = []  # (low, high, assignments, tail)
        for low, high in spans:
            state, at = _run(code, labels, var, low if low is not None else high, 0)
            runs.append((low, high, state, _tail(source, clean, code, at, closing)))
    except _Unsupported:
        return []
    keys = [re.sub(r'\s+', '', run[3]) for run in runs]
    shared = max(set(keys), key=lambda t: (keys.count(t), len(t)))
    arms = []  # [low, high, (assignments, tail without spaces), tail]
    for (low, high, state, tail), key in zip(runs, keys):
        # an arm that leaves by itself keeps only the values it goes on to read
        kept = tuple((n, v) for n, v in state.items() if key == shared or re.search(rf'\b{n}\b', tail))
        if arms and arms[-1][2] == (kept, key):
            arms[-1][1] = high
        else:
            arms.append([low, high, (kept, key), tail])
    default = arms[0]
    if default[2] != arms[-1][2] or default[2][1] == shared:
        return []
    cases = [arm for arm in arms[1:-1] if arm[2] != default[2]]
    if len(cases) < MIN_ARMS or sum(arm[2][1] == shared for arm in cases) < 2:
        return []
    indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, first.start()) + 1:])[0] or '    '
    step = '    '
    lines = [f'switch ({var}) {{']

    def body(arm):
        for variable, value in arm[2][0]:
            lines.append(f'{indent}{step}{variable} = {value};')
        if arm[2][1] == shared:
            lines.append(f'{indent}{step}break;')
        else:
            if arm[3]:
                lines.append(_indented(arm[3], indent + step))
            lines.append(f'{indent}{step}return;')

    for arm in cases:
        lines.append(f'{indent}{_label(arm[0], arm[1])}')
        body(arm)
    lines.append(f'{indent}default:')
    body(default)
    lines.append(f'{indent}}}')
    joined = next(arm[3] for arm in cases if arm[2][1] == shared)
    text = '\n'.join(lines) + ('\n' + _indented(joined, indent) if joined else '')
    return [(FAMILY, edit(source, [(first.start(), len(source[:closing].rstrip()), text)]))]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
