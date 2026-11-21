"""Recover the addressed reply record and the join after an IDO switch."""

import re
from textwrap import dedent, indent

from .integer_repair_support import IDENT, NUMBER, integer, view
from .mips_returns import instructions
from .pattern_repairs import close
from .stack_read_retry import _decimal

FAMILY = 'ido_switch_reply'
_SLOT = r'sp[0-9A-Fa-f]+'
_MEMBER = rf'{IDENT}(?:->{IDENT}|\.{IDENT})+'

# The getter receives the base, and both writers pass the same base and byte
# count. The call delay slot holds the write of the request's reply code.
_TARGET = re.compile(
    rf'addiu \$a2, \$sp, (?P<base>\d+)\n'
    rf'lbu \$a0, \d+\(\$\w+\)\njal (?P<read>{IDENT})\n'
    r'lw \$a1, \d+\(\$\w+\)\nbeqz \$v0, \S+\nnop\nb \S+\naddiu \$v0, \$zero, (?P<failure>-\d+)\n'
    r'lw (?P<req>\$\w+), \d+\(\$sp\)\naddiu \$a0, \$sp, (?P=base)\n'
    r'addiu \$a1, \$zero, (?P<size>\d+)\n'
    r'lbu (?P<code_reg>\$\w+), \d+\((?P=req)\)\nsh \$zero, (?P<error>\d+)\(\$sp\)\n'
    rf'addiu \$a2, \$zero, (?P<first>\d+)\njal (?P<send>{IDENT})\n'
    r'sb (?P=code_reg), (?P<code>\d+)\(\$sp\)\n'
    r'lw (?P<flags_reg>\$\w+), (?P<flags>\d+)\(\$sp\)\n'
    r'addiu \$at, \$zero, (?P<test>\d+)\nbne (?P=flags_reg), \$at, \S+\nnop\n'
    r'addiu (?P<notify>\$\w+), \$zero, (?P<change>\d+)\nsb (?P=notify), (?P=code)\(\$sp\)\n'
    r'addiu \$a0, \$sp, (?P=base)\naddiu \$a1, \$zero, (?P=size)\n'
    r'jal (?P=send)\naddiu \$a2, \$zero, (?P<second>\d+)\n'
)

_SOURCE = re.compile(
    rf'(?P<decl>{IDENT} \*(?P<saved>{IDENT});) s16 (?P<error>{_SLOT}); '
    rf'u8 (?P<code>{_SLOT}); M2C_UNK (?P<base>{_SLOT}); u32 (?P<pc>{_SLOT}); '
    rf'u32 (?P<tmp>{IDENT}); u8 (?P<selector>{IDENT}); '
    rf'(?P=saved) = (?P<param>{IDENT}); (?P=selector) = (?P<method>{_MEMBER}); '
    rf'switch \((?P=selector)\) \{{ case 0: (?P<stop>{IDENT}\((?P=saved)->{IDENT}\);) '
    rf'(?P<join>block_\d+): if \((?P<read>{IDENT})\(\(s32\) (?P=method), (?P<object>(?P=saved)->{IDENT}), '
    rf'&(?P=base)\) != 0\) \{{ return (?P<failure>-\d+); \}} '
    rf'(?P=error) = 0; (?P=code) = (?P<request>(?P=saved)->{IDENT}(?:\.{IDENT})*); '
    rf'(?P<send>{IDENT})\(&(?P=base), (?P<size>{NUMBER}), (?P<first>{NUMBER})\); '
    rf'if \((?P<flags>{_SLOT}) == (?P<test>{NUMBER})\) \{{ '
    rf'(?P=code) = (?P<change>{NUMBER}); (?P=send)\(&(?P=base), (?P=size), (?P<second>{NUMBER})\); \}} return 0; '
    rf'case 1: if \((?P<ready>{IDENT}\(\)) != 0\) \{{ (?P<prepare>{IDENT}\(\);) '
    rf'(?P=pc) = (?P<pc_read>{IDENT}\({NUMBER}\)); if \((?P=pc) != 0\) \{{ '
    rf'(?P=tmp) = (?P=pc) - (?P<step>{NUMBER}); (?P=pc) = (?P=tmp); '
    rf'if \(!\((?P<check>{IDENT}\({NUMBER}, {NUMBER}, )(?P=tmp)(?P<mask> \+ {NUMBER}\) & {NUMBER})\)\) '
    rf'\{{ (?P<action>{IDENT}\(\);) \}} \}} \}} goto (?P=join); default: return (?P<default>-\d+); \}}'
)


