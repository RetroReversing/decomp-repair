"""Recover a word-aligned read buffer and the measured KMC retry paths."""

import re

from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .measured_stack_drafts import _lines

NUMBER = r'\d+'
LABEL = r'\.L\w+'
PREFIX = '__repair_read_'
READ = (
    rf'lw \$a0, (?P<handle>{NUMBER})\(\$s0\)\nlw \$a1, (?P<channel>{NUMBER})\(\$s0\)\n'
    rf'addiu \$a2, \$zero, (?P<page>{NUMBER})\njal (?P<read>{IDENT})\naddiu \$a3, \$sp, (?P<buffer>{NUMBER})\n'
)
TARGET = re.compile(
    rf'addiu \$sp, \$sp, -(?P<frame>{NUMBER})\nsw \$s0, (?P<save>{NUMBER})\(\$sp\)\n'
    rf'move \$s0, \$a0\nsw \$ra, (?P<return>{NUMBER})\(\$sp\)\nlbu \$v0, (?P<flag>{NUMBER})\(\$s0\)\n'
    rf'beqz \$v0, (?P<entry>{LABEL})\nnop\njal (?P<select>{IDENT})\nmove \$a1, \$zero\n'
    rf'move \$v1, \$v0\naddiu \$v0, \$zero, (?P<retry>{NUMBER})\n'
    rf'bne \$v1, \$v0, (?P<selected>{LABEL})\nmove \$a0, \$s0\n'
    r'jal (?P=select)\nmove \$a1, \$zero\nmove \$v1, \$v0\n(?P=selected):\n'
    rf'bnez \$v1, (?P<exit>{LABEL})\nmove \$v0, \$v1\n(?P=entry):\n'
    + READ +
    rf'move \$v1, \$v0\nbeqz \$v1, (?P<compare_label>{LABEL})\naddiu \$v0, \$zero, (?P=retry)\n'
    r'bne \$v1, \$v0, (?P=exit)\nmove \$v0, \$v1\n'
    r'lw \$a0, (?P=handle)\(\$s0\)\nlw \$a1, (?P=channel)\(\$s0\)\n'
    r'addiu \$a2, \$zero, (?P=page)\njal (?P=read)\naddiu \$a3, \$sp, (?P=buffer)\n'
    r'move \$v1, \$v0\nbnez \$v1, (?P=exit)\nnop\n(?P=compare_label):\n'
    rf'addiu \$a0, \$s0, (?P<record>{NUMBER})\naddiu \$a1, \$sp, (?P=buffer)\n'
    rf'jal (?P<compare>{IDENT})\naddiu \$a2, \$zero, (?P<length>{NUMBER})\n'
    r'sltu \$v0, \$zero, \$v0\nsll \$v0, \$v0, 1\n(?P=exit):\n'
    r'lw \$ra, (?P=return)\(\$sp\)\nlw \$s0, (?P=save)\(\$sp\)\njr \$ra\n'
    r'addiu \$sp, \$sp, (?P=frame)'
)


def _decimal(text):
    return re.sub(r'(?<!\w)0x[0-9a-fA-F]+\b', lambda hit: str(int(hit[0], 16)), text)


def _evidence(asm):
    if 'lbu' not in asm or 'sltu' not in asm or 'jal' not in asm:
        return None
    text = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                     if not line.startswith(('glabel ', 'endlabel ')))
    text = re.sub(r'(?m)^addu (\$\w+), (\$\w+), \$zero$', r'move \1, \2', text)
    match = TARGET.fullmatch(_decimal(text))
    if not match:
        return None
    buffer, length, save, ret, frame = (int(match[key]) for key in ('buffer', 'length', 'save', 'return', 'frame'))
    if (not 16 <= buffer < save or buffer % 4 or not 4 <= length <= 64 or length % 4
            or buffer + length != save or ret != save + 4 or ret + 4 != frame):
        return None
    return match


def applies(asm):
    return _evidence(asm) is not None


def _source_shape(target, arg, current):
    select, read, compare = (target[key] for key in ('select', 'read', 'compare'))
    flag, handle, channel, page, record, length, retry = (target[key] for key in
                                                       ('flag', 'handle', 'channel', 'page', 'record', 'length', 'retry'))
    read_args = f'M2C_FIELD({arg}, s32 *, {handle}), M2C_FIELD({arg}, s32 *, {channel}), {page}'
    kind = 's32' if current else 'M2C_UNK'
    bank = '@temp' if current else '@bank'
    bank_declaration = '' if current else 's32 @bank;'
    return _shape(f'''
        {kind} @buffer;
        s32 @temp;
        s32 @result;
        {bank_declaration}
        if (M2C_FIELD({arg}, u8 *, {flag}) != 0) {{
            {bank} = {select}(NULL);
            if ({bank} == {retry}) {{
                {bank} = {select}({arg}, 0);
            }}
            @result = {bank};
            if ({bank} == 0) {{
                goto @entry;
            }}
        }} else {{
        @entry:
            @temp = {read}({read_args}, &@buffer);
            if ((@temp == 0) || ((@result = @temp, (@temp == {retry})) &&
                (@result = {read}({read_args}, &@buffer), (@result == 0)))) {{
                @result = ({compare}({arg} + {record}, &@buffer, {length}) != 0) * 2;
            }}
        }}
        return @result;
    ''')


def rewrite(source, name, asm, header=''):
    """Derive the buffer extent from the compare and preserve the original retry count."""
    if 'M2C_FIELD' not in source or PREFIX in source + header or not (target := _evidence(asm)):
        return None
    part = view(source, name)
    if not part:
        return None
    signature = re.search(rf'\bs32\s+{re.escape(name)}\(void \*(?P<arg>{IDENT})\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    arg = signature['arg']
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    text = ' '.join(_decimal(part.clean[start:end]).split())
    draft = next((hit for current in (False, True)
                  if (hit := _source_shape(target, arg, current).fullmatch(text))), None)
    if not draft or len(set(draft.groups())) != len(draft.groups()) or arg in draft.groups():
        return None

    select, read, compare = (target[key] for key in ('select', 'read', 'compare'))
    flag, handle, channel, page, record, length, retry = (target[key] for key in
                                                       ('flag', 'handle', 'channel', 'page', 'record', 'length', 'retry'))
    buffer, error = PREFIX + 'buffer', PREFIX + 'error'
    read_args = f'M2C_FIELD({arg}, s32 *, {handle}), M2C_FIELD({arg}, s32 *, {channel}), {page}, {buffer}'
    body = f'''
    s32 {buffer}[{int(length) // 4}];
    s32 {error};

    if (M2C_FIELD({arg}, u8 *, {flag}) != 0) {{
        {error} = {select}({arg}, 0);
        if ({error} == {retry}) {{
            {error} = {select}({arg}, 0);
        }}
        if ({error} != 0) {{
            return {error};
        }}
    }}
    {error} = {read}({read_args});
    if ({error} != 0) {{
        if ({error} != {retry}) {{
            return {error};
        }}
        {error} = {read}({read_args});
        if ({error} != 0) {{
            return {error};
        }}
    }}
    return ({compare}((char *){arg} + {record}, {buffer}, {length}) != 0) * 2;
'''
    return edit(source, [(start, end, body)])
