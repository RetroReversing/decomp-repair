"""Recover a volatile poll followed by a read through a mapped address."""

import re
from textwrap import dedent, indent

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .measured_stack_drafts import _lines
from .pattern_repairs import close
from .stack_read_retry import _decimal

FAMILY = 'ido_mapped_poll_read'
ZERO_WORD = 'D_00000000'

_TARGET = re.compile(
    rf'lui \$t6, %hi\((?P<status>{IDENT})\)\nlw \$a2, %lo\((?P=status)\)\(\$t6\)\n'
    r'addiu \$sp, \$sp, -8\nandi \$t7, \$a2, (?P<mask>\d+)\n'
    r'beqz \$t7, (?P<ready>\.L\w+)\nnop\n(?P<poll>\.L\w+):\n'
    r'lui \$t8, %hi\((?P=status)\)\nlw \$a2, %lo\((?P=status)\)\(\$t8\)\n'
    r'andi \$t9, \$a2, (?P=mask)\nbnez \$t9, (?P=poll)\nnop\n(?P=ready):\n'
    r'lui \$t0, (?:\(0 >> 16\)|0)\nlw \$t0, 0\(\$t0\)\n'
    rf'lui \$at, %hi\((?P<segment>{IDENT})\)\nor \$v0, \$zero, \$zero\n'
    r'or \$t1, \$t0, \$a0\nor \$t2, \$t1, \$at\n'
    r'lw \$t3, %lo\((?P=segment)\)\(\$t2\)\naddiu \$sp, \$sp, 8\njr \$ra\nsw \$t3, 0\(\$a1\)'
)


def _target(asm):
    if not asm or 'andi' not in asm or '%lo' not in asm:
        return None
    text = '\n'.join(' '.join(line.split()) for line in _lines(asm) if not line.startswith(('glabel ', 'endlabel ')))
    hit = _TARGET.fullmatch(_decimal(text))
    if hit and hit['ready'] != hit['poll'] and 0 < int(hit['mask']) <= 0xFFFF:
        return hit
    return None


def applies(asm):
    return _target(asm) is not None


def rewrite(source, name, asm, header='', resolve=None):
    if not source or not resolve or 'return 0;' not in source or not (target := _target(asm)):
        return None
    status, segment = resolve(target['status']), resolve(target['segment'])
    if (resolve(ZERO_WORD) != 0 or not isinstance(status, int) or not isinstance(segment, int)
            or not 0xA0000000 <= status <= 0xBFFFFFFC or status % 4
            or segment not in (0x80000000, 0xA0000000)):
        return None
    part = view(source, name)
    closing = close(part.clean, part.opening, '{', '}') if part else None
    if not closing or '_m2c_mapped_' in source + header:
        return None
    sig = re.search(rf'\bs32\s+{re.escape(name)}\s*\(\s*u32\s+(?P<addr>{IDENT}),\s*u32\s*\*\s*(?P<out>{IDENT})\)\s*$',
                    part.clean[:part.opening])
    if not sig:
        return None
    flag, upper = (re.escape(target[key]) for key in ('status', 'segment'))
    arg, dest = sig['addr'], sig['out']
    body = ' '.join(part.clean[part.opening + 1:closing - 1].split())
    draft = re.fullmatch(
        rf'if \({flag} & (?P<mask>{NUMBER})\) \{{ do \{{ \}} while \({flag} & (?P=mask)\); \}} '
        rf'\*{dest} = \*\(\*(?:NULL|\(\(void\s*\*\)\s*0\)) \| {arg} \| \(s32\) &{upper}\); return 0;',
        body)
    if not draft or integer(draft['mask']) != int(target['mask']):
        return None

    declaration = ''
    zero = re.compile(rf'\b{ZERO_WORD}\b')
    known = header + part.clean[:sig.start()]
    if not zero.search(known):
        declaration = f'extern u32 {ZERO_WORD};\n\n'
    elif not re.search(rf'\b(?:extern\s+)?(?:u32|unsigned int)\s+{ZERO_WORD}\s*;', known):
        return None
    access = f'*(volatile u32 *)0x{status:08X}U'
    replacement = dedent(f'''
        char _m2c_mapped_pad[4];
        register u32 _m2c_mapped_status;

        _m2c_mapped_status = {access};
        if (_m2c_mapped_status & {draft['mask']}) {{
            do {{
                _m2c_mapped_status = {access};
            }} while (_m2c_mapped_status & {draft['mask']});
        }}
        *{dest} = *(u32 *)(({ZERO_WORD} | {arg}) | 0x{segment:08X}U);
        return 0;
    ''').strip()
    changes = [
        (sig.start(), sig.start(), declaration),
        (part.opening + 1, closing - 1, '\n' + indent(replacement, '    ') + '\n'),
    ]
    # The draft's spurious external lvalues are superseded by the numeric accesses.
    for symbol in (flag, upper):
        match = re.search(rf'(?m)^extern\s+(?:M2C_UNK|s32)\s+{symbol};[ \t]*\n', part.clean[:sig.start()])
        if match and not re.search(rf'\b{symbol}\b', part.clean[closing:]):
            changes.append((*match.span(), ''))
    return edit(source, changes)
