"""A later arm of an `if` / `else if` chain that compares a value with a constant, comparing it with zero instead.

A twin function (or a draft) gives a chain `if (v == 4) .. else if (v == 1) ..`; the target of this one compiles the
second test as a reload of `v` and a `beqz`, where the candidate loads the constant and `beq`s. The two differ in
instruction count, so a literal search over aligned immediates never sees it, and a chain of one edit at a time
reaches it only if every such arm is changed (each alone is worse when two chains share the shape). Measured on an N64
function (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`) adapted from its matched twin: 1200 -> 0 with the two second
arms of its two chains changed together. The exact judge decides which constant the game used.

Offered for an `else if (EXPR == K)` (or `!=`), K not zero, whose chain's first test is on the same EXPR with another
non-zero constant and where no test of the chain compares EXPR with zero: all such arms together first, then each."""
import re

from .integer_repair_support import edit, view

FAMILY = 'else_chain_compare_zero'
FAMILIES = (FAMILY,)
LIMIT = 6

_EXPR = r'[A-Za-z_]\w*(?:(?:\.|->)\w+|\[[^\[\]()]*\])*'
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
_TEST = re.compile(rf'\bif\s*\(\s*(?P<expr>{_EXPR})\s*(?P<op>==|!=)\s*(?P<k>{_NUMBER})\s*\)')


def _zero(text):
    return int(text.rstrip('uUlL'), 0 if text[:2].lower() == '0x' else 10) == 0


def _key(text):
    return re.sub(r'\s', '', text)


def _sites(clean, start, end):
    tests = list(_TEST.finditer(clean, start, end))
    found = []
    for position, test in enumerate(tests):
        if _zero(test['k']) or not re.search(r'\belse\s*$', clean[start:test.start()]):
            continue
        expr = _key(test['expr'])
        # earlier tests of the same expression in the same block: the chain this arm belongs to
        chain = []
        for earlier in tests[:position]:
            if _key(earlier['expr']) != expr:
                continue
            between = clean[earlier.start():test.start()]
            depth, low = 0, 0
            for char in between:
                depth += (char == '{') - (char == '}')
                low = min(low, depth)
            if depth == 0 and low == 0:
                chain.append(earlier)
        if chain and not any(_zero(earlier['k']) for earlier in chain):
            found.append(test)
    return found[:LIMIT]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(part.clean, part.opening, part.end)
    if not sites:
        return []
    groups = [sites] if len(sites) > 1 else []
    groups += [[site] for site in sites]
    out = [(FAMILY, edit(source, [(test.start('k'), test.end('k'), '0') for test in group])) for group in groups]
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 120}  # the registry (registry.py)
