"""A clamp whose two values meet in one store, written as the inverted test with the store in each arm.

    if (t > K) { v = C; } else { v = t << 15; }
    p->f = v;
becomes
    if (t <= K) { p->f = t << 15; } else { p->f = C; }

KMC GCC 2.7.2: the arm that computes falls through first and the constant arm is last before the join, so the insn
before the store's label is the constant, not the shift. Jump2 (jump.c) cross-jumps an unconditional jump first
against the insns before its label: another command's clamp that also ends `v = t << 15; j L` (an earlier arm with the
same shift) no longer merges into this one's shift, and keeps its own `j; sll` as the target has it. The store in each
arm makes the two values block-local, so they take `$v0` instead of the `$a0` a multi-set value variable got, and the
two identical store tails cross-jump back into one. Either part alone did not pay in a 1315-instruction
sound-sequence interpreter (inverted alone 1260, stores alone 995); together 995 -> 785. The cross-jump order is read
from jump.c; the register choice is a hypothesis. Proposals only; the compiler and the byte judge decide."""
import re

from .csource import find

FAMILIES = ('inverted_clamp_store_arms',)

_INVERT = {'>': '<=', '<': '>=', '>=': '<', '<=': '>', '==': '!=', '!=': '=='}

_PAT = re.compile(
    r'(\n[ \t]*)if \((\w+) (>=|<=|==|!=|>|<) ([^()\n]+)\)\s*\{\s*(\w+) = ([^;\n]+);\s*\}\s*else\s*\{\s*\5 = ([^;\n]+);'
    r'\s*\}(\s*\{?\s*)(\*\(\([^;\n]*?\)\)|\w+(?:->\w+|\[[^\]\n]+\])*) = \5;')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    s, e = span
    body = source[s:e]
    out = []
    for m in _PAT.finditer(body):
        ind, t, op, k, v, first, second, gap, dest = m.groups()
        if re.search(r'\b%s\b' % re.escape(v), body[m.end():]):
            continue
        new = '%sif (%s %s %s)%s{%s  %s = %s;%s}%selse%s{%s  %s = %s;%s}%s' % (
            ind, t, _INVERT[op], k, ind, ind, dest, second, ind, ind, ind, ind, dest, first, ind, gap.rstrip(' \t'))
        out.append((FAMILIES[0], source[:s] + body[:m.start()] + new + body[m.end():] + source[e:]))
    return out[:6]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
