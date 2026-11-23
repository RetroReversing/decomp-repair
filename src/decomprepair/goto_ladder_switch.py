"""m2c's goto ladder over one variable, written back as the `switch` it came from.

m2c reads a `switch` that the compiler turned into a decision tree (`slti`/`beq` splits) as a ladder of `if`s, `goto`s
and labels, with shared tail blocks (`to2FC: id = 0x2FC; goto joined;`), a flag for "no case matched" (`other = 1`)
and sometimes a temporary holding a constant that a shared compare reads (`finalCase = 0x10B; goto lastCheck;`):

    if (cond) {
        other = 0;
        if (id == 0x153) goto to2FC;
        if (id < 0x154) { ... if (id == 2) id = 0x2FA; else other = 1; goto joined; ... }
        ...
    to2FC: id = 0x2FC; goto joined;
    }
    joined: ...

Every path of such a block fixes what it does to the variables from the value of the one variable it tests, so the
block is a function of that value. This family runs the block on every value that matters (the compared constants and
their neighbours), groups the values by what they do (the assignments they leave behind), and writes the groups as the
cases of one `switch (id)`; the values that all do the same thing (and the two unbounded ends) are the `default`.
KMC GCC 2.7.2 builds its own decision tree from the cases, so it makes the original's compares, its shared tests and its
tail blocks itself (a 141-instruction N64 function, 660 -> 0: the ladder had `bnel` where the original had `beql`,
three times, from tail blocks the compiler's own cross-jumping merged).

Two layout facts decide a match and are the family's children: where the `default:` label sits (first, so that its
`other = 1` block is not the one the last case falls into; or last), and the order of the case groups (the groups
appear in the order their assignments appear in the ladder, or in ascending order of their first value). The
compiler lays the arms out in the source's order, and a `default:` written last became the block that falls into the
code after the switch, where the original had a jump to it.

Left alone: a block with anything but constant assignments, `if`s comparing a variable with a constant (or a variable
the path fixed to one), `goto`s and labels; a block that leaves anywhere but to the code right after it; two or more
tested variables; ranges wider than 16 values whose effect is not the default's (a range is written by the range
families); fewer than four cases.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'goto_ladder_switch'
FAMILIES = (FAMILY,)

MAX_RANGE = 16
MIN_CASES = 4
STEPS = 4000
TOKEN = re.compile(r'\s*(?P<t>0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*|[A-Za-z_]\w*|==|!=|<=|>=|[{}();:=<>])')
KEYWORDS = {'if', 'else', 'goto', 'return', 'while', 'for', 'do', 'switch', 'case', 'default', 'break', 'continue'}
TYPES = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 's64', 'u64', 'int', 'long', 'short', 'char', 'unsigned', 'signed', 'f32', 'f64'}


class _Unsupported(Exception):
    pass


def _tokens(text):
    out, at = [], 0
    while at < len(text):
        if not text[at:].strip():
            break
        m = TOKEN.match(text, at)
        if not m:
            raise _Unsupported
        out.append(m['t'])
        at = m.end()
    return out


def _number(token):
    return int(token.rstrip('uUlL'), 0) if re.match(r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*$', token) else None


class _Parser:
    def __init__(self, tokens):
        self.t = tokens
        self.i = 0
        self.declared = set()

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else None

    def take(self, expect=None):
        if self.i >= len(self.t) or (expect is not None and self.t[self.i] != expect):
            raise _Unsupported
        self.i += 1
        return self.t[self.i - 1]

    def operand(self):
        t = self.take()
        n = _number(t)
        if n is not None:
            return ('num', n, t)
        if re.match(r'[A-Za-z_]\w*$', t) and t not in KEYWORDS:
            return ('var', t)
        raise _Unsupported

    def statement(self):
        t = self.peek()
        if t is None:
            raise _Unsupported
        if t == '{':
            self.take()
            body = []
            while self.peek() != '}':
                body.append(self.statement())
            self.take('}')
            return ('block', body)
        if t == ';':
            self.take()
            return ('block', [])
        if t == 'if':
            self.take()
            self.take('(')
            left = self.operand()
            op = self.take()
            if op not in ('==', '!=', '<', '<=', '>', '>='):
                raise _Unsupported
            right = self.operand()
            self.take(')')
            then = self.statement()
            other = None
            if self.peek() == 'else':
                self.take()
                other = self.statement()
            return ('if', (left, op, right), then, other)
        if t == 'goto':
            self.take()
            name = self.take()
            self.take(';')
            return ('goto', name)
        if t in KEYWORDS:
            raise _Unsupported
        if self.peek(1) == ':':
            self.take()
            self.take(':')
            return ('label', t)
        if t in TYPES and self.peek(1) and re.match(r'[A-Za-z_]\w*$', self.peek(1)) and self.peek(2) == ';':
            self.take()
            self.declared.add(self.take())
            self.take(';')
            return ('block', [])
        if re.match(r'[A-Za-z_]\w*$', t) and self.peek(1) == '=':
            self.take()
            self.take('=')
            value = self.operand()
            self.take(';')
            return ('assign', t, value)
        raise _Unsupported


def _flatten(node, code, fresh):
    kind = node[0]
    if kind == 'block':
        for n in node[1]:
            _flatten(n, code, fresh)
    elif kind in ('assign', 'goto', 'label'):
        code.append(node)
    else:
        _, cond, then, other = node
        false_label, end_label = f'.f{next(fresh)}', f'.e{next(fresh)}'
        code.append(('ifnot', cond, false_label))
        _flatten(then, code, fresh)
        if other is not None:
            code.append(('goto', end_label))
        code.append(('label', false_label))
        if other is not None:
            _flatten(other, code, fresh)
            code.append(('label', end_label))


def _count():
    n = 0
    while True:
        n += 1
        yield n


def _compare(a, op, b):
    return {'==': a == b, '!=': a != b, '<': a < b, '<=': a <= b, '>': a > b, '>=': a >= b}[op]


def _run(code, labels, var, value, start, exit_label):
    """The variables' values when the block is left, for `var` = `value`; None when it cannot be told."""
    state = dict(start)
    state[var] = value
    at = steps = 0
    while at < len(code):
        steps += 1
        if steps > STEPS:
            raise _Unsupported
        node = code[at]
        at += 1
        if node[0] == 'assign':
            right = node[2]
            if right[0] == 'num':
                state[node[1]] = right[1]
            elif right[1] in state:
                state[node[1]] = state[right[1]]
            else:
                raise _Unsupported
        elif node[0] == 'goto' or node[0] == 'ifnot':
            if node[0] == 'ifnot':
                (left, op, right) = node[1]
                values = []
                for side in (left, right):
                    if side[0] == 'num':
                        values.append(side[1])
                    elif side[1] in state:
                        values.append(state[side[1]])
                    else:
                        raise _Unsupported
                if _compare(values[0], op, values[1]):
                    continue
                target = node[2]
            else:
                target = node[1]
            if target in labels:
                at = labels[target]
            elif target == exit_label:
                return state
            else:
                raise _Unsupported
    return state


