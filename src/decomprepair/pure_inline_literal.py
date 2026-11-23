"""A pure one-line inline helper called on a literal, written as the literal it computes.

A search or a draft chain leaves `inline static int inline_fn(int arg0) { return -arg0; }` in the source and writes
`D = inline_fn(1);` where the game wrote `D = -1;`. The helper changes nothing the judge can see on its own, but it
does hide the constant from cse in one place and not in another: a `-1` that reaches `state` through the call and a
`-1` stored to two halfword globals through the call all share one register, while the game kept the stores' `-1`
in a register of its own (a `sh $v0` beside the `$s0` that holds `state`). Written as literals the stores load their
own constant and the prologue's order follows. A bounded step on a `gcc-2.7.2-kmc` save-slot reset function (455 with
the calls, 345 with only the stores' calls written out, then the rest were weights and operand order).

Offered when the source defines `[static] [inline] T f(T a) { return EXPR; }` (one parameter, EXPR made only of the
parameter, integer literals and `+ - * ~ << >> & | ^` with parentheses and integer casts) and a function calls `f`
with an integer literal. One child folds every such call in the function (`pure_inline_literal`); the helper itself
stays unless no call of it is left anywhere, in which case it goes too. A hypothesis about how the game spelled the
constant; the exact judge decides.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'pure_inline_literal'
FAMILIES = (FAMILY,)

HELPER = re.compile(
    rf'(?m)^[ \t]*(?:(?:static|inline|__inline__|__inline)[ \t]+)+(?P<ret>[A-Za-z_][\w \t\*]*?)[ \t]+(?P<name>{IDENT})'
    rf'\(\s*(?P<ptype>[A-Za-z_][\w \t]*?)\s+(?P<param>{IDENT})\s*\)\s*\{{\s*return\s+(?P<expr>[^;{{}}]+);\s*\}}[ \t]*\n?')
NUMBER = re.compile(r'0[xX][0-9a-fA-F]+|[0-9]+')
CAST = re.compile(r'\(\s*(?:unsigned\s+)?(?:u|s)?(?:8|16|32|char|short|int)\s*\)')
LITERAL = re.compile(r'\s*(?P<sign>[-+]?)\s*(?P<num>0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*\s*')
WIDTH = {'u8': (8, False), 's8': (8, True), 'u16': (16, False), 's16': (16, True), 'u32': (32, False), 's32': (32, True),
         'char': (8, True), 'short': (16, True), 'int': (32, True), 'unsigned char': (8, False),
         'unsigned short': (16, False), 'unsigned int': (32, False), 'signed char': (8, True),
         'signed short': (16, True), 'signed int': (32, True)}


def _wrap(value, spelling):
    spelling = re.sub(r'\s+', ' ', spelling.strip())
    bits, signed = WIDTH.get(spelling, (32, True))
    value &= (1 << bits) - 1
    return value - (1 << bits) if signed and value >> (bits - 1) else value


def _evaluate(expr, param, value, ptype):
    """EXPR with PARAM = VALUE under 32-bit integer arithmetic, or None when it uses anything else."""
    for cast in CAST.findall(expr):
        spelled = re.sub(r'[()\s]', ' ', cast).strip()
        if spelled not in WIDTH:
            return None
    stripped = CAST.sub(' ', expr)
    tokens = re.findall(rf'{IDENT}|0[xX][0-9a-fA-F]+[uUlL]*|[0-9]+[uUlL]*|<<|>>|[-+*~&|^()]|\S', stripped)
    for token in tokens:
        if re.fullmatch(IDENT, token):
            if token != param:
                return None
        elif not (re.fullmatch(r'0[xX][0-9a-fA-F]+[uUlL]*|[0-9]+[uUlL]*', token) or token in '+-*~&|^()' or token in ('<<', '>>')):
            return None
    python = re.sub(r'(0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*', r'\1', stripped)
    python = re.sub(rf'\b{re.escape(param)}\b', str(value), python)
    try:
        result = eval(python, {'__builtins__': {}}, {})  # only integers and operators survive the check above
    except Exception:
        return None
    if not isinstance(result, int):
        return None
    return _wrap(result, ptype)


def helpers(clean):
    found = {}
    for m in HELPER.finditer(clean):
        found[m['name']] = m
    return found


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    table = helpers(part.clean)
    if not table:
        return []
    body = part.clean[part.opening:part.end]
    edits, used = [], set()
    for helper, m in table.items():
        call = re.compile(rf'(?<![\w.]){re.escape(helper)}\s*\(\s*(?P<arg>[-+]?\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*)\s*\)')
        for hit in call.finditer(body):
            lit = LITERAL.fullmatch(hit['arg'])
            if not lit:
                continue
            number = int(lit['num'].rstrip('uUlL'), 0) * (-1 if lit['sign'] == '-' else 1)
            result = _evaluate(m['expr'], m['param'], number, m['ptype'])
            if result is None:
                continue
            before = body[:hit.start()].rstrip()
            text = str(result)
            if result < 0 and before[-1:] in ('-', '+', '*', '/', '%', '&', '|', '^', '<', '>'):
                text = f'({result})'
            edits.append((part.opening + hit.start(), part.opening + hit.end(), text))
            used.add(helper)
    if not edits:
        return []
    out = edit(source, edits)
    # a helper nothing calls any more goes with its calls
    for helper in used:
        text = _blank(out)
        m = helpers(text).get(helper)
        if m and not re.search(rf'(?<![\w.]){re.escape(helper)}\s*\(', text[:m.start()] + text[m.end():]):
            out = out[:m.start()] + out[m.end():]
    return [(FAMILY, out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
