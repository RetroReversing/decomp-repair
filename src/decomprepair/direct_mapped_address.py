"""Restore independent returns for two MIPS direct-mapped address ranges."""

import re

from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .measured_stack_drafts import _lines

MASK = '0x1FFFFFFF'
TARGET = re.compile(
    r'addiu \$sp, \$sp, -(?P<frame>0x[\da-f]+|\d+)\n'
    r'lui \$v1, (?:\(0x1fffffff >> 16\)|0x1fff)\nori \$v1, \$v1, (?:\(0x1fffffff & 0xffff\)|0xffff)\n'
    r'lui \$v0, (?:\(0x80000000 >> 16\)|0x8000)\nsubu \$v0, \$a0, \$v0\nsltu \$v0, \$v1, \$v0\n'
    r'beqz \$v0, (?P<direct>\.L\w+)\nsw \$ra, (?P<save>0x[\da-f]+|\d+)\(\$sp\)\n'
    r'lui \$v0, (?:\(0x60000000 >> 16\)|0x6000)\naddu \$v0, \$a0, \$v0\nsltu \$v0, \$v1, \$v0\n'
    r'beqz \$v0, (?P<exit>\.L\w+)\nand \$v0, \$a0, \$v1\n'
    rf'jal (?P<fallback>{IDENT})\nnop\nj (?P=exit)\nnop\n'
    r'(?P=direct):\nand \$v0, \$a0, \$v1\n(?P=exit):\n'
    r'lw \$ra, (?P=save)\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, (?P=frame)',
    re.I,
)


def _target(asm):
    if 'sltu' not in asm or 'jal' not in asm:
        return None
    text = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                     if not line.startswith(('glabel ', 'endlabel ')))
    hit = TARGET.fullmatch(text)
    return hit if hit and hit['direct'] != hit['exit'] else None


def applies(asm):
    return _target(asm) is not None


def rewrite(source, name, asm, header=''):
    """Use two unsigned range checks and preserve the fallback argument."""
    if MASK not in source or not (target := _target(asm)):
        return None
    part = view(source, name)
    if not part:
        return None
    signature = re.search(rf'\bs32\s+{re.escape(name)}\s*\(\s*s32\s+(?P<arg>{IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None
    arg, fallback = signature['arg'], target['fallback']
    if not re.search(rf'\bs32\s+{fallback}\s*\(\s*\)\s*;', part.clean[:part.opening]):
        return None
    # The generated unprototyped declaration permits forwarding the live argument.
    if re.search(rf'\b{fallback}\s*\(', header):
        return None

    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    body = ' '.join(part.clean[start:end].split())
    for declaration, result in (('', '@value'), ('s32 @other;', '@other')):
        shape = _shape(f'''
            s32 @value;
            {declaration}
            if ((u32) ({arg} - 0x80000000) > {MASK}U) {{
                @value = {arg} & {MASK};
                if ((u32) ({arg} + 0x60000000) > {MASK}U) {{
                    return {fallback}();
                }}
                return @value;
            }}
            {result} = {arg} & {MASK};
            return {result};
        ''')
        if shape.fullmatch(body):
            break
    else:
        return None

    return edit(source, [(start, end, f'''
    if (((u32){arg} - 0x80000000U) <= {MASK}U) {{
        return {arg} & {MASK};
    }}
    if (((u32){arg} + 0x60000000U) <= {MASK}U) {{
        return {arg} & {MASK};
    }}
    return {fallback}({arg});
''')])