def _numbers(code, var):
    found = set()
    for node in code:
        if node[0] == 'ifnot':
            found.update(side[1] for side in (node[1][0], node[1][2]) if side[0] == 'num')
        elif node[0] == 'assign' and node[1] != var and node[2][0] == 'num':
            found.add(node[2][1])
    return found


def _scrutinee(code):
    count = {}
    for node in code:
        if node[0] == 'ifnot':
            (left, _, right) = node[1]
            for a, b in ((left, right), (right, left)):
                if a[0] == 'var' and b[0] == 'num':
                    count[a[1]] = count.get(a[1], 0) + 1
    return max(count, key=count.get) if count else None


def _hex(n):
    return hex(n).upper().replace('0X', '0x') if abs(n) > 9 else str(n)


def _analyse(inside, after):
    """(var, prefix assignments, cases {value: effect}, default effect, effect order) of a block's inside, or None."""
    parser = _Parser(_tokens(inside))
    body = []
    while parser.peek() is not None:
        body.append(parser.statement())
    prefix = []
    while body and (body[0] == ('block', []) or (body[0][0] == 'assign' and body[0][2][0] == 'num')):
        node = body.pop(0)
        if node[0] == 'assign':
            prefix.append(node)
    code = []
    _flatten(('block', body), code, _count())
    if not any(n[0] in ('goto', 'label') for n in code):
        return None
    labels = {n[1]: i for i, n in enumerate(code) if n[0] == 'label'}
    var = _scrutinee(code)
    if var is None:
        return None
    exits = {n[1] for n in code if n[0] == 'goto' and n[1] not in labels}
    exits |= {n[2] for n in code if n[0] == 'ifnot' and n[2] not in labels}
    if len(exits) > 1 or (exits and (after is None or next(iter(exits)) != after)):
        return None
    exit_label = next(iter(exits)) if exits else None
    start = {n[1]: n[2][1] for n in prefix}
    marks = sorted({k + d for k in _numbers(code, var) for d in (0, 1)})
    if len(marks) < MIN_CASES:
        return None
    segments = [(None, marks[0], marks[0] - 1)] + [(a, b, a) for a, b in zip(marks, marks[1:])] + [(marks[-1], None, marks[-1] + 1)]
    effects = []
    for low, high, probe in segments:
        end = _run(code, labels, var, probe, start, exit_label)
        diff = {v: x for v, x in end.items() if v != var and start.get(v) != x and v not in parser.declared}
        if end[var] != probe:
            diff[var] = end[var]
        effects.append((low, high, diff))
    default = effects[0][2]
    if effects[-1][2] != default:
        return None
    cases = {}
    for low, high, diff in effects[1:-1]:
        if diff == default:
            continue
        if high - low > MAX_RANGE:
            return None
        for value in range(low, high):
            cases[value] = diff
    if len(cases) < MIN_CASES:
        return None
    seen = []
    for node in code:
        if node[0] == 'assign' and node[1] not in seen and node[1] not in parser.declared:
            seen.append(node[1])
    appears = []
    for node in code:
        if node[0] == 'assign' and node[2][0] == 'num' and node[1] not in parser.declared:
            appears.append((node[1], node[2][1]))
    return var, prefix, cases, default, seen, appears


