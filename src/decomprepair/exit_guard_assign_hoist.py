"""A value computed just after an early exit, computed before it: `if (c == 0) { goto out; } n = c + 8;` becomes
`n = c + 8; if (c == 0) { goto out; }`.

When the target's branch for the exit has the computation in its delay slot, the game's source may have had it above the
test: the branch is then the last insn before the slot, the store the source had before it stays before the branch, and
reorg takes the computation. Written below the test, SN GCC 2.8.1 (N64, `-G0 -mips3 -O2`) fills the slot with the store
and keeps the computation after. Measured on one 165-instruction LZ unpacker: 180 -> 120. The reorg account is a
hypothesis from the target's and the compiled order; the judge decides.

The move is made only when it cannot change the program: the guard's body is one `goto` or `return`, the assigned name is
a plain local whose address is never taken, the expression has no call, memory read or side effect, and the local is dead
on the exit path (`local_flow` liveness at the `goto`'s label; a `return` that doesn't name it).
"""
import re

from . import local_flow
from .integer_repair_support import IDENT, edit, view

FAMILY = 'exit_guard_assign_hoist'
FAMILIES = (FAMILY,)
LIMIT = 8
GUARD = re.compile(
    rf'(?<=[;{{}}])\s*(?P<guard>if\s*\((?P<test>[^(){{}};]*)\)\s*\{{\s*(?P<exit>goto\s+(?P<label>{IDENT})|return\b(?P<value>[^;{{}}]*))\s*;\s*\}})'
    rf'(?P<space>\s*)(?P<assign>(?P<dest>{IDENT})\s*=(?!=)\s*(?P<rhs>[^;{{}}=]+);)')
PURE = re.compile(rf'(?:\s|{IDENT}|0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*|<<|>>|[+\-*&|^~()])+')


def _pure(rhs):
    """No call, dereference, address, increment or assignment: only names, integers and plain operators."""
    text = rhs.strip()
    if not PURE.fullmatch(text) or '++' in text or '--' in text:
        return False
    if re.search(rf'{IDENT}\s*\(', text):
        return False
    # a unary `*` or `&` starts the expression or follows another operator or `(`
    return not re.search(r'(?:^|[+\-*&|^~(]|<<|>>)\s*[*&]', text)


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b|^\s*#', part.body, re.M):
        return []
    hits = list(GUARD.finditer(part.clean, part.opening, part.end))
    if not hits:
        return []
    flow = local_flow.analyze(source, name)
    if flow is None:
        return []
    sites = []
    for hit in hits:
        dest = hit['dest']
        if dest not in flow.names or not _pure(hit['rhs']) or re.search(r'\+\+|--|=(?!=)', hit['test'].replace('==', '')
                                                                       .replace('!=', '').replace('<=', '').replace('>=', '')):
            continue
        if re.search(rf'\b{dest}\b', hit['test']):
            continue
        if hit['label']:
            index = flow.labels.get(hit['label'])
            if index is None or dest in flow.nodes[index].live:
                continue
        elif re.search(rf'\b{dest}\b', hit['value']):
            continue
        sites.append(hit)

    def build(chosen):
        edits = []
        for hit in chosen:
            line = source.rfind('\n', 0, hit.start('guard')) + 1
            indent = source[line:hit.start('guard')]
            between = '\n' + indent if not indent.strip() else ' '
            edits.append((hit.start('guard'), hit.end('assign'),
                          source[hit.start('assign'):hit.end('assign')] + between + source[hit.start('guard'):hit.end('guard')]))
        return edit(source, edits)

    results = []
    for chosen in ([sites] if len(sites) > 1 else []) + [[site] for site in sites]:
        if not chosen:
            continue
        text = build(chosen)
        if (FAMILY, text) not in results:
            results.append((FAMILY, text))
        if len(results) >= LIMIT:
            break
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}
