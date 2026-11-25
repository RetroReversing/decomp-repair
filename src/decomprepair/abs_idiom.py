"""A hand-written absolute value (`v = x; if (v < 0) { v = -v; }`) as the C library's `abs()`.

m2c writes the integer `abs` it reads from the target as a copy and a conditional negation:

    var_v0 = (s32) (a - b);
    if (var_v0 < 0) { var_v0 = -var_v0; }

GCC 2.8 (SN and KMC, MIPS) compiles that to `bgez` + a copied register + `negu`, and `abs(x)` to the other layout the
target usually has: `bltzl $v0, L` with the `negu $v0, $v0` in its delay slot (the branch-likely's own copy of the negate),
which needs no register copy. The match needs `int abs(int);` and `v = abs(expr)` (or `abs(v)` for a bare `if`). A function
with several such tests may need only some of them as calls (a matched game function wrote the first as `abs(dx)` and the
second as `(dz < 0) ? -dz : dz`), so besides the child that rewrites every site there is one per site (the whole family is
capped at eight children).

The shapes (the assigned variable an integer: `s32`, `int`, `s16`, `u16`, `s8`, `u8`, declared in the function or a parameter):
- `V = EXPR; if (V < 0) { V = -V; }`, and the same with `if (EXPR < 0)` when EXPR is one name (a temporary m2c copied);
- the bare `if (V < 0) { V = -V; }` as `V = abs(V);`.
Gated on the target's assembly: a `negu` (or `subu rd, $zero, rs`) must be there, since a function that never negates cannot
be an absolute value. `int abs(int);` is added in front of the function when neither the source nor the header declares
`abs`."""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view

FAMILY = 'abs_idiom'
FAMILIES = (FAMILY, FAMILY + '_one')

INTEGERS = r'(?:s8|u8|s16|u16|s32|u32|int|short|char|unsigned\s+(?:int|short|char)|signed\s+(?:int|short|char))'
SET = re.compile(rf'(?m)^(?P<lead>[ \t]*)(?P<var>{IDENT})\s*=\s*(?P<expr>[^;{{}}]+?)\s*;[ \t]*\n[ \t]*'
                 rf'if\s*\(\s*(?P<test>[^;{{}}]+?)\s*<\s*0\s*\)\s*\{{\s*(?P=var)\s*=\s*-\s*(?P=var)\s*;\s*\}}(?!\s*else\b)')
BARE = re.compile(rf'(?m)^(?P<lead>[ \t]*)if\s*\(\s*(?P<var>{IDENT})\s*<\s*0\s*\)\s*\{{\s*(?P=var)\s*=\s*-\s*(?P=var)\s*;\s*\}}'
                  rf'(?!\s*else\b)')
MAX_ONE = 7


def negates(asm):
    """Whether the target negates an integer: `negu`, or `subu`/`sub` from `$zero`."""
    for line in (asm or '').splitlines():
        hit = re.search(r'\*/\s*(?P<op>[a-z.]+)\s+(?P<args>[^\n]*)$', line)
        if not hit:
            continue
        op, args = hit['op'], [a.strip() for a in hit['args'].split(',')]
        if op in ('negu', 'neg') or (op in ('subu', 'sub') and len(args) == 3 and args[1] == '$zero'):
            return True
    return False


def _is_integer(part, var, top):
    """Whether `var` is declared an integer (not a pointer or a float) in the function or its parameters."""
    return re.search(rf'\b{INTEGERS}\s+{re.escape(var)}\s*[;,=)\[]', part.clean[top:part.end]) is not None


def _sites(part, top):
    found, taken = [], []
    for hit in SET.finditer(part.clean, part.opening, part.end):
        expr, test = hit['expr'].strip(), hit['test'].strip()
        if test not in (hit['var'], expr) or not _is_integer(part, hit['var'], top):
            continue
        found.append((hit.start(), hit.end(), f'{hit["lead"]}{hit["var"]} = abs({expr});'))
        taken.append((hit.start(), hit.end()))
    for hit in BARE.finditer(part.clean, part.opening, part.end):
        if any(a <= hit.start() < b for a, b in taken) or not _is_integer(part, hit['var'], top):
            continue
        found.append((hit.start(), hit.end(), f'{hit["lead"]}{hit["var"]} = abs({hit["var"]});'))
    return sorted(found)


def _declared(source, header):
    return re.search(r'(?m)^[ \t]*(?:extern[ \t]+)?(?:int|s32)[ \t]+abs\s*\(', source + '\n' + (header or '')) is not None


def variants(source, name, asm, header=''):
    if not negates(asm):
        return []
    part = view(source, name)
    if not part:
        return []
    top = find(source, name)[0]
    top = source.rfind('\n', 0, top) + 1
    sites = _sites(part, top)
    if not sites:
        return []
    proto = [] if _declared(source, header) else [(top, top, 'int abs(int);\n')]
    out = [(FAMILY, edit(source, [(a, b, text) for a, b, text in sites] + proto))]
    if len(sites) > 1:
        for a, b, text in sites[:MAX_ONE]:
            out.append((FAMILY + '_one', edit(source, [(a, b, text)] + proto)))
    return out


# Not declared: the library runs this repair from its rule, rules/abs_idiom.json (rules.py), which tests/test_rules.py
# checks gives this function's children for every case here. Kept as the hand-written reference until the rule has run
# for a release; delete it with its test then.
