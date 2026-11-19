"""m2c's compare tree for a small `switch`, written back as the `switch`.

gcc builds a `switch` of a few cases as a tree of compares; m2c reads it back as nested `if`s on the value:

    if (t != 0xA5) {
        if (t < 0xA6) {
            if (t != 0xA3) { return 1U; }
            return A;
        }
        if (t != 0xA6) { return 1U; }
        return B;
    }
    return C;

An N64 function was 71% so and exact as `switch (t) { case 0xA5: return C; case 0xA6: return B; case 0xA3:
return A; } return 1U;` -- the bodies in the reverse of m2c's order (the order the compiler laid them out; m2c walks
the tree). Every leaf must return; each is a case when the path to it fixes the value with `==`, else the default, and
all defaults must return the same. The case order is offered as m2c's, reversed and ascending.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'compare_tree_switch'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
COMPARE = re.compile(r'\s*(?P<x>' + IDENT + r')\s*(?P<op>==|!=|<=|>=|<|>)\s*(?P<k>' + NUMBER + r')\s*$')
NEGATE = {'==': '!=', '!=': '==', '<': '>=', '>=': '<', '>': '<=', '<=': '>'}


def _leaves(source, clean, start, stop, facts, out):
    """Each `return` in clean[start:stop] with the comparisons that reach it; False when the shape isn't a tree."""
    text = clean[start:stop]
    lead = len(text) - len(text.lstrip())
    at = start + lead
    if at >= stop:
        return False
    ret = re.match(r'return\s+([^;]+);\s*$', clean[at:stop])
    if ret:
        out.append((facts, source[at + ret.start(1):at + ret.end(1)].strip()))
        return True
    head = re.match(r'if\s*\(', clean[at:stop])
    if not head:
        return False
    cond_open = at + head.end() - 1
    cond_close = close(clean, cond_open)
    compare = COMPARE.match(clean[cond_open + 1:cond_close - 1]) if cond_close else None
    brace = re.match(r'\s*\{', clean[cond_close:stop]) if compare else None
    if not brace:
        return False
    then_open = cond_close + brace.end() - 1
    then_close = close(clean, then_open, '{', '}')
    if not then_close:
        return False
    fact = (compare['x'], compare['op'], int(re.sub(r'[uUlL]+$', '', compare['k']), 0))
    if not _leaves(source, clean, then_open + 1, then_close - 1, facts + [fact], out):
        return False
    other = re.match(r'\s*else\s*\{', clean[then_close:stop])
    negated = (fact[0], NEGATE[fact[1]], fact[2])
    if other:
        else_open = then_close + other.end() - 1
        else_close = close(clean, else_open, '{', '}')
        if not else_close or clean[else_close:stop].strip():
            return False
        return _leaves(source, clean, else_open + 1, else_close - 1, facts + [negated], out)
    return _leaves(source, clean, then_close, stop, facts + [negated], out)


def _variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening + 1:end - 1]
    tree = None
    for m in re.finditer(r'(?m)^[ \t]*if\s*\(', body):
        # the tree is the function's last statement: everything after its first `if`
        leaves = []
        if _leaves(source, clean, opening + 1 + m.start(), end - 1, [], leaves):
            tree = (opening + 1 + m.start(), leaves)
            break
        # (only the first top-level `if` is tried: an earlier statement may be part of nothing)
        break
    if not tree:
        return []
    start, leaves = tree
    names = {f[0] for facts, _ in leaves for f in facts}
    if len(names) != 1 or len(leaves) < 3:
        return []
    var = names.pop()
    cases, defaults = {}, []
    for facts, expr in leaves:
        values = {k for _, op, k in facts if op == '=='}
        if len(values) > 1:
            return []
        if values:
            k = values.pop()
            if k in cases:
                return []
            cases[k] = expr
        else:
            defaults.append(expr)
    if len(cases) < 2 or len({' '.join(d.split()) for d in defaults}) > 1:
        return []
    default = defaults[0] if defaults else None
    indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:])[0]
    order = list(cases)
    result = []
    for keys in (order[::-1], order, sorted(order)):
        lines = [f'{indent}switch ({var}) {{\n']
        for k in keys:
            lines.append(f'{indent}case 0x{k:X}:\n{indent}    return {cases[k]};\n')
        lines.append(f'{indent}}}\n')
        if default is not None:
            lines.append(f'{indent}return {default};\n')
        text = source[:start] + ''.join(lines) + source[end - 1:]
        if text not in [t for _, t in result]:
            result.append((FAMILY, text))
    return result


# a leaf that carries its constant through m2c's variable: `v = K; if (c) { return D; } return v;` (after its duplicate-
# return comment), or plainly `v = K; return v;`
CARRIED = re.compile(r'(?m)^(?P<i>[ \t]*)(?P<v>' + IDENT + r') = (?P<k>-?' + NUMBER + r');[ \t]*\n'
                     r'(?P<guard>[ \t]*if \([^\n]*\) \{[ \t]*\n[ \t]*return [^;\n]+;[ \t]*\n[ \t]*\}[ \t]*\n)?'
                     r'(?:[ \t]*/\*[^\n]*\*/[ \t]*\n)?[ \t]*return (?P=v);')


def _direct(source):
    """Such leaves as direct returns, and the variable's declaration gone when nothing else names it."""
    text = CARRIED.sub(lambda m: (m['guard'] or '') + m['i'] + 'return ' + m['k'] + ';', source)
    if text == source:
        return source
    for var in {m['v'] for m in CARRIED.finditer(source)}:
        if len(re.findall(r'\b' + var + r'\b', _blank(text))) == 1:
            text = re.sub(r'(?m)^[ \t]*[\w ]+?\s+' + var + r'\s*;[ \t]*\n', '', text, count=1)
    return text


def variants(source, name):
    """m2c's compare tree as a `switch`; leaves that carry their constant through a variable read as direct returns (an
    N64 function's tree, `var_v0 = 4; if (arg0 != 0x10) { return 0; } return var_v0;`, was exact as a `switch` that
    returns 4, at 18.6% as m2c wrote it)."""
    found = _variants(source, name)
    direct = _direct(source)
    if direct != source:
        found += [(f, t) for f, t in _variants(direct, name) if t not in [x for _, x in found]]
    return found
