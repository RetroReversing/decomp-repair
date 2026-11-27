"""A global just stored with a constant and then passed as `SYM + K`: the address plus K, not the value.

    D_800BBBA8 = 0;   f(D_800BBBA8 + 1, 2, ...);     ->     D_800BBBA8 = 0;   f(&D_800BBBA8 + 1, 2, ...);

A draft that read the `s8` global as a value folds `0 + 1` to a literal 1 after the store; the target passes the address
plus one (a string or buffer cursor: the byte at the symbol is cleared, the callee gets the next one). The two differ in
every call argument row and the store keeps its place. A N64 menu setup routine (KMC GCC 2.7.2 `-O1 -g`, 80
instructions) stood at 760 with the value and 505 with `&D_800BBBA8 + 1`; the second step, holding the address in a local
(`symbol_address_local`), was exact. `stored_address_value_read` is this change the other way round.

Children, one per site: a call argument `SYM + K` or `SYM - K` (K an integer literal) where SYM is an `extern` scalar
global (not an array, not a local) and a statement `SYM = <literal>;` comes earlier in the function, becomes
`&SYM + K`. Proposals only; the compiler and the byte judge decide."""
import re

from .constant_in_local import _CALL_ARGUMENT, _INT, _NOT_STATEMENT
from .integer_repair_support import IDENT, edit, view

FAMILY = 'stored_symbol_value_argument_address'
FAMILIES = (FAMILY,)
LIMIT = 6
_ARGUMENT = re.compile(rf'(?:^|,)\s*(?P<s>{IDENT})\s*[-+]\s*(?:{_INT})\s*(?=,|$)')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.clean
    text = body[part.opening:part.end]
    if re.search(r'\b(?:volatile|asm|__asm__)\b|^\s*#', text, re.M):
        return []
    scalars = set(re.findall(rf'\bextern\s+(?:const\s+)?[A-Za-z_][\w ]*?\s+({IDENT})\s*;', body[:part.opening]))
    out = []
    for call in _CALL_ARGUMENT.finditer(body, part.opening, part.end):
        if call['callee'] in _NOT_STATEMENT or call['callee'] == 'sizeof' or call['callee'].startswith('M2C_'):
            continue
        for argument in _ARGUMENT.finditer(call['args']):
            symbol = argument['s']
            if symbol not in scalars:
                continue
            before = body[part.opening:call.start()]
            if not re.search(rf'(?m)^[ \t]*{symbol}\s*=\s*(?:{_INT}|-\s*(?:{_INT}))\s*;', before):
                continue
            at = call.start('args') + argument.start('s')
            out.append((FAMILY, edit(source, [(at, at, '&')])))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
