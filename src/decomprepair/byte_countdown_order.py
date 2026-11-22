"""Stage an unsigned byte countdown ahead of a neighboring signed byte read."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _visible

FAMILY = 'byte_countdown_load_order'
REG = r'\$\w+'
FRESH = 'repair_countdown_byte'

TARGET = re.compile(
    rf'lbu (?P<count>{REG}), (?P<count_off>{NUMBER})\((?P<base>{REG})\)\n'
    rf'lb (?P<signed>{REG}), (?P<signed_off>{NUMBER})\((?P=base)\)\n'
    rf'lb (?P<other>{REG}), (?P<other_off>{NUMBER})\((?P=base)\)\n'
    rf'addiu (?P=count), (?P=count), (?:-1|0xffff)\n'
    rf'sb (?P=count), (?P=count_off)\((?P=base)\)'
)
SOURCE = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<temp>{IDENT})\s*=\s*'
    rf'(?P<reader>{IDENT})\(\s*\(char\s*\*\)\s*(?P<base>{IDENT})\s*,\s*(?P<signed_off>{NUMBER})\s*\);\s*'
    rf'(?P<field>\*\(\(u8\s*\*\)\s*\(\(\(char\s*\*\)\s*(?P=base)\)\s*\+\s*(?P<count_off>{NUMBER})\)\))'
    rf'\s*=\s*\(u8\)\s*\((?P<load>\((?P=field)\))\s*-\s*1\)\s*;\s*'
    rf'if\s*\(\s*(?P=temp)\s*<\s*(?P=reader)\(\s*\(char\s*\*\)\s*(?P=base)\s*,'
    rf'\s*(?P<other_off>{NUMBER})\s*\)\s*\)'
)


def _offsets(hit):
    return tuple(integer(hit[key]) for key in ('count_off', 'signed_off', 'other_off'))


def _is_signed_reader(prefix, name):
    pattern = (
        rf'\b(?:inline\s+static|static\s+inline)\s+s8\s+{name}\s*\('
        rf'\s*char\s*\*\s*(?P<base>{IDENT})\s*,\s*int\s+(?P<offset>{IDENT})\s*\)\s*{{\s*'
        r'return\s+\*\(\(s8\s*\*\)\s*\(\s*(?P=base)\s*\+\s*(?P=offset)\s*\)\)\s*;\s*}'
    )
    return re.search(pattern, prefix) is not None


def variants(source, name, rows, *, header=''):
    """Require measured MIPS load ordering and preserve the wrapping byte store."""
    visible = _visible(source, name, header)
    if not visible:
        return []
    part, context = visible
    if re.search(rf'\b{FRESH}\b', context):
        return []
    target = {_offsets(hit) for hit in TARGET.finditer('\n'.join(left for _, left, _ in rows if left))
              if len({hit['count'], hit['signed'], hit['other'], hit['base']}) == 4}
    if not target:
        return []
    changed = '\n'.join(left for mark, left, _ in rows if mark != ' ' and left)
    candidates = []
    for hit in SOURCE.finditer(part.clean, part.opening + 1, part.end):
        offsets = _offsets(hit)
        if offsets not in target or len(set(offsets)) != 3 or hit['temp'] == hit['base']:
            continue
        if not re.search(rf'\blbu \$\w+, (?:{offsets[0]}|{hex(offsets[0])})\(', changed):
            continue
        if not _is_signed_reader(part.clean[:part.opening], hit['reader']):
            continue
        names = '|'.join((hit['base'], hit['temp'], hit['reader'], 'u8', 'u32', 's8'))
        if (re.search(rf'(?m)^\s*#\s*define\s+(?:{names})\b', context)
                or re.search(rf'\b(?:volatile|_Atomic)\b[^;{{}}\n]*\b(?:{names})\b|'
                             rf'\b(?:{names})\b[^;{{}}\n]*\b(?:volatile|_Atomic)\b', context)):
            continue
        block = part.clean[part.opening + 1:hit.start()].rstrip()
        if block[-1:] not in (';', '{', '}', ':') or re.search(r'/[*/]|#', source[hit.start():hit.end()]):
            continue
        expression = source[slice(*hit.span('load'))]
        candidates.append(edit(source, [
            (part.opening + 1, part.opening + 1, f'\n    u32 {FRESH};'),
            (hit.start(), hit.start(), f'{hit["indent"]}{FRESH} = {expression};\n'),
            (*hit.span('load'), FRESH),
        ]))
    return [(FAMILY, candidates[0])] if len(candidates) == 1 else []
