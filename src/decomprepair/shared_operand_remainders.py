"""Remainders (or quotients) of one variable by different constants, named in locals before the statements that use them.

`a = 0xFF - (G % 144) * 4; b = 0xFF - (G % 36) * 6;` against `m144 = G % 144; m36 = G % 36; a = 0xFF - m144 * 4;
b = 0xFF - m36 * 6;`. On SN64 GCC 2.8.1 (N64, `-O2`) both remainders come from one `mult` by the magic `0x38E38E39`
(`mfhi >> 5` for 144, `>> 3` for 36), and the target finished both remainders before either outer expression
(`0xFF - m * 4` after the second remainder): written inline, each statement's arithmetic is expanded whole, so the
first one's `sll`/`subu` comes between the two remainder chains and every register of the shared chain moves. Named in
fresh locals assigned one after the other, the remainders are expanded first and the outer expressions after them,
as the target has it. A 194-instruction HUD drawer went 450 -> 105 (`-mfp32`; 475 -> 130 under its own profile) by
this one edit, where staging the outer expression (`a = G % 144; ...; a = 0xFF - a * 4`, reusing the result
variable) scored 435-850 and reusing other locals of the function for the remainders 395-1345: the locals must be
new ones, used nowhere else. Hypothesis (not confirmed in the compiler's source): fresh single-set user variables keep
the remainders as separate statements through expansion and the first scheduler's order, while a reused variable is
multi-set and is ranked differently.

Children, for two or more adjacent assignment statements of one block that each read exactly one
`(V % K)` or `(V / K)` with the same variable `V` (a parameter, local or global declared as an integer, not assigned by
those statements) and integer literals `K`: every such operation named in a fresh local (`rem144`, `quo10`) declared at
the top of the function, assigned in the statements' order just before the first of them; and the same with the
assignments in the other order. Only MIPS; the candidate is never a verdict, the judge decides.
"""
import re

from .csource import _blank, find

FAMILY = 'shared_operand_remainders'
FAMILIES = (FAMILY,)
_ID = r'[A-Za-z_]\w*'
_NUMBER = r'0[xX][0-9A-Fa-f]+|\d+'
_STATEMENT = re.compile(rf'(?<=[;{{}}])(\s*)({_ID})\s*=\s*([^;{{}}=]+);')
_OPERATION = re.compile(rf'\(\s*({_ID})\s*([%/])\s*({_NUMBER})\s*\)')
_SIGNED = ('s32', 'int', 'signed', 's16', 's8', 'short', 'char', 'long')
_UNSIGNED = ('u32', 'unsigned', 'u16', 'u8')
_LIMIT = 8


def _type(text, var):
    """The local type for an operation on `var` (`s32` or `u32`), from its declaration in `text`, else None."""
    words = '|'.join(_SIGNED + _UNSIGNED)
    hit = re.search(rf'\b((?:(?:extern|static|volatile|const|register)\s+)*)((?:{words})(?:\s+(?:{words}))*)\s+'
                    rf'(?:{_ID}\s*(?:\[[^\]]*\])?\s*(?:=[^,;]*)?,\s*)*{var}\s*[;,=)]', text)
    if not hit or 'volatile' in hit[1]:
        return None
    return 'u32' if any(w in hit[2].split() for w in _UNSIGNED) and 'signed' not in hit[2].split() else 's32'


def _groups(clean, lo, hi):
    """Runs of adjacent statements [(start, end, var, [(op_start, op_end, op, k), ...] per statement)]."""
    runs, run, last_end = [], [], None
    for hit in _STATEMENT.finditer(clean, lo, hi):
        ops = list(_OPERATION.finditer(hit[3]))
        base = hit.start(3)
        ok = len(ops) == 1 and hit[2] != ops[0][1]
        adjacent = last_end is not None and not clean[last_end:hit.start()].strip()
        if not ok:
            if len(run) > 1:
                runs.append(run)
            run, last_end = [], hit.end()
            continue
        op = ops[0]
        item = (hit.start(2), hit.end(), op[1], hit[2], base + op.start(), base + op.end(), op[2], op[3])
        if run and adjacent and run[0][2] == op[1] and all(r[3] != op[1] for r in run):
            run.append(item)
        else:
            if len(run) > 1:
                runs.append(run)
            run = [item]
        last_end = hit.end()
    if len(run) > 1:
        runs.append(run)
    return runs


def _fresh(text, stem, taken):
    name, n = stem, 1
    while re.search(rf'\b{name}\b', text) or name in taken:
        n += 1
        name = f'{stem}_{n}'
    taken.add(name)
    return name


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    out = []
    for run in _groups(clean, opening + 1, span[1])[:_LIMIT]:
        var = run[0][2]
        if len({(r[6], int(r[7], 0)) for r in run}) < 2:  # one operation twice is cse's own business
            continue
        kind = _type(clean[span[0]:span[1]], var) or _type(_blank(source[:span[0]]), var) or _type(header or '', var)
        if not kind:
            continue
        taken, names = set(), []
        for r in run:
            names.append(_fresh(source, ('rem' if r[6] == '%' else 'quo') + str(int(r[7], 0)), taken))
        indent = clean[:run[0][0]].rsplit('\n', 1)[-1]
        sets = [f'{n} = {var} {r[6]} {r[7]};' for n, r in zip(names, run)]
        body = source
        for r, n in sorted(zip(run, names), key=lambda x: x[0][4], reverse=True):
            body = body[:r[4]] + n + body[r[5]:]
        decl_at = opening + 1
        decls = ''.join(f'\n    {kind} {n};' for n in names)
        for order in (sets, sets[::-1]):
            child = body[:run[0][0]] + ('\n' + indent).join(order) + '\n' + indent + body[run[0][0]:]
            child = child[:decl_at] + decls + child[decl_at:]
            if child != source:
                out.append((FAMILY, child))
    seen, unique = set(), []
    for fam, src in out:
        if src not in seen:
            seen.add(src)
            unique.append((fam, src))
    return unique


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
