"""Flatten a three-call KMC dispatch and recover its explicit zero-return case."""

import re

from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .measured_stack_drafts import _lines

NUM = r'\d+'
LABEL = r'\.L\w+'
TARGET = re.compile(
    rf'addiu \$sp, \$sp, -(?P<frame>{NUM})\nsw \$s0, (?P<saved>{NUM})\(\$sp\)\n'
    rf'move \$s0, \$a0\nsw \$ra, (?P<return>{NUM})\(\$sp\)\nlh \$v1, (?P<selector>{NUM})\(\$s0\)\n'
    rf'addiu \$v0, \$zero, (?P<first>{NUM})\nbeq \$v1, \$v0, (?P<call0>{LABEL})\n'
    rf'slti \$v0, \$v1, (?P<second>{NUM})\nbnez \$v0, (?P<exit>{LABEL})\nmove \$v0, \$zero\n'
    rf'addiu \$v0, \$zero, (?P=second)\nbeq \$v1, \$v0, (?P<call1>{LABEL})\n'
    rf'addiu \$v0, \$zero, (?P<third>{NUM})\nbeq \$v1, \$v0, (?P<call2>{LABEL})\n'
    r'move \$v0, \$zero\nj (?P=exit)\nnop\n'
    rf'(?P=call0):\nlui \$a0, %hi\((?P<queue>{IDENT})\)\njal (?P<probe>{IDENT})\n'
    rf'addiu \$a0, \$a0, %lo\((?P=queue)\)\nj (?P<finish>{LABEL})\nnop\n'
    rf'(?P=call1):\nlbu \$a1, (?P<byte>{NUM})\(\$s0\)\nlw \$a2, (?P<word>{NUM})\(\$s0\)\n'
    rf'lhu \$a3, (?P<half>{NUM})\(\$s0\)\nlui \$a0, %hi\((?P=queue)\)\njal (?P<read>{IDENT})\n'
    r'addiu \$a0, \$a0, %lo\((?P=queue)\)\nj (?P=finish)\nnop\n'
    rf'(?P=call2):\nlbu \$a1, (?P=byte)\(\$s0\)\nlw \$a2, (?P=word)\(\$s0\)\n'
    rf'lhu \$a3, (?P=half)\(\$s0\)\nlui \$a0, %hi\((?P=queue)\)\njal (?P<write>{IDENT})\n'
    r'addiu \$a0, \$a0, %lo\((?P=queue)\)\n'
    rf'(?P=finish):\nlw \$a0, (?P<message>{NUM})\(\$s0\)\nmove \$a1, \$zero\naddiu \$a2, \$zero, 1\n'
    rf'jal (?P<send>{IDENT})\nsw \$v0, (?P<result>{NUM})\(\$s0\)\naddiu \$v0, \$zero, 1\n'
    r'(?P=exit):\nlw \$ra, (?P=return)\(\$sp\)\nlw \$s0, (?P=saved)\(\$sp\)\n'
    r'jr \$ra\naddiu \$sp, \$sp, (?P=frame)'
)


def _decimal(text):
    return re.sub(r'(?<!\w)0x[0-9a-fA-F]+\b', lambda hit: str(int(hit[0], 16)), text)


def _evidence(asm):
    if 'slti' not in asm or 'lhu' not in asm:
        return None
    lines = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                      if not line.startswith(('glabel ', 'endlabel ')))
    lines = re.sub(r'(?m)^addu (\$\w+), (\$\w+), \$zero$', r'move \1, \2', lines)
    match = TARGET.fullmatch(_decimal(lines))
    if not match:
        return None
    first, second, third = (int(match[key]) for key in ('first', 'second', 'third'))
    labels = {match[key] for key in ('call0', 'call1', 'call2', 'finish', 'exit')}
    if not 0 < first < 32766 or (second, third) != (first + 1, first + 2) or len(labels) != 5:
        return None
    return match


def applies(asm):
    return _evidence(asm) is not None


def rewrite(source, name, asm, header=''):
    """Keep the calls and common tail in target order with an explicit zero case."""
    if 'switch' not in source or not (target := _evidence(asm)):
        return None
    part = view(source, name)
    if not part:
        return None
    signature = re.search(rf'\bs32\s+{re.escape(name)}\(void \*(?P<arg>{IDENT})\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    arg = signature['arg']
    first, second, third = (int(target[key]) for key in ('first', 'second', 'third'))
    selector, byte, word, half, message, result = (target[key] for key in
                                                    ('selector', 'byte', 'word', 'half', 'message', 'result'))
    queue = target['queue']
    args = f'&{queue}, M2C_FIELD({arg}, u8 *, {byte}), M2C_FIELD({arg}, s32 *, {word}), M2C_FIELD({arg}, u16 *, {half})'
    probe, read, write, send = (target[key] for key in ('probe', 'read', 'write', 'send'))
    delivery = f'{send}(M2C_FIELD({arg}, s32 *, {message}), 0, 1);'
    assign = f'M2C_FIELD({arg}, s32 *, {result})'
    draft = _shape(f'''
        s16 @selector;
        s32 @zero;
        s32 @result;
        @selector = M2C_FIELD({arg}, s16 *, {selector});
        if (@selector != {first}) {{
            @zero = 0;
            if (@selector >= {second}) {{
                switch (@selector) {{
                case {second}:
                    @result = {read}({args});
                    goto @join;
                case {third}:
                    @result = {write}({args});
                    goto @join;
                default:
                    return 0;
                }}
            }} else {{
                return @zero;
            }}
        }} else {{
            @result = {probe}(&{queue});
        @join:
            {assign} = @result;
            {delivery}
            @zero = 1;
            return @zero;
        }}
    ''')
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    match = draft.fullmatch(' '.join(_decimal(part.clean[start:end]).split()))
    if not match or len(set(match.groups())) != 4 or arg in match.groups():
        return None
    if re.search(rf'(?m)^\s*#\s*define\s+(?:{match["selector"]}|{match["result"]})\b', source + '\n' + header):
        return None
    value, kind = match['result'], match['selector']
    body = f'''
    s16 {kind} = M2C_FIELD({arg}, s16 *, {selector});
    s32 {value};

    switch ({kind}) {{
    case 0x{first - 1:X}:
        return 0;
    case 0x{first:X}:
        {value} = {probe}(&{queue});
        break;
    case 0x{second:X}:
        {value} = {read}({args});
        break;
    case 0x{third:X}:
        {value} = {write}({args});
        break;
    default:
        return 0;
    }}
    {assign} = {value};
    {delivery}
    return 1;
'''
    return edit(source, [(start, end, body)])
