"""A store of an expression around a call's result (`G = (f((H + 7) & ~7) + 7) & ~7;`) written through one local that
holds the computed argument first and the result after: `x = (H + 7) & ~7; x = (f(x) + 7) & ~7; G = x;`.

gcc 2.7.2's local-alloc ties an insn's output to a first operand that dies there, so the `and` that builds the
argument straight into `$a0` pulls the sum (and the load before it) into `$a0` too. One local set twice is a pseudo
with two deaths: global.c allocates it, before local-alloc and in the lowest free register, so the load and the sum go
to `$v0` and only the `and` writes `$a0`. On an N64 function (KMC GCC 2.7.2, `-O1 -g`, 34 instructions; an allocator
aligning its pool) the target's `lui $v0; lw $v0; addiu $v0, 7; ...; and $a0, $v0, $s0` came only that way (20 -> 0):
the argument staged in a local of its own, or the result alone through a local, both stayed at 20, as did a dozen
spellings of the expression, its types and the callee's prototype.

call_argument_result_local
    `LHS = E;` (a statement, one call `f(..., A, ...)` in E with A an expression that is not a lone name or number,
    no other call, assignment or increment in E) becomes `x = A; x = E[A := x]; LHS = x;` with `s32 x;` declared at
    the top of the function (the global's or local's own integer type when the source declares one). One child per
    such argument, at most four. The judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, split_args, view
from .pattern_repairs import close

FAMILY = 'call_argument_result_local'
FAMILIES = (FAMILY,)
LIMIT = 4
INTEGER = r'(?:(?:un)?signed\s+)?(?:char|short|int|long)|[su](?:8|16|32)'
STATEMENT = re.compile(r'(?<=[;{}])(?P<indent>\s*)(?P<lhs>' + IDENT + r'(?:\s*\[[^\];]*\])?)\s*=(?!=)\s*(?P<e>[^;{}]+);')
KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'do', 'else', 'case'}


def _name(clean):
    for candidate in ('temp', 'carry', 'value', 'staged'):
        if not re.search(rf'\b{candidate}\b', clean):
            return candidate
    return None


def _type(clean, lhs):
    base = re.match(IDENT, lhs)[0]
    hit = re.search(rf'(?m)^\s*(?:extern\s+|static\s+)?({INTEGER})\s+{base}\s*(?:\[[^\]]*\])?\s*[;=]', clean)
    return ' '.join(hit[1].split()) if hit else 's32'


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b|^\s*#', part.body, re.M):
        return []
    local = _name(part.clean)
    if not local:
        return []
    out = []
    body_start = part.opening + 1
    for hit in STATEMENT.finditer(part.clean, body_start, part.end - 1):
        expression = hit['e']
        if re.search(r'\+\+|--|(?<![=!<>])=(?!=)|\?|,(?![^()]*\))', expression):
            continue
        callees = [c for c in re.finditer(r'(?<![\w.>])(' + IDENT + r')\s*\(', expression) if c[1] not in KEYWORDS
                   and not re.fullmatch(INTEGER, c[1])]
        if len(callees) != 1:
            continue
        open_at = hit.start('e') + callees[0].end() - 1
        end = close(part.clean, open_at, '(', ')')
        if not end:
            continue
        inside = part.clean[open_at + 1:end - 1]
        for a, b in split_args(inside):
            argument = inside[a:b].strip()
            if not argument or re.fullmatch(IDENT + r'|(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*|"[^"]*"', argument):
                continue
            start = open_at + 1 + a + (len(inside[a:b]) - len(inside[a:b].lstrip()))
            stop = start + len(argument)
            kind = _type(part.clean, hit['lhs'])
            indent = hit['indent']
            written = (source[hit.start('e'):start] + local + source[stop:hit.end('e')]).strip()
            lhs = source[hit.start('lhs'):hit.end('lhs')]
            replacement = (f'{indent}{local} = {source[start:stop]};{indent}{local} = {written};'
                           f'{indent}{lhs} = {local};')
            out.append(edit(source, [(body_start, body_start, f'\n    {kind} {local};'),
                                     (hit.start(), hit.end(), replacement)]))
            if len(out) == LIMIT:
                break
        if len(out) >= LIMIT:
            break
    return [(FAMILY, child) for child in dict.fromkeys(out) if child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
