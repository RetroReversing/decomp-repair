"""A scaled operand one arm of an `if`/`else` passes to its call, computed before the branch.

m2c writes each arm's call arguments where the arm uses them: `if (hi) { rect(g, s4, t * 8, ...); } else { rect(g, s4,
t * 4, ...); }`. The game computed the operands it passes in both layouts before it chose one (`uly = t * 4;` above the
`if`, the high-resolution arm using `t * 8` of its own): the same instructions in a different place, and a different
order for the scheduler and a different pseudo for the allocator. On a 315-instruction tile-rectangle builder staging the
one arm's `t * 4` before the branch was 655 -> 185, and with `scaled_copy_in_place` 0 (the scaled bounds written back
into their variables).

`variants` finds an `if (c) { ... } else { ... }` (not an `else if`, no assignment in `c`) whose arms each have a
statement-level call to the same function, takes an argument of one arm's call of the form `v * K` or `v << K` where `v` is
a plain local integer that the other arm's call also names (in an argument of its own) and that the arm does not assign
before the call, and writes it as a new local assigned above the `if`:

    staged = v * K;  if (c) { call(..., v * 8, ...); } else { call(..., staged, ...); }

One proposal per such argument (at most 4), and one with every such argument of the `if` staged. The local has the type of
`v`. A hypothesis about the compiler's choice; the exact judge decides."""
import re

from .compiler_phase_repairs import fresh
from .integer_repair_support import edit, split_args, view
from .pattern_repairs import close

FAMILY = 'arm_operand_pre_stage'
FAMILIES = (FAMILY,)
LIMIT = 4

_ID = r'[A-Za-z_]\w*'
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
_INTEGER = r'(?:unsigned\s+(?:char|short|int|long)|signed\s+(?:char|short|int|long)|[su](?:8|16|32|64)|char|short|int|long)'
_IF = re.compile(r'\bif\s*\(')
_CALL = re.compile(rf'(?m)^[ \t]*(?P<f>{_ID})\s*\(')
_SCALED = re.compile(rf'(?P<v>{_ID})\s*(?P<op>\*|<<)\s*(?P<k>{_NUMBER})')


def _arm(clean, at):
    """(open, end) of the brace block starting at the first non-space character from `at`, or None."""
    while at < len(clean) and clean[at].isspace():
        at += 1
    if at >= len(clean) or clean[at] != '{':
        return None
    end = close(clean, at, '{', '}')
    return (at, end) if end else None


def _call(clean, arm):
    """(function, [(start, end) of each argument], statement start) of the first statement-level call in the arm."""
    for hit in _CALL.finditer(clean, arm[0] + 1, arm[1]):
        if hit['f'] in ('if', 'while', 'for', 'switch', 'return', 'sizeof'):
            continue
        opening = hit.end() - 1
        ending = close(clean, opening, '(', ')')
        if ending is None or clean[ending:].lstrip()[:1] != ';':
            continue
        spans = [(opening + 1 + a, opening + 1 + b) for a, b in split_args(clean[opening + 1:ending - 1])]
        return hit['f'], spans, hit.start()
    return None


def _type_of(clean, opening, name):
    hit = re.search(rf'(?m)^[ \t]*(?:register[ \t]+)?(?P<t>{_INTEGER})[ \t]+{re.escape(name)}[ \t]*;', clean[opening:])
    return ' '.join(hit['t'].split()) if hit else None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, opening, end = part.clean, part.opening, part.end
    sites = []
    for hit in _IF.finditer(clean, opening + 1, end):
        if re.search(r'\belse\s*$', clean[opening:hit.start()]):
            continue
        condition_end = close(clean, hit.end() - 1, '(', ')')
        if condition_end is None:
            continue
        condition = clean[hit.end():condition_end - 1]
        if re.search(r'(?<![=!<>])=(?!=)|\+\+|--', condition):
            continue
        first = _arm(clean, condition_end)
        if first is None:
            continue
        rest = re.match(r'\s*else\b', clean[first[1]:])
        second = _arm(clean, first[1] + rest.end()) if rest else None
        if second is None:
            continue
        calls = [_call(clean, first), _call(clean, second)]
        if None in calls or calls[0][0] != calls[1][0]:
            continue
        for arm, other, mine, theirs in ((first, second, calls[0], calls[1]), (second, first, calls[1], calls[0])):
            other_names = set()
            for a, b in theirs[1]:
                other_names |= set(re.findall(_ID, clean[a:b]))
            for a, b in mine[1]:
                scaled = _SCALED.fullmatch(clean[a:b].strip())
                if not scaled or scaled['v'] not in other_names:
                    continue
                kind = _type_of(clean, opening, scaled['v'])
                prefix = clean[arm[0]:mine[2]]
                if kind is None or re.search(rf'(?<![\w.]){re.escape(scaled["v"])}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(scaled["v"])}', prefix):
                    continue
                sites.append((hit.start(), a, b, scaled, kind))
    if not sites:
        return []
    sites = sites[:LIMIT]
    out = []
    groups = [sites] if len(sites) > 1 else []
    groups += [[site] for site in sites]
    for group in groups:
        taken = []
        edits = []
        text = source
        declarations = []
        statements = {}
        for at, a, b, scaled, kind in group:
            stem = fresh(text + ''.join(declarations), header, f'staged_{scaled["v"]}')
            declarations.append(f' {stem} ')
            edits.append((a + (len(clean[a:b]) - len(clean[a:b].lstrip())), b - (len(clean[a:b]) - len(clean[a:b].rstrip())), stem))
            statements.setdefault(at, []).append(f'{stem} = {scaled["v"]} {scaled["op"]} {scaled["k"]};')
            taken.append(f'{kind} {stem};')
        for at, lines in statements.items():
            edits.append((at, at, ' '.join(lines) + ' '))
        edits.append((opening + 1, opening + 1, '\n    ' + '\n    '.join(taken)))
        out.append((FAMILY, edit(source, edits)))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 99}  # the registry: no caller wiring (registry.py)
