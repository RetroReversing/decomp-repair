"""A float parameter in the prototype of a callee m2c declared without parameters.

m2c declares a callee it knows nothing about as `f32 func_800828D0();`. With no prototype, C promotes a float
argument to double, so gcc 2.7.2 converts it (`cvt.d.s $f12`) where the game passed the float as it was. Two N64
functions were 88% and 75% so, and exact with `f32 func_800828D0(f32);`: one also with its own parameter, passed only
to that callee, declared `f32` (the game's `mtc1`/`mov.s` moves had said so), the other once m2c's flag became a
direct `return` (flag_returns).
"""
import re

from . import m2cfix
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'float_prototype'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
FLOATS = ('f32', 'float')


def _declared_types(text):
    """Each name declared in `text` (parameters, locals) and its type."""
    types = {}
    for m in re.finditer(r'(?:^|[,(;{]\s*)\s*((?:unsigned\s+|signed\s+|const\s+)?' + IDENT + r')((?:\s*\*)*)\s*(' + IDENT
                         + r')\s*(?=[,;)=\[])', text, re.M):
        if m[1] not in ('return', 'goto', 'case', 'else', 'do', 'sizeof'):
            types[m[3]] = m[1] + m[2].replace(' ', '')
    return types


def _argument_type(arg, types):
    arg = arg.strip()
    cast = re.match(r'\(\s*(f32|float|f64|double)\s*\)', arg)
    if cast:
        return 'f32' if cast[1] in FLOATS else 'f64'
    if re.fullmatch(r'-?\d+\.\d*(?:[eE][-+]?\d+)?f', arg):
        return 'f32'
    if re.fullmatch(IDENT, arg):
        return types.get(arg)
    return None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    outside = clean[:span[0]]
    signature = clean[span[0]:opening]
    params_text = signature[signature.rfind('(') + 1:signature.rfind(')')]
    params = _declared_types('(' + params_text + ')')
    types = {**params, **_declared_types(clean[opening:end])}
    result = []
    for decl in re.finditer(r'(?m)^[ \t]*((?:extern\s+)?(?:unsigned\s+|signed\s+)?' + IDENT + r'(?:\s*\*)*)\s*(' + IDENT
                            + r')\s*\(\s*\)\s*;', outside):
        callee = decl[2]
        calls = []
        for call in re.finditer(r'\b' + callee + r'\s*\(', clean[opening:end]):
            paren = opening + call.end() - 1
            closing = close(clean, paren)
            inner = clean[paren + 1:closing - 1]
            calls.append([a.strip() for a in m2cfix._split_top_level(inner)] if inner.strip() else [])
        if not calls or len({len(c) for c in calls}) != 1 or not calls[0]:
            continue
        arity = len(calls[0])
        kinds, promote = [], []
        for i in range(arity):
            seen = {_argument_type(c[i], types) for c in calls}
            if seen & {'f64', 'double'}:
                break
            if seen & set(FLOATS):
                kinds.append('f32')
                # where other calls pass a float, the caller's own integer parameter passed there is one too when
                # nothing else uses it (second proposal)
                promote.extend(c[i] for c in calls if re.fullmatch(IDENT, c[i]) and c[i] in params
                               and (params[c[i]] or '').startswith(('s32', 'int', 'u32')))
            else:
                kinds.append(types.get(calls[0][i]) if re.fullmatch(IDENT, calls[0][i]) and types.get(calls[0][i]) else 's32')
        else:
            if 'f32' not in kinds:
                continue
            at = decl.start(2)
            paren = clean.find('(', at)
            proto = source[:paren + 1] + ', '.join(kinds) + source[clean.find(')', paren):]
            result.append((FAMILY, proto))
            uses = clean[opening:end]
            mine = [p for p in dict.fromkeys(promote)
                    if len(re.findall(r'(?<![\w.>])' + p + r'\b', uses)) == sum(c.count(p) for c in calls)]
            if mine:
                floated = proto
                for p in mine:
                    floated = _retype_param(floated, name, p, 'f32')
                for i, k in enumerate(kinds):
                    if any(c[i] in mine for c in calls):
                        kinds[i] = 'f32'
                paren = _blank(floated).find('(', decl.start(2))
                floated = floated[:paren + 1] + ', '.join(kinds) + floated[_blank(floated).find(')', paren):]
                result.append((FAMILY, floated))
    return result[:4]


def _retype_param(source, name, param, kind):
    span = find(source, name)
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    head = source[span[0]:opening]
    head = re.sub(r'(?:unsigned\s+|signed\s+)?' + IDENT + r'\s+' + param + r'\b', f'{kind} {param}', head, count=1)
    return source[:span[0]] + head + source[opening:]
