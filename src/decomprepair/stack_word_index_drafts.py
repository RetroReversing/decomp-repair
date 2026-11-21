"""Restore a grouped word copy when m2c keeps its stack stores and loses their indexed base."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .measured_stack_drafts import WORD_RUN, _body, _lines, _word_copy

WORDS = 8
PREFIX = '__repair_indexed_words'
BODY = re.compile(
    rf'(?P<value>{IDENT}) = (?P<arg>{IDENT}); (?P<copy>(?:{WORD_RUN.pattern} ){{{WORDS}}})'
    rf'(?P<result>{IDENT}) = 0; if \((?P=value) <= (?P<limit>{NUMBER})\) {{ '
    rf'(?P<digit>{IDENT}) = (?P<top>{NUMBER}); (?P<index>{IDENT}) = 0; do {{ '
    rf'(?P<divisor>{IDENT}) = \*\(\((?P=index) \* 4\) \+ sp\); '
    rf'(?P=result) \|= \((?P=value) / (?P=divisor)\) \* (?P=digit); '
    rf'(?P=value) = (?P=value) % (?P=divisor); (?P=index) \+= 1; (?P=digit) = (?P=digit) >> (?P<shift>{NUMBER}); '
    rf'}} while \((?P=index) < (?P<count>{NUMBER})\); return (?P=result); }} return (?P<fallback>{NUMBER});'
)


def _evidence(asm):
    if not asm or 'divu' not in asm or 'sll' not in asm or asm.count('($sp)') < WORDS:
        return None
    lines = _lines(asm)
    text = '\n'.join(' '.join(line.split()) for line in lines
                     if not line.startswith(('glabel ', 'endlabel ')))
    table = re.search(rf'(?m)^lui (?P<base>\$\w+), %hi\((?P<symbol>{IDENT})\)\n'
                      r'addiu (?P=base), (?P=base), %lo\((?P=symbol)\)\n'
                      r'lw \$\w+, (?:0x0|0)?\((?P=base)\)', text)
    exit_ = re.search(
        rf'(?m)^j (?P<done>\.L\w+)\n(?:addu \$v0, \$a3, \$zero|move \$v0, \$a3)\n\.L\w+:\n'
        rf'lui \$a3, \((?P<value>{NUMBER}) >> 16\)\nori \$a3, \$a3, \((?P=value) & 0xFFFF\)\n'
        r'(?:addu \$v0, \$a3, \$zero|move \$v0, \$a3)\n(?P=done):\njr \$ra\n'
        r'addiu \$sp, \$sp, (?:32|0x20)$', text)
    lookup = re.search(
        r'(?m)^sll (?P<index>\$\w+), \$\w+, (?:2|0x2)\n'
        r'addu (?P<address>\$\w+), (?P=index), \$sp\n'
        r'lw (?P<value>\$\w+), (?:0x0|0)?\((?P=address)\)\n'
        r'divu \$zero, \$\w+, (?P=value)$', text)
    if not table or not exit_ or not lookup or not _word_copy(lines, 4 * WORDS, base=table['base']):
        return None
    if not re.search(rf'(?m)^slti \$\w+, \$\w+, (?:{WORDS}|0x{WORDS:X})$', text):
        return None
    return table['symbol'], integer(exit_['value'])


def applies(asm):
    return _evidence(asm) is not None


def rewrite(source, name, asm, header=''):
    if '+ sp)' not in source or PREFIX in source + header or not (target := _evidence(asm)):
        return None
    if not (part := view(source, name)):
        return None
    locals_, body, end = _body(part)
    match = BODY.fullmatch(body)
    signature = re.search(rf'\bs32 {re.escape(name)}\(u32 ({IDENT})\)\s*$', part.clean[:part.opening])
    if not match or not signature or signature[1] != match['arg']:
        return None
    base, fallback = target
    if integer(match['count']) != WORDS or integer(match['fallback']) != fallback:
        return None
    if len(re.findall(rf'\b{base}\b', part.clean)) != WORDS + 1 or re.search(rf'\b{base}\b', header):
        return None
    copies = list(WORD_RUN.finditer(match['copy']))
    offsets = list(range(0, WORDS * 4, 4))
    if ([integer(hit['off']) for hit in copies] != offsets
            or [int(hit['local'][2:], 16) for hit in copies] != offsets
            or any(hit['base'] != base for hit in copies)):
        return None
    value, result, index, digit, divisor = (match[key] for key in ('value', 'result', 'index', 'digit', 'divisor'))
    expected = {hit['local']: 's32' for hit in copies}
    expected.update({value: 'u32', result: 's32', index: 's32', digit: 'u32', divisor: 'u32'})
    if locals_ != expected or len(expected) != WORDS + 5:
        return None
    declaration = re.search(rf'\bextern (?:M2C_UNK|s32) {base};', part.clean[:part.opening])
    if not declaration:
        return None
    typed = f'typedef struct {{ u32 words[{WORDS}]; }} {PREFIX}_t;\nextern {PREFIX}_t {base};'
    return edit(source, [(*declaration.span(), typed), (part.opening+1, end, f'''
    {PREFIX}_t {PREFIX};
    s32 {index};
    s32 {result};
    u32 {divisor};
    u32 {digit};
    u32 {value};

    {value} = {match["arg"]};
    {PREFIX} = {base};
    {result} = 0;
    if ({value} <= {match["limit"]}) {{
        {digit} = {match["top"]};
        {index} = 0;
        do {{
            {divisor} = {PREFIX}.words[{index}];
            {result} |= ({value} / {divisor}) * {digit};
            {value} = {value} % {divisor};
            {index} += 1;
            {digit} = {digit} >> {match["shift"]};
        }} while ({index} < {WORDS});
    }} else {{
        {result} = {match["fallback"]};
    }}
    return {result};
''')])
