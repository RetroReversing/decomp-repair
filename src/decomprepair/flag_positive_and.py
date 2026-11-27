"""A 0/1 flag and a comparison joined by `&`, with the flag written as `flag > 0`.

    s32 found = 0; ... found = 1; ... if (found & ((count & 0x3F) == 0))   ->   if (found > 0 & ((count & 0x3F) == 0))

KMC GCC 2.7.2 knows the flag holds only 0 or 1 and turns `flag & (x == 0)` into a branch on `x` and `andi flag, 1`.
Written as `flag > 0` the compare folds back to the flag itself and the target's `sltiu` and `and` stay (a
345-instruction function, 410 -> 10). Offered only for a local whose every assignment is the literal 0 or 1, so
`flag > 0` is the same value. The exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'flag_positive_and'
FAMILIES = (FAMILY,)
_DECL = re.compile(rf'(?<![\w.])(?:s32|u32|int|s16|u16|s8|u8)[ \t]+(?P<f>{IDENT})[ \t]*(?:=[ \t]*[01][ \t]*)?;')
_COMPARE = re.compile(r'==|!=|<=|>=|(?<![<>-])[<>](?![<>=])|^\s*!')


def _is_flag(body, flag):
    writes = re.findall(rf'(?<![\w.>]){flag}[ \t]*(=(?!=)[^;,)]*|[-+*/%&|^]=|<<=|>>=|\+\+|--)', body)
    if re.search(rf'(?:\+\+|--)\s*{flag}\b|(?<!&)&{flag}\b', body):
        return False
    return bool(writes) and all(re.fullmatch(r'=\s*[01]\s*', w) for w in writes)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    out = []
    for decl in _DECL.finditer(body):
        flag = decl['f']
        if not _is_flag(body, flag):
            continue
        for hit in re.finditer(rf'(?<![\w.>])(?P<f>{flag})[ \t]*(?<!&)&(?![&=])[ \t]*\(', body):
            if not re.search(r'(?:[(=]|\breturn)\s*$', body[:hit.start()]):
                continue  # an operator before the flag binds it first
            opening = part.opening + hit.end() - 1
            end = close(clean, opening)
            if end is None or not _COMPARE.search(clean[opening + 1:end - 1]) or '&&' in clean[opening:end]:
                continue
            at = part.opening + hit.start('f')
            out.append((FAMILY, edit(source, [(at, at + len(flag), f'{flag} > 0')])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
