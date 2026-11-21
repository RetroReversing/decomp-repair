"""Recover a channel status buffer with overlapping byte and halfword reads."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .pattern_repairs import close

REQUEST = '__osPfsRequestOneChannel'
RESULT = '__osPfsGetOneChannelData'


def evidence(lines):
    text = '\n'.join(' '.join(line.split()) for line in lines if not line.endswith(':'))
    calls = re.findall(rf'(?m)^jal ({IDENT})$', text)
    if (len(calls) != 6 or [calls[i] for i in (0, 2, 4, 5)] != [REQUEST, 'osRecvMesg', 'osRecvMesg', RESULT]
            or calls[1] != calls[3]):
        return None
    status = re.search(
        rf'jal {RESULT}\naddiu \$a1, \$sp, (?P<slot>{NUMBER})\n'
        rf'lbu \$v1, (?P<flags>{NUMBER})\(\$sp\)\nandi \$v0, \$v1, (?:1|0x1)\n'
        r'beqz \$v0, \S+\nandi \$v0, \$v1, (?:2|0x2)\nbnez \$v0, \S+\naddiu \$v0, \$zero, (?:2|0x2)\n'
        r'lhu \$v0, (?P=flags)\(\$sp\)\naddiu \$v1, \$zero, (?:256|0x100)\n'
        r'andi \$v0, \$v0, (?:511|0x1[fF][fF])\nbeq \$v0, \$v1, \S+\nnop\nj \S+\n'
        r'addiu \$v0, \$zero, (?:1|0x1)\nlbu \$v1, (?P=flags)\(\$sp\)\n'
        r'andi \$v1, \$v1, (?:4|0x4)\nbnez \$v1, \S+\naddiu \$v0, \$zero, (?:4|0x4)\n',
        text)
    if not status:
        return None
    start = integer(status['slot'])
    if start % 4 or not 16 <= start <= 64 or integer(status['flags']) != start + 2:
        return None
    before = text[:status.start()]
    buffer = re.search(rf'addiu (?P<reg>\$s[0-7]), \$sp, (?P<buffer>{NUMBER})\n', before)
    if not buffer or integer(buffer['buffer']) != start + 8:
        return None
    reg = re.escape(buffer['reg'])
    receive = rf'(?:move \$a1, {reg}|addu \$a1, {reg}, \$zero)\n(?:addiu \$a2, \$zero, (?:1|0x1)\n)?jal osRecvMesg\n'
    if len(re.findall(receive, before)) != 2:
        return None
    return status, calls[1], text


def rewrite(source, name, context, lines):
    proven = evidence(lines)
    if not proven or '__repair_channel_timeout' in source + context or not (part := view(source, name)):
        return None
    target, dma, text = proven
    format_slot = integer(target['slot'])
    data, queue, flags = (f'sp{offset:X}' for offset in (format_slot, format_slot + 8, format_slot + 2))
    signature = re.search(rf'\bs32\s+{re.escape(name)}\(s32 ({IDENT}), (?:s32|M2C_UNK) ({IDENT})\)\s*$',
                          part.clean[:part.opening])
    if not signature or not (close_at := close(part.clean, part.opening, '{', '}')):
        return None
    mail, channel = signature.groups()
    begin = part.opening + 1
    body = part.clean[begin:close_at - 1]
    declarations = re.match(
        rf'\s*(?P<a>M2C_UNK {data});\s*(?P<b>M2C_UNK {queue});\s*'
        rf's32 (?P<result>{IDENT});[ \t]*\n(?P<unused>[ \t]*s32 (?P<scratch>{IDENT});[ \t]*\n)', body)
    if not declarations:
        return None
    result, scratch = declarations['result'], declarations['scratch']
    protocol = re.fullmatch(
        rf'(?P<prefix>\s*(?:void \*{IDENT};\s*)?'
        rf'(?P<timeout>{IDENT} = (?P<value>{NUMBER});\s*)?{REQUEST}\({channel}\);\s*'
        rf'(?:(?P<pointer>{IDENT}) = (?:\(char \*\))?&(?P<base>{IDENT}) \+ (?P<offset>{NUMBER});\s*)?'
        rf'{dma}\(1, (?P<addr>&?{IDENT})\);\s*osRecvMesg\({mail}, &{queue}, 1\);\s*'
        rf'{result} = {dma}\(0, (?P=addr)\);\s*osRecvMesg\({mail}, &{queue}, 1\);\s*'
        rf'{RESULT}\({channel}, &{data}\);)'
        rf'(?P<tests>\s*if \(!\({flags} & 1\) \|\| \({scratch} = 2, \(\({flags} & 2\) == 0\)\)\) {{\s*'
        rf'if \(\(\(u16\) {flags} & (?:0x1[fF][fF]|511)\) != (?:0x100|256)\) {{\s*return 1;\s*}}\s*'
        rf'{scratch} = 4;\s*if \(!\({flags} & 4\)\) {{\s*{scratch} = {result};\s*}}\s*'
        rf'return {scratch};\s*}}\s*return {scratch};\s*)',
        body[declarations.end():])
    if not protocol:
        return None
    middle = begin + declarations.end()
    edits = [(begin + declarations.start('a'), begin + declarations.end('a'), f's32 {data}[2]'),
             (begin + declarations.start('b'), begin + declarations.end('b'), f's32 {queue}[2]'),
             (begin + declarations.start('unused'), begin + declarations.end('unused'), '')]
    prefix = part.source[middle:middle + protocol.end('prefix')].replace(f'&{queue}', queue).replace(f'&{data}', data)
    if relocation := protocol['base']:
        offset = integer(protocol['offset'])
        pair = (rf'lui (\$s[0-7]), %hi\({relocation} \+ ({NUMBER})\)\n'
                rf'addiu \1, \1, %lo\({relocation} \+ \2\)')
        if protocol['pointer'] != protocol['addr'] or not any(
                integer(value) == offset for _, value in re.findall(pair, text[:target.start()])):
            return None
        ptr = protocol['pointer']
        prefix = prefix.replace(f'{ptr} = &{relocation}', f'{ptr} = (char *)&{relocation}')
    if before := protocol['timeout']:
        symbol = before.split(' = ', 1)[0]
        target_timeout = re.search(rf'addiu (?P<reg>\$\w+), \$zero, (?P<val>{NUMBER})\n'
                                   rf'(?:[^\n]+\n){{0,8}}lui \$at, %hi\({symbol}\)\n'
                                   rf'sb (?P=reg), %lo\({symbol}\)\(\$at\)', text[:target.start()])
        if not target_timeout or integer(target_timeout['val']) != integer(protocol['value']):
            return None
        edits.insert(0, (begin, begin, '\n    s32 __repair_channel_timeout;'))
        value = protocol['value']
        prefix = prefix.replace(f'{symbol} = {value};', f'__repair_channel_timeout = {value};\n    {symbol} = __repair_channel_timeout;')
    byte = f'((u8 *){data})[2]'
    edits.append((middle, close_at - 1,
                  prefix + f'\n    if (({byte} & 1) && ({byte} & 2)) return 2;\n'
                  f'    if ((*(u16 *)((u8 *){data} + 2) & 0x1FF) != 0x100) return 1;\n'
                  f'    if ({byte} & 4) return 4;\n    return {result};\n'))
    return edit(source, edits)
