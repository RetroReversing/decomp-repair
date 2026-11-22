"""m2c's compare tree with range tests over one variable, whose leaves assign constants, written as a `switch`.

gcc lowers a small `switch` whose cases set one value into compares with a range test in the middle (`slti`), and m2c
reads that back as nested `if`s over one variable with `<` / `>=` and `!=` tests, each leaf assigning a constant that
the code after the tree uses:

    if (t != 0x1A) {
        if (0x1B > (s32) t) { v = 3; if (t != 0x19) { v = 1; } }
        else { v = 1; if (t == 0x1B) { v = 3; } }
    } else { v = 2; }
    X = v;

Written as C that tree compiles to the target's registers only by luck; as `switch (t) { case 0x19: case 0x1B: v = 3;
break; case 0x1A: v = 2; break; default: v = 1; break; }` a KMC gcc 2.7.2 save-menu function went from 30 (the
value in `$a0` instead of `$v0`) to exact. assignment_tree_switch reads only `==` / `!=` tests; this one runs the tree
for every constant it tests, one value beside each, and one beyond each end, so range tests and shared leaves
need no pattern: the values that fall in no tested constant must all give one outcome (the `default`), and each
tested constant that differs from it is a case (constants with one outcome share labels in the first child, and
repeat the body in the second). Only constant assignments (or a local the function sets to one constant once) and
`if`s on the one variable are read; a `u32`/unsigned cast, a call or any other statement leaves the tree alone.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'range_assignment_switch'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?\s*(?:0[xX][0-9a-fA-F]+|\d+)'
SIGNED_CAST = re.compile(r'\(\s*(?:s32|int|signed|signed int|long)\s*\)\s*')
BARE = re.compile(r'\(\s*(' + IDENT + r')\s*\)')
FLIP = {'<': '>', '>': '<', '<=': '>=', '>=': '<=', '==': '==', '!=': '!='}
OPS = {'==': lambda a, b: a == b, '!=': lambda a, b: a != b, '<': lambda a, b: a < b, '<=': lambda a, b: a <= b,
       '>': lambda a, b: a > b, '>=': lambda a, b: a >= b}
UNSIGNED = re.compile(r'\b(?:u8|u16|u32|unsigned)\b')


class _Bail(Exception):
    pass


def _spell(k):
    return str(k) if -10 < k < 10 else f'-0x{-k:X}' if k < 0 else f'0x{k:X}'


def _number(text):
    return int(text.replace(' ', ''), 0)


def _condition(text):
    """(variable, op, constant) from one test, or Bail."""
    text = text.strip()
    while True:
        new = BARE.sub(r'\1', SIGNED_CAST.sub('', text))
        if new == text:
            break
        text = new
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    if re.search(r'\d[uU]\b|\(\s*(?:u8|u16|u32|unsigned)', text):
        raise _Bail
    m = re.fullmatch(r'(' + IDENT + r')\s*(==|!=|<=|>=|<|>)\s*(' + NUMBER + r')', text)
    if m:
        return m[1], m[2], _number(m[3])
    m = re.fullmatch(r'(' + NUMBER + r')\s*(==|!=|<=|>=|<|>)\s*(' + IDENT + r')', text)
    if m:
        return m[3], FLIP[m[2]], _number(m[1])
    m = re.fullmatch(r'(!?)\s*(' + IDENT + r')', text)
    if m:
        return m[2], '==' if m[1] else '!=', 0
    raise _Bail


def _block(clean, start, stop, constants, tests):
    """The statements of clean[start:stop]: ('set', name, number) and ('if', (variable, op, k), then, else)."""
    items, at = [], start
    while True:
        while at < stop and clean[at] in ' \t\n':
            at += 1
        if at >= stop:
            return items
        m = re.compile(r'(' + IDENT + r')\s*=(?!=)\s*(' + NUMBER + r'|' + IDENT + r')[uUlL]*\s*;').match(clean, at)
        if m and m.end() <= stop:
            value = m[2]
            if re.fullmatch(IDENT, value):
                if value not in constants:
                    raise _Bail
                value = constants[value]
            else:
                value = _number(value)
            items.append(('set', m[1], value))
            at = m.end()
            continue
        node, at = _if(clean, at, stop, constants, tests)
        items.append(node)


def _if(clean, at, stop, constants, tests):
    head = re.compile(r'if\s*\(').match(clean, at)
    if not head:
        raise _Bail
    cond_open = head.end() - 1
    cond_close = close(clean, cond_open)
    if not cond_close or cond_close > stop:
        raise _Bail
    test = _condition(clean[cond_open + 1:cond_close - 1])
    tests.append(test)
    then_open = cond_close
    while clean[then_open] in ' \t\n':
        then_open += 1
    if clean[then_open] != '{':
        raise _Bail
    then_close = close(clean, then_open, '{', '}')
    if not then_close:
        raise _Bail
    then = _block(clean, then_open + 1, then_close - 1, constants, tests)
    after = then_close
    while after < stop and clean[after] in ' \t\n':
        after += 1
    other = []
    end = then_close
    if re.compile(r'else\b').match(clean, after):
        rest = after + 4
        while clean[rest] in ' \t\n':
            rest += 1
        if clean[rest] == '{':
            else_close = close(clean, rest, '{', '}')
            if not else_close:
                raise _Bail
            other = _block(clean, rest + 1, else_close - 1, constants, tests)
            end = else_close
        else:
            node, end = _if(clean, rest, stop, constants, tests)
            other = [node]
    return ('if', test, then, other), end


def _run(items, value, env):
    for item in items:
        if item[0] == 'set':
            env[item[1]] = item[2]
        else:
            _, (_, op, k), then, other = item
            _run(then if OPS[op](value, k) else other, value, env)


def _constants(body):
    """Locals the function sets to one constant once (`x = 3;` or `T x = 3;`): a tree may assign them."""
    found = {}
    for m in re.finditer(r'\b(' + IDENT + r')\s*=(?!=)\s*(' + NUMBER + r')[uUlL]*\s*;', body):
        found.setdefault(m[1], []).append(_number(m[2]))
    result = {}
    for name, values in found.items():
        if len(values) == 1 and len(re.findall(r'\b' + name + r'\s*=(?!=)', body)) == 1:
            result[name] = values[0]
    return result


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    constants = _constants(clean[opening:end])
    result, covered = [], 0
    for hit in re.finditer(r'(?m)^(?P<indent>[ \t]*)if\s*\(', clean[:end]):
        if hit.start() < opening or hit.start() < covered:
            continue
        at = hit.start('indent') + len(hit['indent'])
        tests = []
        try:
            node, stop = _if(clean, at, end, constants, tests)
            variable = tests[0][0]
            if any(t[0] != variable for t in tests):
                raise _Bail
            kinds = {t[2] for t in tests}
            declared = re.search(r'\b((?:unsigned\s+)?\w+)\s+' + variable + r'\s*[;,=)\[]', clean[:end])
            low = 0 if declared and UNSIGNED.search(declared[1]) else -2 ** 31
            samples = set(kinds) | {low, 2 ** 31 - 1}
            for k in kinds:
                samples |= {k - 1, k + 1}
            samples = sorted(s for s in samples if s >= low)
            outcomes = {}
            for s in samples:
                env = {}
                _run([node], s, env)
                outcomes[s] = env
        except (_Bail, IndexError, ValueError):
            continue
        generic = [outcomes[s] for s in samples if s not in kinds]
        if not generic or any(g != generic[0] for g in generic):
            continue
        default = generic[0]
        cases = {k: outcomes[k] for k in sorted(kinds) if outcomes[k] != default}
        if len(cases) < 2:
            continue
        order = []
        for env in [*cases.values(), default]:
            order.extend(v for v in env if v not in order)
        line_end = clean.find('\n', stop - 1)
        if clean[stop:line_end].strip():
            continue
        indent = hit['indent']

        def body(env, indent=indent):
            return ''.join(f'{indent}  {v} = {_spell(env[v])};\n' for v in order if v in env) + f'{indent}  break;\n'
        groups = []
        for k, env in cases.items():
            for group in groups:
                if group[1] == env:
                    group[0].append(k)
                    break
            else:
                groups.append(([k], env))
        shared = ''.join(''.join(f'{indent}case {_spell(k)}:\n' for k in keys) + body(env) for keys, env in groups)
        split = ''.join(f'{indent}case {_spell(k)}:\n{body(env)}' for k, env in cases.items())
        for labels in (shared, split):
            text = (f'{indent}switch ({variable})\n{indent}{{\n' + labels + f'{indent}default:\n{body(default)}{indent}}}\n')
            candidate = source[:hit.start()] + text + source[line_end + 1:]
            if candidate not in [t for _, t in result]:
                result.append((FAMILY, candidate))
        covered = stop
    return result[:4]
