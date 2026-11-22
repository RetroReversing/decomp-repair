"""A run of byte stores around one symbol, written through a base pointer that cse cannot fold back into the symbol.

KMC GCC 2.7.2 keeps a symbol's address in a register for a run of `sb $zero,-3($v0)` ... `sb $v1,5($v0)` stores
(`lui $v0` + `addiu $v0,$v0,%lo(sym)` once) only when the pointer is not a known constant at cse. Every plain form of
the source (`M2C_FIELD(&sym, s8 *, k)`, `((u8 *)&sym)[k]`, a pointer local set to `&sym`) lets cse substitute the
constant back, because `sym + k` costs one `lui $at` and a store with a `%lo(sym+k)` offset, and the base register
dies: nine stores became nine `lui $at` / `sb` pairs, 4400 against a target that keeps the base. Only a base whose
value cse cannot see makes the register survive; the source has to supply a term that is zero but that only the
combiner can prove zero.

The term here is `(byte_global >> 8)`: a byte load is `(zero_extend:SI (mem:QI ..))`, cse does not track nonzero bits,
so the sum `&sym + (byte >> 8)` stays a computation; the combiner (nonzero_bits) then reduces the shift to zero, the load
dies, and the base is the plain `lui`/`addiu` pair every store addresses (the target's exact code, 4400 -> 0, in a
state-reset function of 46 instructions). Two earlier spellings of the same idea, `(&sym + n) - n` over a word global
and over a pointer, also keep the register but leave an unused stack slot (an 8 byte frame): the load there is used
twice, and combine's use count for the pseudo stays above zero, so reload gives the dead pseudo a frame slot. A single
use of the byte (the shift) lets combine zero the count.

The rewrite is two edits that only pay off together (the base pointer alone folds back, the opaque term alone has no
store to reach it): the stores of one symbol become `base[k] = value;` and `base` is declared first as
`u8 *base = (u8 *)&sym + (byte >> 8);`.

Evidence: when the target's assembly is given, it must show the shape: an `addiu $r,$r,%lo(sym)` followed by at least
three byte stores off that register. A caller that passes no assembly does not run the family.

Children (bounded):
- `opaque_symbol_base`: the symbol's stores (the symbol with most) rewritten, per byte global that can carry the term.

Qualifying statements: `M2C_FIELD(&sym, T *, k) = v;` and `(*(T *)((T *)&sym + (k))) = v;`, `T` a byte type, `k` a
number, at least four of them for one symbol. A function with `volatile` or inline `asm` is left alone.
"""
import re

from .csource import _blank, find

FAMILY = 'opaque_symbol_base'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?\s*(?:0[xX][0-9a-fA-F]+|\d+)'
BYTE = r'(?:u8|s8|char|unsigned\s+char|signed\s+char)'
MINIMUM = 4
CARRIERS = 3

_FIELD = re.compile(rf'M2C_FIELD\s*\(\s*&\s*(?P<sym>{IDENT})\s*,\s*(?P<type>{BYTE})\s*\*\s*,\s*\(?\s*(?P<k>{NUMBER})\s*\)?\s*\)'
                    rf'\s*=(?!=)\s*(?P<value>[^;{{}}]*);')
_CAST = re.compile(rf'\(\s*\*\s*\(\s*(?P<type>{BYTE})\s*\*\s*\)\s*\(\s*\(\s*{BYTE}\s*\*\s*\)\s*&\s*(?P<sym>{IDENT})'
                   rf'\s*\+\s*\(?\s*(?P<k>{NUMBER})\s*\)?\s*\)\s*\)\s*=(?!=)\s*(?P<value>[^;{{}}]*);')
_EXTERN_BYTE = re.compile(rf'(?m)^[ \t]*extern\s+(?P<type>{BYTE})\s+(?P<name>{IDENT})\s*;')


def _number(text):
    return int(re.sub(r'\s+', '', text), 0)


def _shows_a_base(asm, symbol):
    """Whether the target keeps one register as the symbol's base for three or more byte stores."""
    for found in re.finditer(rf'addiu\s+(\$\w+),\s*\1,\s*%lo\({re.escape(symbol)}\)', asm):
        register = re.escape(found[1])
        after = asm[found.end():]
        stores = re.findall(rf'\bsb\s+\$\w+,\s*-?(?:0x)?[0-9a-fA-F]+\({register}\)', after)
        if len(stores) >= 3:
            return True
    return False


def variants(source, name, asm):
    clean = _blank(source)
    span = find(source, name)
    if not span or re.search(r'\b(?:volatile|asm|__asm__)\b', clean[span[0]:span[1]]):
        return []
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    groups = {}
    for pattern in (_FIELD, _CAST):
        for hit in pattern.finditer(clean, opening, end):
            before = clean[opening:hit.start()].rstrip()
            if before[-1:] not in {'{', ';', '}'} or re.search(r'\w\s*\(|\+\+|--', hit['value']):
                continue
            groups.setdefault(hit['sym'], []).append((hit.start(), hit.end(), _number(hit['k']), hit['value'].strip()))
    ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    if not ranked or len(ranked[0][1]) < MINIMUM:
        return []
    symbol, stores = ranked[0]
    if not asm or not _shows_a_base(asm, symbol):
        return []
    if len({k for _, _, k, _ in stores}) < 3:
        return []
    taken = set(re.findall(IDENT, clean))
    carriers = [(m['type'], m['name']) for m in _EXTERN_BYTE.finditer(clean) if m['name'] != symbol]
    # a carrier the function does not already use goes first: any byte global works, the load is deleted
    used = set(re.findall(IDENT, clean[opening:end]))
    carriers.sort(key=lambda item: item[1] in used)
    local = 'base'
    while local in taken:
        local += '_'
    result = []
    for kind, carrier in carriers[:CARRIERS]:
        text = source
        for begin, stop, k, value in sorted(stores, reverse=True):
            text = text[:begin] + f'{local}[{k}] = {value};' + text[stop:]
        read = carrier if re.fullmatch(r'u8|unsigned\s+char', kind) else f'(u8){carrier}'
        brace = text.find('{', start)
        declare = f'\n    u8 *{local} = (u8 *)&{symbol} + ({read} >> 8);'
        result.append((FAMILY, text[:brace + 1] + declare + text[brace + 1:]))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',), 'order': 60}  # the registry: no caller wiring (registry.py)
