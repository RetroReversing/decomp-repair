"""Recover IDO's argument-first evaluation of a byte-offset callback."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'lw \$t9, (?P<stack>\d+)\(\$sp\)\nlw \$s0, (?P<ptr>\d+)\(\$t9\)\n'
    r'lh \$t0, (?P<delta>\d+)\(\$s0\)\naddu \$a0, \$t0, \$t9\n'
    r'lw \$t9, (?P<callback>\d+)\(\$s0\)\njalr \$t9'
)
_CANDIDATE = re.compile(
    r'lh \$t0, (?P<delta>\d+)\(\$s0\)\nsll \$t1, \$t0, 2\n'
    r'lw \$t2, (?P<stack>\d+)\(\$sp\)\naddu \$a0, \$t1, \$t2\n'
    r'lw \$t9, (?P<callback>\d+)\(\$s0\)\njalr \$t9'
)


def variants(source, name, header, rows):
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    t, c = _TARGET.search(target), _CANDIDATE.search(candidate)
    if not t or not c or any(t[k] != c[k] for k in ('stack', 'delta', 'callback')):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or re.search(r'\b(?:volatile|asm|__asm__|__LINE__)\b', part.clean):
        return []
    part.end = end
    body = part.body
    if '/*' in body or '//' in body or '#' in body:
        return []
    pattern = re.compile(
        rf'(?P<temp>{IDENT})\s*=\s*M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*void\s*\*\*\s*,\s*'
        rf'(?P<ptr>0x[0-9a-fA-F]+|\d+)\s*\)\s*;\s*'
        rf'M2C_FIELD\(\s*(?P=temp)\s*,\s*M2C_UNK\s*\(\s*\*\*\s*\)\s*\(\s*void\s*\*\s*\)\s*,\s*'
        rf'(?P<callback>0x[0-9a-fA-F]+|\d+)\s*\)\s*\(\s*M2C_FIELD\(\s*(?P=temp)\s*,\s*s16\s*\*\s*,\s*'
        rf'(?P<delta>0x[0-9a-fA-F]+|\d+)\s*\)\s*\+\s*(?P=base)\s*\)\s*;'
    )
    matches = list(pattern.finditer(body))
    if len(matches) != 1:
        return []
    m = matches[0]
    if any(int(m[k], 0) != int(t[k]) for k in ('ptr', 'delta', 'callback')):
        return []
    if len(re.findall(rf'\b{re.escape(m["temp"])}\b', body)) != 4:
        return []
    if not re.search(rf'\bregister\s+void\s*\*\s*{re.escape(m["temp"])}\s*;', body):
        return []
    if not re.search(rf'\bs32\s*\*\s*{re.escape(m["base"])}\b', part.clean[:part.opening]):
        return []
    replacement = (f'M2C_FIELD({m["temp"]}, M2C_UNK (**)(void *), {m["callback"]})('
                   f'M2C_FIELD({m["temp"]} = M2C_FIELD({m["base"]}, void **, {m["ptr"]}), '
                   f's16 *, {m["delta"]}) + (s8 *) {m["base"]});')
    # IDO 7.1 evaluates the argument before the function designator here. The
    # assignment is intentionally confined to this measured compiler pattern.
    return [('measured_ido_callback_offset', edit(source, [(part.opening + 1 + m.start(),
                                                             part.opening + 1 + m.end(), replacement)]))]
