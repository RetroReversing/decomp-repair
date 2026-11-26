"""A commutative accumulate written into a separate destination, so the call result (or the new term) stays first.

m2c writes a running sum as `acc += f(x);`. The original's add had the new term as its FIRST operand, `addu $s2,$v0,$s2`,
and the compiler gives `acc += f(x)` (and `acc = acc + f(x)`, and `acc = f(x) + acc`) the accumulator first,
`addu $s2,$s2,$v0`: one row of the difference per accumulate, and no operand order of the same statement moves it.
Hypothesis read from gcc's `optabs.c` (`expand_binop`): a commutative operation whose destination is its own operand
swaps the operands to put that one first; with a destination of its own the order written is kept. The spelling that
matched (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, two small N64 string-width loops, 5 -> 0 and 20 -> 15 -> 0) is a
temporary declared right after the accumulator:

    s32 acc;  s32 temp_v0;  ...  temp_v0 = f(x) + acc;  acc = temp_v0;       (was `acc += f(x);`)

Respelled: a statement `acc += E;`, `acc = acc + E;` or `acc = E + acc;` (and the same with `*`, `&`, `|`, `^`) where
`acc` is an integer local declared in the function and `E` does not mention it and assigns nothing. One child per site
and operand order (`E op acc`, the order that matched, and `acc op E`), each with the temporary declared right after the
accumulator's declaration; every site together; and the declaration at the end of the declaration block instead
(declaration order moved registers in the matched function). A candidate rewrite; the exact judge decides.
"""
import re

from . import shift_pair_return_cast
from .integer_repair_support import DECL, IDENT, edit, view

FAMILY = 'accumulate_separate_dest'
FAMILIES = (FAMILY,)
LIMIT = 8
OPS = r'[+*&|^]'
ATOM = re.compile(r'[\w.]+(?:\((?:[^()]|\([^()]*\))*\))?')

COMPOUND = re.compile(rf'(?<=[;{{}}])\s*(?P<acc>{IDENT})\s*(?P<op>{OPS})=\s*(?P<e>[^;{{}}]+?)\s*;')
LEFT = re.compile(rf'(?<=[;{{}}])\s*(?P<acc>{IDENT})\s*=(?!=)\s*(?P=acc)\s*(?P<op>{OPS})\s*(?P<e>[^;{{}}]+?)\s*;')
RIGHT = re.compile(rf'(?<=[;{{}}])\s*(?P<acc>{IDENT})\s*=(?!=)\s*(?P<e>[^;{{}}]+?)\s*(?P<op>{OPS})\s*(?P=acc)\s*;')
PLAIN_LINE = re.compile(r'[ \t]*(?:unsigned |signed |struct |const )*\w+[ \t*]+\**\w+(?:\[\w*\])?[ \t]*;[ \t]*$')


def _binary(expr):
    flat = expr
    while True:
        inner = re.sub(r'\([^()]*\)|\[[^\[\]]*\]', '', flat)
        if inner == flat:
            break
        flat = inner
    return bool(re.search(r'[-+*/%&|^<>=?:!~,]', flat))


def _paren(expr):
    return expr if ATOM.fullmatch(expr) else f'({expr})'


def _sites(clean, start, end, accs):
    found = {}
    for pattern, kind in ((COMPOUND, 'c'), (LEFT, 'l'), (RIGHT, 'r')):
        for hit in pattern.finditer(clean, start, end):
            acc, expr = hit['acc'], hit['e'].strip()
            if acc not in accs or re.search(rf'(?<![\w.>]){re.escape(acc)}\b', expr):
                continue
            if re.search(r'[^=!<>]=[^=]|\+\+|--', expr):
                continue
            if kind != 'c' and _binary(expr):
                continue  # `acc = acc * a + b` is not `acc * (a + b)`: a bare operand only
            found[hit.start('acc')] = (hit.start('acc'), hit.end(), acc, hit['op'], expr)
    return [found[key] for key in sorted(found)]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    first = source.find('\n', part.opening) + 1
    # the end of the declaration block: the run of plain `type name;` lines that opens the body
    block_end, at = first, first
    while at < part.end:
        line_end = source.find('\n', at)
        line = source[at:line_end if line_end >= 0 else part.end]
        if PLAIN_LINE.fullmatch(line):
            block_end = line_end + 1
            at = block_end
        elif not line.strip():
            at = line_end + 1
        else:
            break
    accs = {hit['name']: (hit['type'], hit.end()) for hit in DECL.finditer(clean, first, block_end)}
    if not accs:
        return []
    sites = _sites(clean, block_end, part.end, accs)[:LIMIT]
    if not sites:
        return []
    taken = set(re.findall(IDENT, clean))
    names = []
    for number, site in enumerate(sites):
        fresh = f'sep_{site[2]}{number or ""}'
        while fresh in taken:
            fresh += '_'
        taken.add(fresh)
        names.append(fresh)
    indent = re.match(r'[ \t]*', source[first:])[0] or '  '

    def build(chosen, swapped, where):
        edits = []
        for number in chosen:
            start, end, acc, op, expr = sites[number]
            text = f'{names[number]} = {acc} {op} {_paren(expr)}; ' if swapped else f'{names[number]} = {_paren(expr)} {op} {acc}; '
            edits.append((start, end, text + f'{acc} = {names[number]};'))
            decl = f'{indent}{accs[acc][0]} {names[number]};\n'
            if where == 'after':
                after = source.find('\n', accs[acc][1]) + 1
                edits.append((after, after, decl))
            else:
                edits.append((block_end, block_end, decl))
        return edit(source, edits)

    out = []

    def add(result):
        if result != source and (FAMILY, result) not in out:
            out.append((FAMILY, result))

    everyone = list(range(len(sites)))
    for swapped in (False, True):
        for number in everyone:
            add(build([number], swapped, 'after'))
        if len(everyone) > 1:
            add(build(everyone, swapped, 'after'))
    # steps that only pay off together: the accumulate, then the shift-pair return as the cast it was (20 -> 15 -> 0)
    for _, together in list(out):
        for _, tail in shift_pair_return_cast.variants(together, name):
            add(tail)
    add(build(everyone, False, 'end'))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 89}  # the registry: no caller wiring
