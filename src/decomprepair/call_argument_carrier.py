"""A masked call result, `v = (f(A) + K) & M;`, through one carrier local for the argument and the result.

    temp = (f((G + 0xF) & ~0xF) + 0xF) & ~0xF;
 -> c = (G + 0xF) & ~0xF;
    c = f(c) + 0xF;
    temp = c & ~0xF;

The game aligned a value, passed it, and aligned the call's result again (`ALIGN16`), reusing one variable. Written
inline, the argument's computation dies in the insn that sets `$a0` and local-alloc suggests `$a0` for it (the load
and the add go to `$a0`); the target has `lui $v0; lw $v0; addiu $v0,$v0,0xF; ... and $a0,$v0,$s0`. A carrier set
twice and dying twice is a global pseudo: combine can no longer fold the argument's value into the `$a0` copy and
global.c gives the carrier `$v0`, its preference from the call result. The final mask goes into its own local, so the
value read by the stores after it stays a local quantity (with the carrier itself read by those stores, local-alloc
puts their sums in `$v0` first and the carrier loses it). KMC gcc 2.7.2 `-O1 -g`, an N64 allocator setup of 34
instructions, 20 -> 0; the carrier that kept the `+ K` out of its second set (`c = f(c); v = (c + K) & M;`) stayed
20, and is offered too. Hypothesis from the dumps (`.lreg`/`.greg`) of that function, not a controlled rule.

Offered for an assignment `V = (F(A) OP K) & M;` (OP one of `+ - | ^`) whose call has one argument without a call or
assignment in it. One child per site and form, and one with every site in the first form.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'call_argument_carrier'
FAMILIES = (FAMILY,)
LIMIT = 8
KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof'}
HEAD = re.compile(rf'(?m)^(?P<ind>[ \t]*)(?P<v>{IDENT})\s*=\s*\(\s*(?P<f>{IDENT})\s*\(')
TERM = r'(?:[^;()]|\([^;()]*\))+?'
REST = re.compile(rf'\s*(?P<op>[-+|^])\s*(?P<k>{TERM})\s*\)\s*&\s*(?P<m>{TERM})\s*;')


def _top_level_comma(text):
    depth = 0
    for ch in text:
        depth += ch in '(['
        depth -= ch in ')]'
        if ch == ',' and depth == 0:
            return True
    return False


def _carrier(body):
    name, n = 'carry', 1
    while re.search(rf'\b{name}\b', body):
        n += 1
        name = f'carry{n}'
    return name


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    sites = []
    for hit in HEAD.finditer(clean, part.opening, part.end):
        if hit['f'] in KEYWORDS:
            continue
        call_open = hit.end() - 1
        call_close = close(clean, call_open)
        if not call_close or call_close > part.end:
            continue
        rest = REST.match(clean, call_close)
        arg = source[call_open + 1:call_close - 1].strip()
        if (not rest or not arg or _top_level_comma(arg) or re.search(rf'\b{IDENT}\s*\(|(?<![=!<>])=(?!=)|\+\+|--', arg)
                or re.search(rf'\b{re.escape(hit["v"])}\b', arg)):
            continue
        sites.append((hit, rest, arg))
    if not sites:
        return []
    c = _carrier(clean[part.opening:part.end])
    newline = clean.find('\n', part.opening)
    if newline < 0 or newline > part.end:
        return []
    ind = sites[0][0]['ind'] or '    '
    declaration = (newline + 1, newline + 1, f'{ind}s32 {c};\n')

    def form(site, which):
        hit, rest, arg = site
        i, v, f = hit['ind'], hit['v'], hit['f']
        op, k, m = rest['op'], rest['k'].strip(), rest['m'].strip()
        if which == 0:
            text = f'{c} = {arg};\n{i}{c} = {f}({c}) {op} {k};\n{i}{v} = {c} & {m};'
        else:
            text = f'{c} = {arg};\n{i}{c} = {f}({c});\n{i}{v} = ({c} {op} {k}) & {m};'
        return (hit.start('v'), rest.end(), text)

    out = []
    if len(sites) > 1:
        out.append((FAMILY, edit(source, [declaration] + [form(s, 0) for s in sites])))
    for site in sites:
        for which in (0, 1):
            out.append((FAMILY, edit(source, [declaration, form(site, which)])))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
