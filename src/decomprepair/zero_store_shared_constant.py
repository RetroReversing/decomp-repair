"""A store of `0` where the target stores the register that also holds another store's constant.

Borrowed or adapted C can carry the wrong constant in one store: a flag byte stored as `0` where the game stores `1`.
The score then differs only in registers, because the compiler shares one `li $a0, 1` between the stores of `1` (the
target's `sb $a0, %lo(G)($at)` and `sb $a0, 0x70($v0)`) while the draft stores `$zero` for the second and keeps the first
in `$v0` (a 20-instruction reset routine, KMC GCC 2.7.2 `-O2 -G0 -mips3 -mgp32 -mfp32`, 15 with
`field = 0;` and exact with `field = 1;`, the draft's four register rows being the only symptom).

The evidence is the target's own stores, counted per constant: `z_t` stores of `$zero`, and for each constant K
loaded with `addiu $r, $zero, K` (or `ori`) the number `k_t` of stores of the register that holds it. The source's
stores of a literal (`LHS = 0;` and `LHS = K;` to anything that is not a plain local of the function: a global, a field
through `M2C_FIELD`, a pointer or array element) are counted the same way, `z_s` and `k_s`. When the source stores `0`
more often than the target does (`z_s > z_t`) and the target stores K more often than the source does (`k_t > k_s`),
each `0` store is offered as a `K` store, one child per store and per K (K with the larger surplus first, at most
8 children). A hypothesis like every other family's: it changes what the code does, the judge decides, and it is
offered only with the target's assembly.
"""
import re

from .case_temporary_repairs import DECLARATION
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'zero_store_shared_constant'
FAMILIES = (FAMILY,)
LIMIT = 8
NUM = r'-?(?:0[xX][0-9a-fA-F]+|\d+)'
LINE = re.compile(r'^\s*(?:/\*.*?\*/\s*)?(?P<op>[a-z][\w.]*)\s+(?P<args>[^#\n]*)$', re.M)
LOAD = re.compile(rf'^\$(?P<rd>\w+)\s*,\s*\$zero\s*,\s*(?P<k>{NUM})\s*$')
STORE = re.compile(r'^\$(?P<rt>\w+)\s*,')
STORES = ('sb', 'sh', 'sw')
NO_DEST = {'sb', 'sh', 'sw', 'swc1', 'sd', 'beq', 'bne', 'beql', 'bnel', 'bgez', 'bgtz', 'blez', 'bltz', 'j', 'jr', 'nop'}
LITERAL_STORE = re.compile(rf'(?m)(?:^|(?<=[;{{}}]))(?P<lead>[ \t]*)(?P<lhs>[^;{{}}=\n]+?)\s*=\s*(?P<k>{NUM})[uUlL]*\s*;')


def target_stores(asm):
    """(zero stores, {constant: stores of the register holding it}) read from the target's listing."""
    held, zero, per = {}, 0, {}
    for m in LINE.finditer(asm):
        op, args = m['op'], m['args'].strip()
        if op in STORES:
            hit = STORE.match(args)
            if hit and hit['rt'] == 'zero':
                zero += 1
            elif hit and hit['rt'] in held:
                per[held[hit['rt']]] = per.get(held[hit['rt']], 0) + 1
            continue
        if op in ('addiu', 'ori', 'addi', 'daddiu'):
            hit = LOAD.match(args)
            if hit:
                held[hit['rd']] = int(hit['k'], 0)
                continue
        if op in NO_DEST or op.startswith('b') or op.startswith('j'):
            if op in ('jal', 'jalr'):
                held = {r: k for r, k in held.items() if r.startswith('s')}
            continue
        reg = re.match(r'\$(\w+)', args)
        if reg:
            held.pop(reg.group(1), None)
    return zero, per


def variants(source, name, asm=''):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    zero_t, per_t = target_stores(asm)
    if not per_t:
        return []
    locals_ = {m['name'] for m in DECLARATION.finditer(clean, opening + 1, end)}
    locals_ |= set(re.findall(r'[A-Za-z_]\w*', clean[span[0]:opening]))
    zero_sites, per_s = [], {}
    for m in LITERAL_STORE.finditer(clean, opening + 1, end):
        lhs = m['lhs'].strip()
        if re.fullmatch(r'[A-Za-z_]\w*', lhs) and lhs in locals_:
            continue
        if re.match(r'(?:return|goto|else|case|default)\b', lhs) or lhs.startswith(('#', '/')):
            continue
        k = int(m['k'], 0)
        if k == 0:
            zero_sites.append(m)
        else:
            per_s[k] = per_s.get(k, 0) + 1
    if len(zero_sites) <= zero_t:
        return []
    wanted = sorted(((per_t[k] - per_s.get(k, 0), k) for k in per_t if per_t[k] > per_s.get(k, 0)), reverse=True)
    out = []
    for _, k in wanted:
        for m in zero_sites:
            text = source[:m.start('k')] + (hex(k) if abs(k) > 9 else str(k)) + source[m.end('k'):]
            out.append((FAMILY, text))
    return [(f, t) for f, t in out if t != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 60}
