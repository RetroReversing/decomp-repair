"""Recover an IDO callback's adjusted receiver and address-taken event word."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import abi_register_names, normalized_integer_lines
from .mips_returns import instructions

_TARGET = re.compile(
    r'addiu \$sp, \$sp, -56\naddiu \$t6, \$zero, (?P<event>\d+)\n'
    r'sw \$ra, 20\(\$sp\)\nsw \$t6, 44\(\$sp\)\nlw \$t7, 68\(\$a0\)\n'
    r'sll \$t8, \$a1, 2\nsubu \$t8, \$t8, \$a1\nsll \$t8, \$t8, 5\n'
    r'addu \$t9, \$t7, \$t8\nlw \$v1, (?:0)?\(\$t9\)\naddiu \$a1, \$sp, 44\n'
    r'lw \$v0, 40\(\$v1\)\nlw \$t9, 44\(\$v0\)\nlh \$t0, 40\(\$v0\)\n'
    r'jalr \$t9\naddu \$a0, \$t0, \$v1\nlw \$ra, 20\(\$sp\)\naddiu \$sp, \$sp, 56\njr \$ra\nnop'
)
_SOURCE = re.compile(
    rf's32 (?P<event_slot>{IDENT}); void \*(?P<method>{IDENT}); void \*(?P<object>{IDENT}); '
    rf'(?P=event_slot) = (?P<event>{NUMBER}); '
    rf'(?P=object) = \*\(M2C_FIELD\((?P<owner>{IDENT}), s32 \*, 0x44\) \+ \((?P<index>{IDENT}) \* 0x60\)\); '
    r'(?P=method) = M2C_FIELD\((?P=object), void \*\*, 0x28\); '
    r'M2C_FIELD\((?P=method), M2C_UNK \(\*\*\)\(void \*, s32 \*\), 0x2C\)'
    r'\(M2C_FIELD\((?P=method), s16 \*, 0x28\) \+ (?P=object), &(?P=event_slot)\);'
)


def _target(asm):
    if 'jalr' not in asm or 'lh' not in asm:
        return None
    return _TARGET.fullmatch('\n'.join(normalized_integer_lines(instructions(abi_register_names(asm)))))


def applies(asm):
    return _target(asm) is not None


def rewrite(source, name, asm, header=''):
    if 'M2C_FIELD' not in source or not (target := _target(asm)) or not (part := view(source, name)):
        return None
    closing = part.clean.rfind('}', part.opening, part.end)
    draft = _SOURCE.fullmatch(' '.join(part.clean[part.opening+1:closing].split()))
    if (not draft or integer(draft['event']) != int(target['event']) or int(target['event']) > 32767
            or re.search(rf'\b{re.escape(name)}\s*\(', header)
            or '__m2c_event_' in source + header):
        return None
    owner, index = draft['owner'], draft['index']
    if len({owner, index, draft['object'], draft['method'], draft['event_slot']}) != 5:
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*{owner}, s32 {index}\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    # IDO keeps the event in the measured slot with the surrounding locals
    # present. The empty guard stages the adjusted-receiver address before JALR.
    return edit(source, [(signature.start(), closing+1, f'''void {name}(int **{owner}, int {index}) {{
    int __m2c_event_before[2];
    int __m2c_event_value = {draft['event']};
    int __m2c_event_after[1];
    char *__m2c_event_adjustment;
    int *__m2c_event_object;
    int *__m2c_event_method;
    __m2c_event_object = *(int **)((char *){owner}[17] + {index} * 96);
    __m2c_event_method = (int *)__m2c_event_object[10];
    __m2c_event_adjustment = (char *)__m2c_event_method + 40;
    if (__m2c_event_method) {{}}
    ((void (*)(int, int *))(__m2c_event_method[11]))(
        (int)__m2c_event_object + *(short *)__m2c_event_adjustment, &__m2c_event_value);
}}''')])
