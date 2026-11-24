"""A float local cast to an integer inside float arithmetic or a float comparison, written without the cast.

`((s32) d) < best` or `y - (((int) d) * n)` with `d` an `f32` local truncates `d` (`trunc.w.s`, `mfc1`, `mtc1`,
`cvt.s.w`) where the target has none: no game wrote it, a search kept it because it moved registers. Each such cast
dropped is a child, and one child drops them all.

A float range test `(d >= 0.0f) && (d < best)` that m2c wrote with `&&` compiles to two flag-setting `c.*.s` with
`li 1`/`move 0` and an `and` in this compiler when the operands are plain locals (spilled_invariant_repairs), where the
target branches twice (`bc1f`, `bc1f`, the store of `d` in the first delay slot); the search's cast had hidden that by
making one operand a conversion. So the last child drops every cast and also nests every such range test
(`if (d >= 0.0f) { if (d < best) ... }`). A 1928-instruction collision sweep (KMC gcc 2.7.2): dropping the casts alone
16965 -> 18040, nesting alone 14885, both 13995. One function; the judge decides.
"""
import re

from .csource import _blank, find

FAMILY = 'float_truncation_cast_drop'
COMBINED = 'float_truncation_cast_drop_nest'
FAMILIES = (FAMILY, COMBINED)

I = r'[A-Za-z_]\w*'
INT = r'(?:s32|int|long|signed|signed\s+int|u32|unsigned|unsigned\s+int)'
ARITH = r'(?:[<>]=?|==|!=|[-+*/])'


def _floats(text):
    return set(re.findall(r'(?m)^[ \t]*(?:register\s+)?(?:f32|float)\s+(' + I + r')\s*;', text))


def _casts(body, floats):
    """Spans of `((INT) x)` with x a float local, next to an arithmetic or comparison operator."""
    out = []
    for m in re.finditer(r'\(\s*\(\s*' + INT + r'\s*\)\s*(' + I + r')\s*\)', body):
        if m[1] not in floats:
            continue
        before = body[:m.start()].rstrip()
        after = body[m.end():].lstrip()
        if re.search(ARITH + r'$', before) or re.match(ARITH, after):
            out.append((m.start(), m.end(), m[1]))
    return out


def _drop(body, casts):
    for start, end, name in sorted(casts, reverse=True):
        body = body[:start] + name + body[end:]
    return body


def _nest_ranges(body):
    """Every `if ((v >= K) && (v < w)) {..}` without an else written as two nested ifs."""
    rx = re.compile(r'if \(\((' + I + r') >= ([^()&|]+)\) && \((?:\1 < (' + I + r')|(' + I + r') > \1)\)\)(\s*)\{')
    pos = 0
    while True:
        m = rx.search(body, pos)
        if not m:
            return body
        brace = m.end() - 1
        depth = 0
        for k in range(brace, len(body)):
            depth += body[k] == '{'
            depth -= body[k] == '}'
            if depth == 0:
                break
        if re.match(r'\s*else\b', body[k + 1:]):
            pos = m.end()
            continue
        bound = m[3] or m[4]
        indent = re.match(r'[ \t]*', body[body.rfind('\n', 0, m.start()) + 1:])[0]
        new = 'if (%s >= %s)\n%s{\n%s  if (%s < %s)%s{%s}\n%s}' % (
            m[1], m[2].strip(), indent, indent, m[1], bound, m[5], body[brace + 1:k], indent)
        body = body[:m.start()] + new + body[k + 1:]
        pos = m.start() + len('if (')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    body = source[opening:span[1]]
    floats = _floats(body) | set(re.findall(r'\b(?:f32|float)\s+(' + I + r')\s*[,)]', source[span[0]:opening]))
    casts = _casts(body, floats)
    if not casts:
        return []
    wrap = lambda text: source[:opening] + text + source[span[1]:]  # noqa: E731
    out = []
    if len(casts) > 1:
        out.append((FAMILY, wrap(_drop(body, casts))))
    nested = _nest_ranges(_drop(body, casts))
    if nested != _drop(body, casts):
        out.insert(0, (COMBINED, wrap(nested)))
    out += [(FAMILY, wrap(_drop(body, [c]))) for c in casts[:6]]
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
