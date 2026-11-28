"""A local that holds an address inside a parameter, written as that address again in one later statement.

A draft or a rewrite names a parameter's inner block once (`work = &arg->work;`, m2c's `temp_s1 = arg0 + 0x58;`) and uses
the name everywhere. The target of an SN GCC 2.8.1 N64 frame function (`-G0 -mips3 -O2 -mfp32`, 386 instructions) used the
saved register everywhere but in one call after several branches had joined: there it built the address again from the
parameter (`addiu $a0, $s7, 0x58`) and subtracted the parameter's offset first (`addiu $a1, $a1, -0x58; subu $a1, $a1,
$s7`). Written `flush(&arg->work, (u32) end - (u32) &arg->work)` the rows came back (305 -> 0 on the exact judge, with the
rest of the function already matching). Hypothesis, not read in cse.c: past a join cse no longer knows the local equals
the expression, so the expression is computed from the parameter and fold reassociates the difference.

`variants` reads locals assigned exactly once from `&param->member`, `&param[K]` or `param + K` (also behind a cast),
where the function assigns neither the parameter nor takes the local's address, and offers one child per later statement
that reads the local, with every read in that statement written as the expression."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'member_address_respell'
FAMILIES = (FAMILY,)
LIMIT = 40

_CAST = rf'(?:\(\s*{IDENT}(?:\s+{IDENT})?\s*\**\s*\)\s*)?'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_ADDRESS = (rf'&\s*(?P<a>{IDENT})(?:\s*->\s*{IDENT}(?:\s*\.\s*{IDENT})*|\s*\[\s*{_NUM}\s*\])',
            rf'(?P<b>{IDENT})\s*\+\s*{_NUM}',
            rf'\(\s*(?P<b>{IDENT})\s*\+\s*{_NUM}\s*\)')
_ASSIGN = tuple(re.compile(rf'(?m)^[ \t]*(?P<local>{IDENT})[ \t]*=[ \t]*(?P<value>{_CAST}{shape})[ \t]*;') for shape in _ADDRESS)


def _writes(body, word):
    """How many times the body assigns, steps or takes the address of `word` itself."""
    return len(re.findall(rf'(?<![\w.>]){word}\b\s*(?:(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--)|(?:\+\+|--)\s*{word}\b(?!\s*(?:->|\.|\[))'
                          rf'|(?<![&\w)\]] )(?<![&\w)\]])&\s*{word}\b(?!\s*(?:->|\.|\[))', body))


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    signature = re.search(rf'\b{re.escape(name)}\s*\(([^()]*)\)\s*$', clean[:part.opening])
    if not signature:
        return []
    params = {words[-1] for words in (re.findall(IDENT, p) for p in signature[1].split(',')) if len(words) > 1}
    body = clean[part.opening:part.end]
    result = []
    for pattern in _ASSIGN:
        for hit in pattern.finditer(body):
            local, base = hit['local'], hit.groupdict().get('a') or hit.groupdict().get('b')
            if base not in params or local in params or _writes(body, local) != 1 or _writes(body, base):
                continue
            value = f"({source[part.opening + hit.start('value'):part.opening + hit.end('value')]})"
            statements = {}
            for use in re.finditer(rf'(?<![\w.>]){local}\b', body[hit.end():]):
                at = part.opening + hit.end() + use.start()
                start = max(clean.rfind(mark, part.opening, at) for mark in ';{}') + 1
                statements.setdefault(start, []).append((at, at + len(local), value))
            result += [(FAMILY, edit(source, uses)) for uses in statements.values()]
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
