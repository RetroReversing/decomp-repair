"""m2c's `var_aN`: a register's leftover value it passed as an extra argument, taken out again.

When an argument register still holds an earlier value at a call, m2c can't tell it is unused: it names the register
(`var_a0`), follows every value it held (a parameter's copy, a constant set inside a condition's comma), and passes it
as a trailing argument the callee's guessed prototype then has too:

    var_a0 = arg0;  temp_s0 = var_a0;
    if ((D == 0) || (var_a0 = (void *)1, (E == 1))) { ... }
    x = 1.0f / f(arg1 * k, var_a0);           /* prototype: f32 f(f32, void *); */

An N64 function was 97.6% so and exact without it: `temp_s0 = arg0;`, the plain condition, `f(arg1 * k)` and `f32
f(f32);`. Offered when the variable starts as a copy of a parameter and is otherwise only set inside commas, copied,
or passed as a call's last argument (with a float before it, `$a0` follows the float's own register).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'register_carrier_argument'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    signature = clean[span[0]:opening]
    params = re.findall(r'(' + IDENT + r')\s*(?:,|\))', signature[signature.rfind('(') + 1:])
    result = []
    for var in sorted(set(re.findall(r'\bvar_a([0-3])\b', clean[opening:end]))):
        v = f'var_a{var}'
        body = source[opening:end]
        cbody = clean[opening:end]
        first = re.search(r'(?m)^[ \t]*' + v + r'\s*=\s*(' + IDENT + r')\s*;[ \t]*\n', cbody)
        if not first or first[1] not in params:
            continue
        param = first[1]
        text = body
        # set inside a comma: `(v = K, (cond))` -> `(cond)`
        text = re.sub(r'\(\s*' + v + r'\s*=\s*[^,;()]*(?:\([^()]*\)[^,;()]*)*,\s*', '(', text)
        # copies: `x = v;` -> `x = param;`
        text = re.sub(r'(?m)^([ \t]*' + IDENT + r'\s*=\s*)' + v + r'\s*;', r'\g<1>' + param + ';', text)
        # the first assignment goes
        text = re.sub(r'(?m)^[ \t]*' + v + r'\s*=\s*' + param + r'\s*;[ \t]*\n', '', text, count=1)
        # the trailing argument in the register's own position goes, and the callee's prototype loses it
        callees = []
        arity = {}

        real = []

        def drop(m, v=v, callees=callees, arity=arity, real=real, register=int(var)):
            args = m['args']
            parts = [p.strip() for p in args.split(',')]
            if v in parts[:-1] or (parts[-1] == v and len(parts) - 1 == register):
                real.append(m['f'])  # in its own register's slot (or not last): really passed
                return m[0]
            if parts[-1] == v:
                callees.append(m['f'])
                arity[m['f']] = len(parts)
                return f"{m['f']}({', '.join(parts[:-1])})"
            return m[0]
        text = re.sub(r'(?P<f>' + IDENT + r')\((?P<args>[^()]*(?:\([^()]*\)[^()]*)*)\)', drop, text)
        if re.search(r'(?<![\w.>])' + v + r'\b', re.sub(r'(?m)^[ \t]*[\w ]+?[\s*]+' + v + r'\s*;', '', text)):
            continue
        if not callees or real:
            continue
        text = re.sub(r'(?m)^[ \t]*[\w ]+?[\s*]+' + v + r'\s*;[ \t]*\n', '', text, count=1)
        whole = source[:opening] + text + source[end:]
        outside_ok = True
        for callee in set(callees):
            proto = re.search(r'(?m)^(?P<head>[^\n;{}]*\b' + callee + r'\s*\()(?P<params>[^()]*)\)\s*;', whole[:span[0]])
            if not proto:
                continue
            ps = [p.strip() for p in proto['params'].split(',')]
            if len(ps) != arity.get(callee):
                outside_ok = False
                break
            whole = whole[:proto.start('params')] + ', '.join(ps[:-1]) + whole[proto.end('params'):]
        if outside_ok and whole != source:
            result.append((FAMILY, whole))
    return result
