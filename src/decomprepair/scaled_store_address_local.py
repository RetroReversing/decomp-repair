"""A byte store at `base[K + (index * S)]`, written as a pointer local holding `base + index * S` and a store through it.

KMC GCC 2.7.2 expands `base[K + index * S]` (a sum with a constant inside, handled with EXPAND_SUM in expr.c) as
`(plus (mult index S) base)` and puts the MULT first ("Put a constant term last and put a multiplication first"),
so the `addu` has the scaled index first: `addu $v0,$v0,$a0`. When the sum is assigned to a pointer local the
expansion takes the plain binary-operation path instead (the modifier is not EXPAND_SUM), which keeps the operands in
the order written, base first: `addu $v0,$a0,$v0`, and the constant becomes the store's displacement. A saved best
that otherwise matched (an index-guarded flag store in a slot table) stood at 20 with this operand order as the only
row besides an allocation difference; the pointer local took it to 15. The compiler-source reading is a hypothesis
that the measurement agrees with; the judge decides each child.

Children (each only when it differs from the source, bounded):
- `scaled_store_address_local`: one qualifying store rewritten, per store;
- `scaled_store_address_local_all`: every qualifying store rewritten, each with its own local.

A qualifying statement starts a block or follows a `;`, is `base[K + (index * S)] = value;` (or the sum in the other
order, or `(index * S) + K`), where `base` is a byte pointer (`u8`, `s8`, `char`) declared in the function, `index` is a
name, `K` and `S` are numbers, and the statement has no call, increment or assignment to `index` or `base`.
"""
import re

from .csource import _blank, find

FAMILY = 'scaled_store_address_local'
FAMILY_ALL = 'scaled_store_address_local_all'
FAMILIES = (FAMILY, FAMILY_ALL)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'0[xX][0-9a-fA-F]+|\d+'
BYTE = r'(?:u8|s8|char|unsigned\s+char|signed\s+char)'
LIMIT = 12


def _sum(text):
    """The (K, index, S) of `K + (index * S)` or `(index * S) + K`, or None."""
    scaled = rf'\(?\s*({IDENT})\s*\*\s*({NUMBER})\s*\)?'
    first = re.fullmatch(rf'\s*({NUMBER})\s*\+\s*{scaled}\s*', text)
    if first:
        return first[1], first[2], first[3]
    second = re.fullmatch(rf'\s*{scaled}\s*\+\s*({NUMBER})\s*', text)
    if second:
        return second[3], second[1], second[2]
    return None


def variants(source, name):
    clean = _blank(source)
    span = find(source, name)
    if not span or re.search(r'\b(?:volatile|asm|__asm__)\b', clean[span[0]:span[1]]):
        return []
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    bases = set(re.findall(rf'\b{BYTE}\s*\*\s*({IDENT})\b', clean[start:end]))
    taken = set(re.findall(IDENT, clean))
    hits = []
    for base in sorted(bases):
        pattern = re.compile(rf'(?<![\w.>])({base})\s*\[(?P<sum>[^\[\];]*)\]\s*=(?!=)\s*(?P<value>[^;{{}}]*);')
        for hit in pattern.finditer(clean, opening, end):
            parts = _sum(hit['sum'])
            if not parts:
                continue
            before = clean[opening:hit.start()].rstrip()
            if before[-1:] not in {'{', ';', '}'}:
                continue
            k, index, scale = parts
            statement = hit.group(0)
            if re.search(rf'\+\+|--|\w\s*\(|\b(?:{re.escape(index)}|{base})\s*[-+*/&|^]?=(?!=)', statement.replace(hit['sum'], '')):
                continue
            hits.append((hit.start(), hit.end(), base, k, index, scale, hit['value'].strip()))
    if not hits:
        return []

    def declare(count):
        names = []
        number = 0
        while len(names) < count:
            number += 1
            candidate = f'addr{number}'
            if candidate not in taken:
                names.append(candidate)
        return names

    def build(chosen):
        names = declare(len(chosen))
        text = source
        for (begin, stop, base, k, index, scale, value), local in sorted(zip(chosen, names), reverse=True):
            text = (text[:begin] + f'{local} = {base} + ({index} * {scale}); {local}[{k}] = {value};' + text[stop:])
        declared = ''.join(f'\n    u8 *{local};' for local in names)
        brace = text.find('{', start)
        return text[:brace + 1] + declared + text[brace + 1:]

    result = []
    for hit in hits[:LIMIT]:
        result.append((FAMILY, build([hit])))
    if len(hits) > 1:
        result.append((FAMILY_ALL, build(hits[:LIMIT])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