def _target(asm):
    if not asm or 'jal' not in asm or 'sh' not in asm:
        return None
    rows = instructions(asm)
    if not rows or len(rows) > 256:
        return None
    text = _decimal(''.join(' '.join(line.split()) + '\n' for line in rows))
    frame = re.match(r'addiu \$sp, \$sp, -(\d+)\n', text)
    match = _TARGET.search(text)
    if (frame and match and 16 <= int(match['base']) and
            int(match['base']) + int(match['size']) <= int(frame[1])):
        return match
    return None


def applies(asm):
    return _target(asm) is not None


def rewrite(source, name, asm, header=''):
    if not source or 'M2C_UNK sp' not in source or 'goto block_' not in source:
        return None
    target = _target(asm)
    part = view(source, name)
    if not target or not part:
        return None
    close_index = close(part.clean, part.opening, '{', '}')
    if not close_index or not (draft := _SOURCE.fullmatch(' '.join(part.clean[part.opening + 1:close_index - 1].split()))):
        return None
    if any('_m2c_reply_' in text for text in (source, header)) or draft['method'].split('->', 1)[0] != draft['param']:
        return None
    signature = rf'\b{re.escape(name)}\({IDENT}\s*\*\s*{re.escape(draft["param"])}\)\s*$'
    if not re.search(signature, part.clean[:part.opening]):
        return None
    if any(int(draft[key][2:], 16) != int(target[key]) for key in ('base', 'code', 'error', 'flags')):
        return None
    if any(integer(draft[key]) != int(target[key]) for key in ('size', 'first', 'second', 'change', 'test', 'failure')):
        return None
    if any(draft[key] != target[key] for key in ('read', 'send')):
        return None
    if re.search(rf'\b{re.escape(draft["flags"])}\b', header):
        return None

    base, size = int(target['base']), int(target['size'])
    fields = [(int(target[key]) - base, width, key) for key, width in (('code', 1), ('error', 2), ('flags', 4))]
    if base % 4 or size % 4 or not 4 <= size <= 256:
        return None
    declarations = []
    end = 0
    for offset, width, field in fields:
        if not end <= offset <= size - width or offset % width:
            return None
        if offset > end:
            declarations.append(f'u8 _m2c_reply_pad_{end}[{offset - end}];')
        declarations.append(f'{"u8" if width == 1 else f"s{8 * width}"} _m2c_reply_{field};')
        end = offset + width
    if end < size:
        declarations.append(f'u8 _m2c_reply_pad_{end}[{size - end}];')
    body = dedent(f'''
        {draft['decl']}
        struct {{ {' '.join(declarations)} }} _m2c_reply_record;
        u32 {draft['pc']};

        {draft['saved']} = {draft['param']};
        switch ({draft['method']}) {{
        case 0:
            {draft['stop']}
            break;
        case 1:
            if ({draft['ready']} != 0) {{
                {draft['prepare']}
                {draft['pc']} = {draft['pc_read']};
                if ({draft['pc']} == 0) break;
                {draft['pc']} -= {draft['step']};
                if (!({draft['check']}{draft['pc']}{draft['mask']})) {{
                    {draft['action']}
                }}
            }}
            break;
        default:
            return {draft['default']};
        }}
        if ({draft['read']}((s32) {draft['method']}, {draft['object']}, (void *)&_m2c_reply_record) != 0) {{
            return {draft['failure']};
        }}
        _m2c_reply_record._m2c_reply_code = {draft['request']};
        _m2c_reply_record._m2c_reply_error = 0;
        {draft['send']}((void *)&_m2c_reply_record, {draft['size']}, {draft['first']});
        if (_m2c_reply_record._m2c_reply_flags == {draft['test']}) {{
            _m2c_reply_record._m2c_reply_code = {draft['change']};
            {draft['send']}((void *)&_m2c_reply_record, {draft['size']}, {draft['second']});
        }}
        return 0;
    ''').strip()
    return source[:part.opening + 1] + '\n' + indent(body, '    ') + '\n' + source[close_index - 1:]
