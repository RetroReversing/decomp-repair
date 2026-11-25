"""A float field advanced by a call's result: `F = F + call(F) * k;` split so GCC 2.7.2 allocates the field after the product.

KMC GCC 2.7.2 (N64) gives the registers of a straight-line float chain by the priority of each *quantity*
(`floor_log2(refs) * refs / live length`, local-alloc.c), and a sum ties to its first operand. In
`F = (call(F) * k) + F` the sum ties to the product, which takes `$f0`. The target of a small angle-step function
wrote `lwc1 $f2, F; add.s $f2, $f2, $f0` instead: the product in `$f0`, the field re-read after the call in `$f2`, the
sum in the field's register. No spelling of the one-line expression gives it (twenty tried: operand order, `+=`,
locals, casts, `(f32)` of the call), because the line's two loads and the product are scheduled in an order that gives
the field-and-sum quantity the higher priority. What matched (score 10 -> 0) was the call result in a local, the
product in its own `do { } while (0)` (a scheduling boundary: the field's load stays after it, the product keeps
`$f0`), then the field in a local and the sum written field first:

    d = call(F);  do { t = d * k; } while (0);  v = F;  F = v + t;

The same two edits without the boundary (`d = ...; t = d * k; v = F; F = v + t;`) are proposed too, since they matched
other shapes of the pair. For a single-statement wrapper, also try capturing the initial field read,
scoping the call and product together, and updating the field with `+=`. Only MIPS (the GCC scheduler), only a float field read twice with the same text, only a
call multiplied by something. The candidate is never a verdict: the judge decides.
"""
import re

from .csource import _blank, find
from .scheduling_scope import _ID, _statements

FAMILY = 'float_sum_split'
FAMILIES = (FAMILY,)
_FLOAT = re.compile(r'\b(f32|float|f64|double)\s*\*\s*[,)]')


def _norm(text):
    return re.sub(r'\s+', '', text)


def _top_level(text, ch):
    """Indexes of `ch` at bracket depth 0 (a `==`, `+=`, `++` is not one)."""
    depth, out = 0, []
    for i, c in enumerate(text):
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        elif c == ch and depth == 0:
            before, after = text[i - 1:i], text[i + 1:i + 2]
            if ch == '=' and (before in '=!<>+-*/%&|^' or after == '='):
                continue
            if ch == '+' and (before == '+' or after in '+='):
                continue
            out.append(i)
    return out


def _python_strip_parens(text):
    text = text.strip()
    while text.startswith('(') and text.endswith(')'):
        depth = 0
        for i, c in enumerate(text):
            depth += (c == '(') - (c == ')')
            if depth == 0 and i < len(text) - 1:
                return text
        text = text[1:-1].strip()
    return text


_strip_parens = _python_strip_parens
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _strip_parens(text):
        found = _scan.unwrap_parens(text)
        return _python_strip_parens(text) if found is NotImplemented else found


def _product(term):
    """(call text, other factor) of `call(...) * y` or `y * call(...)`, else None."""
    term = _strip_parens(term)
    stars = _top_level(term, '*')
    if len(stars) != 1:
        return None
    left, right = term[:stars[0]].strip(), term[stars[0] + 1:].strip()
    for call, other in ((left, right), (right, left)):
        call = re.sub(r'^\(\s*(?:f32|float|s32|int)\s*\)\s*', '', _strip_parens(call))
        hit = re.fullmatch(rf'({_ID})\s*\(.*\)', call, re.S)
        if hit and _top_level(other, '(') == [] and not re.search(rf'\b{_ID}\s*\(', other.replace('(f32)', '')):
            return call, other, hit[1]
    return None


def _return_type(source, upto, callee):
    hit = re.search(rf'(?m)^\s*((?:(?:unsigned|signed)\s+)?{_ID})\s+{callee}\s*\(', source[:upto])
    return hit[1] if hit and hit[1] not in ('return', 'else') else 's32'


def _captured_field_update(clean, opening, closing, start, stop, lvalue, call, factor, kind, indent):
    """Capture the first read used as a cast argument and reload for the compound update."""
    if clean[opening + 1:start].strip() or clean[stop:closing].strip() or kind not in ('f32', 'float'):
        return None
    field = re.fullmatch(rf'M2C_FIELD\(\s*{_ID}\s*,\s*(?:f32|float)\s*\*\s*,\s*(?:0x[0-9a-fA-F]+|\d+)\s*\)', lvalue)
    argument = re.fullmatch(rf'(?P<callee>{_ID})\s*\(\s*\(\s*(?P<cast>s32|int)\s*\)\s*(?P<field>.+)\)', call)
    if (not field or not argument or _norm(argument['field']) != _norm(lvalue)
            or not re.fullmatch(rf'(?:\(\s*(?:float|f32)\s*\)\s*)?{_ID}', factor)):
        return None
    return ('\n' + indent).join((
        f'{kind} v_split = {lvalue};',
        f'{kind} t_split;',
        f'do {{ t_split = ({argument["callee"]}(({argument["cast"]}) v_split) * {factor}); }} while (0);',
        f'{lvalue} += t_split;',
    ))


def variants(source, name, arch='mips', asm='', header=''):
    if arch != 'mips':
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'\bvolatile\b', clean[span[0]:span[1]]):
        return []
    out = []
    for a, b in _statements(clean, opening, closing):
        text = clean[a:b - 1]
        eq = _top_level(text, '=')
        if len(eq) != 1:
            continue
        lvalue, rhs = text[:eq[0]].strip(), _strip_parens(text[eq[0] + 1:])
        kind = _FLOAT.search(lvalue)
        plus = _top_level(rhs, '+')
        if not kind or len(plus) != 1 or '(' not in lvalue:
            continue
        left, right = rhs[:plus[0]].strip(), rhs[plus[0] + 1:].strip()
        for same, other in ((left, right), (right, left)):
            product = _product(other)
            if _norm(same) != _norm(lvalue) or not product or _norm(lvalue) not in _norm(product[0]):
                continue
            call, factor, callee = product
            t = kind[1]
            temps = {k: n for k in 'dvt' if not re.search(rf'\b(?:{k}_split)\b', source)
                     for n in (f'{k}_split',)}
            if len(temps) != 3:
                continue
            d, v, w = temps['d'], temps['v'], temps['t']
            decl = f'{_return_type(source, span[0], callee)} {d}; {t} {v}; {t} {w};'
            indent = source[source.rfind('\n', 0, a) + 1:a]
            indent = indent if not indent.strip() else '    '
            captured = _captured_field_update(clean, opening, closing, a, b, lvalue, call, factor, t, indent)
            if captured and _norm(_strip_parens(other)).startswith(_norm(call) + "*"):
                out.append((FAMILY, source[:a] + captured + source[b:]))
            for scoped in (True, False):
                prod = f'{w} = {d} * {factor};'
                lines = [f'{d} = {call};', f'do {{ {prod} }} while (0);' if scoped else prod,
                         f'{v} = {lvalue};', f'{lvalue} = {v} + {w};']
                body = ('\n' + indent).join(lines)
                src = source[:a] + body + source[b:]
                open_at = src.index('{', find(src, name)[0])
                src = src[:open_at + 1] + f'\n    {decl}' + src[open_at + 1:]
                out.append((FAMILY, src))
            break
    return [x for x in out if x[1] != source]
