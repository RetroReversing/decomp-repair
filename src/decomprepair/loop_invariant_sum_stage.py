"""A loop's `base + i + K` (a value the loop never assigns, the loop's counter and a literal) written with the invariant
part staged in a local inside the loop: `t = base + K; f(.., i + t, ..)`.

On a 629-instruction N64 level loader (SN64 GCC 2.8.1, `sn-n64-281 -G0 -mips3 -O2 ... -mfp32`) the target adds the
counter to a saved register that holds `base + 1`, set once before the loop (`lw $t1, base_slot; addiu $s0, $t1, 1` in
the preheader, then `addu $a1, $s6, $s0` in the body). Every spelling of the sum in place (`base + i + 1`,
`base + 1 + i`, `i + (base + 1)`) gives the counter's own add instead: the front end folds the literal outward
(`(base + i) + 1`), or cse shares `i + 1` with the counter's increment, so no instruction computes `base + 1` and the
loop pass has nothing to hoist. A user variable set to `base + 1` inside the loop is a loop invariant that loop.c moves
to the preheader, and the sum becomes one add of the counter and the hoisted register: 1060 -> 625, with the loop's
rows exact apart from the scheduler's order.

loop_invariant_sum_stage
    In the body of a `for`/`while` loop, an additive chain of exactly three terms, one an identifier the loop never
    assigns (an integer local or parameter), one a variable the loop assigns and one an integer literal, standing alone
    as an argument, initialiser or right-hand side: a new local of the invariant's type is set to `invariant + K` as the
    statement before, and the chain becomes `counter + local`. One child per chain, and one with every chain.

Hypothesis from that match (loop.c's `scan_loop`: a register set once in the loop from an invariant expression is a
movable); the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'loop_invariant_sum_stage'
FAMILIES = (FAMILY,)
LIMIT = 6
_TERM = rf'(?:{IDENT}|{NUMBER})'
_CHAIN = re.compile(rf'(?<![\w.>\]\)])({_TERM})\s*\+\s*({_TERM})\s*\+\s*({_TERM})(?![\w(\[.])')
_ASSIGNED = r'(?:(?<![\w.>]){0}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+\s*{0}\b|--\s*{0}\b|(?<![\w.>]){0}\s*(?:\+\+|--))'
_KEYWORDS = {'if', 'else', 'for', 'while', 'do', 'return', 'switch', 'case', 'sizeof', 'goto', 'break', 'continue'}


def _assigned(text, ident):
    return re.search(_ASSIGNED.format(re.escape(ident)), text) is not None


def _loops(clean, lo, hi):
    """(header start, body opening, body end) of every braced `for`/`while` loop between lo and hi."""
    for hit in re.finditer(r'\b(?:for|while)\s*\(', clean[:hi]):
        if hit.start() < lo:
            continue
        after = close(clean, hit.end() - 1)
        if not after:
            continue
        brace = re.match(r'\s*{', clean[after:hi])
        if not brace:
            continue
        opening = after + brace.end() - 1
        end = close(clean, opening, '{', '}')
        if end:
            yield hit.start(), opening, end


def _type_of(clean, part, ident):
    head = clean[:part.opening]
    params = head[head.rfind('(') + 1:]
    for text in (params, part.body):
        found = re.findall(rf'(?:^|[;{{}},(])\s*((?:register\s+)?{INTEGER})\s+{re.escape(ident)}\s*(?=[;=,)])', text)
        if len(found) == 1:
            return found[0].replace('register', '').strip()
    return None


def _declaration_end(clean, part):
    """Just past the function's leading declarations (the place a new local joins them)."""
    at = part.opening + 1
    decl = re.compile(rf'\s*(?:(?:const|register|static|struct|union|unsigned|signed)\s+)*{IDENT}[\s*]+{IDENT}'
                      r'(?:\s*\[[^\];]*\])?(?:\s*=[^;{}]*)?\s*;[ \t]*')
    while True:
        hit = decl.match(clean, at, part.end)
        if not hit or hit[0].split()[0] in _KEYWORDS:
            return at
        at = hit.end()


def _fresh(source, base):
    name, n = f'{base}_sum', 1
    while re.search(rf'\b{name}\b', source):
        n += 1
        name = f'{base}_sum{n}'
    return name


def _sites(part):
    clean = part.clean
    sites, seen = [], set()
    for start, opening, end in _loops(clean, part.opening, part.end):
        loop = clean[start:end]
        body_lo, body_hi = opening + 1, end - 1
        for hit in _CHAIN.finditer(clean, body_lo, body_hi):
            if hit.start() in seen:
                continue
            before = clean[body_lo:hit.start()].rstrip()[-1:]
            after = clean[hit.end():body_hi].lstrip()[:1]
            if before not in ('(', ',', '=') or after not in (')', ',', ';'):
                continue
            if before == '=' and clean[:hit.start()].rstrip()[-2:-1] in '=!<>+-*/%&|^':
                continue
            terms = [hit[1], hit[2], hit[3]]
            literals = [t for t in terms if re.fullmatch(NUMBER, t)]
            names = [t for t in terms if t not in literals]
            if len(literals) != 1 or len(names) != 2 or set(names) & _KEYWORDS:
                continue
            varying = [t for t in names if _assigned(loop, t)]
            fixed = [t for t in names if t not in varying]
            if len(varying) != 1 or len(fixed) != 1:
                continue
            kind = _type_of(clean, part, fixed[0])
            if kind is None or _type_of(clean, part, varying[0]) is None:
                continue
            statement = max(clean.rfind(c, body_lo - 1, hit.start()) for c in ';{}') + 1
            if re.match(r'\s*(?:else|case|default)\b', clean[statement:hit.start()]):
                continue
            if clean[statement:hit.start()].count('(') - clean[statement:hit.start()].count(')') < 0:
                continue
            begin = statement + len(clean[statement:hit.start()]) - len(clean[statement:hit.start()].lstrip())
            line = clean.rfind('\n', 0, begin) + 1
            own_line = not clean[line:begin].strip()
            seen.add(hit.start())
            sites.append((hit, fixed[0], varying[0], literals[0], kind, line if own_line else begin, own_line))
    return sites


def _child(source, part, chosen):
    edits, declared = [], []
    taken = source
    for hit, fixed, varying, literal, kind, at, own_line in chosen:
        name = _fresh(taken, fixed)
        taken += f' {name} '
        if own_line:
            indent = re.match(r'[ \t]*', source[at:])[0]
            edits.append((at, at, f'{indent}{name} = {fixed} + {literal};\n'))
        else:
            edits.append((at, at, f'{name} = {fixed} + {literal}; '))
        edits.append((hit.start(), hit.end(), f'{varying} + {name}'))
        declared.append(f'{kind} {name};')
    at = _declaration_end(part.clean, part)
    indent = re.search(r'\n([ \t]*)\S', source[part.opening:at + 1] + '\n    x')
    pad = indent[1] if indent else '    '
    edits.append((at, at, ''.join(f'\n{pad}{text}' for text in declared)))
    return edit(source, edits)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(part)
    out = [(FAMILY, _child(source, part, [site])) for site in sites[:LIMIT]]
    if len(sites) > 1:
        out.append((FAMILY, _child(source, part, sites[:LIMIT])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