def _groups(cases, appears, var):
    """The case groups (a list of values each, ascending) in order of the ladder's own assignments, and by value."""
    by_effect = {}
    for value in sorted(cases):
        by_effect.setdefault(tuple(sorted(cases[value].items())), []).append(value)
    groups = list(by_effect.values())

    def first(group):
        key = tuple(sorted(cases[group[0]].items()))
        for position, (name, number) in enumerate(appears):
            if (name, number) in key:
                return position
        return len(appears)
    return sorted(groups, key=first), sorted(groups, key=lambda g: g[0])


def _arm(effect, seen, indent):
    lines = [f'{indent}    {v} = {_hex(effect[v]) if v in effect else 0};\n' for v in seen if v in effect]
    return ''.join(lines) + f'{indent}    break;\n'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    depth_at = opening + 1
    while True:
        hit = re.compile(r'\bif\s*\(').search(clean, depth_at, end)
        if not hit:
            break
        depth_at = hit.end()
        if clean.count('{', opening, hit.start()) - clean.count('}', opening, hit.start()) != 1:
            continue
        cond_close = close(clean, clean.index('(', hit.start()))
        block = clean.find('{', cond_close) if cond_close else -1
        if block < 0 or clean[cond_close:block].strip():
            continue
        block_close = close(clean, block, '{', '}')
        if not block_close:
            continue
        rest = clean[block_close:end]
        after = re.match(r'\s*([A-Za-z_]\w*)\s*:', rest)
        if re.match(r'\s*else\b', rest):
            continue
        inside = clean[block + 1:block_close - 1]
        try:
            found = _analyse(inside, after.group(1) if after else None)
        except (_Unsupported, KeyError, IndexError, RecursionError):
            continue
        if not found:
            continue
        var, prefix, cases, default, seen, appears = found
        indent = re.match(r'[ \t]*', clean[clean.rfind('\n', 0, hit.start()) + 1:]).group()
        pad = indent + '    '
        first, ascending = _groups(cases, appears, var)
        for order in (first, ascending):
            for default_first in (True, False):
                arms = ''.join(''.join(f'{pad}case {_hex(v)}:\n' for v in group) + _arm(cases[group[0]], seen, pad) for group in order)
                default_arm = f'{pad}default:\n' + _arm(default, seen, pad)
                text = '\n' + ''.join(f'{pad}{n[1]} = {n[2][2] if n[2][0] == "num" else n[2][1]};\n' for n in prefix)
                text += f'{pad}switch ({var}) {{\n' + (default_arm + arms if default_first else arms + default_arm) + f'{pad}}}\n{indent}'
                candidate = source[:block + 1] + text + source[block_close - 1:]
                if candidate not in [t for _, t in result]:
                    result.append((FAMILY, candidate))
    return result[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
