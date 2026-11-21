"""Recover lost stack objects from KMC drafts with corroborating MIPS copies."""

import re

from . import channel_status_drafts, formatted_stack_draft, message_frame_drafts
from .integer_repair_support import IDENT, NUMBER, integer, view
from .mips import abi_register_names
from .unaligned_stack_drafts import MEMORY, stack_copy

P = '__m2c_copy_'
PARAMS = r'(?P<signature>\bvoid\s+{name}\s*\(\s*(?P<parameters>[^()]*)\))\s*$'
OUTGOING = re.compile(
    rf'(?:(?P<read>{IDENT}) = (?P<payload>{IDENT}); )?'
    rf'(?P<dest>{IDENT}) = &(?P<base>{IDENT}); '
    rf'(?:(?P<write>{IDENT}) = &sp4; )?(?:(?P<clear>{IDENT}) = 3; )?'
    rf'(?P<ready>{IDENT}) = (?P<ready_value>{NUMBER}); '
    rf'(?P<bytes>(?:sp[0-3] = (?:{NUMBER}|{IDENT}); ){{4}})'
    rf'(?:do {{ \*(?P=write) = \*(?P=read); (?P=write) \+= 1; (?P=read) \+= 1; }} '
    rf'while \(\(s32\) (?P=write) < \(s32\) &spC\); (?P<counter>{IDENT}) = 3; )?'
    rf'do {{ \*(?P=dest) = 0; (?P<loop>{IDENT}) -= 1; (?P=dest) \+= 1; }} while \((?P=loop) >= 0\); '
    r'M2C_FIELD\((?P=dest), s8 \*, 0\) = M2C_UNALIGNED32\(sp0\); '
    r'M2C_FIELD\((?P=dest), M2C_UNK \*, 4\) = M2C_UNALIGNED32\(sp4\); '
    r'M2C_FIELD\((?P=dest), M2C_UNK \*, 8\) = M2C_UNALIGNED32\(sp8\); '
    rf'M2C_FIELD\((?P=dest), s8 \*, 0xC\) = (?P<end>{NUMBER});'
)
INCOMING = re.compile(
    rf'(?P<out>{IDENT}) = (?P<arg>{IDENT}); (?P<flags>{IDENT}) = 0; '
    rf'(?P<input>{IDENT}) = (?:\(char \*\))?&(?P<source>{IDENT})(?: \+ (?P<offset>{NUMBER}))?; '
    rf'(?P<index>{IDENT}) = 0; '
    rf'if \(\(s32\) (?P<count>{IDENT}|M2C_FIELD\(&(?P<count_base>{IDENT}), u8 \*, (?P<count_off>{NUMBER})\)) > 0\) {{ (?P<bytes>{IDENT}) = (?P=arg) \+ 2; do {{ '
    r'sp0 = M2C_UNALIGNED32\(M2C_FIELD\((?P=input), M2C_UNK \*, 0\)\); '
    r'sp4 = M2C_UNALIGNED32\(M2C_FIELD\((?P=input), M2C_UNK \*, 4\)\); '
    rf'(?P<status>{IDENT}) = \(u32\) \(sp2 & (?P<mask>{NUMBER})\) >> (?P<shift>{NUMBER}); '
    r'M2C_FIELD\((?P=bytes), s8 \*, 1\) = \(s8\) (?P=status); '
    r'if \((?P=status) == 0\) { \*(?P=out) = sp4 \| \(sp5 << 8\); '
    r'(?P=flags) \|= 1 << (?P=index); M2C_FIELD\((?P=bytes), u8 \*, 0\) = sp6; } '
    r'(?P=index) \+= 1; (?P=input) \+= 8; (?P=bytes) \+= 4; (?P=out) \+= 4; } '
    rf'while \((?P=index) < \(s32\) (?P=count)\); }} \*(?P<return>{IDENT}) = (?P=flags);'
)
WORD_RUN = re.compile(
    rf'(?P<local>sp[0-9A-F]+) = M2C_FIELD\(&(?P<base>{IDENT}), s32 \*, (?P<off>{NUMBER})\);'
)
WORD_RETURN = re.compile(rf'return \*\(\((?P<index>{IDENT}) \* 4\) \+ sp\);')
DECL = re.compile(rf'(?P<type>s8|u8|s16|u16|s32|u32|f32|void|M2C_UNK) (?P<pointer>\*)?(?P<name>{IDENT}); ')


def _lines(asm):
    return tuple(line for raw in abi_register_names(asm).splitlines()
                 if (line := re.sub(r'/\*.*?\*/|#.*', '', raw).strip()))


def _outgoing_copy(lines):
    offsets = [0, 3, 4, 7, 8, 11] * 2
    ops = ('lwl', 'lwr') * 3 + ('swl', 'swr') * 3
    for i, line in enumerate(lines):
        if not line.startswith('lwl') or i+12 > len(lines):
            continue
        mem = [MEMORY.fullmatch(line) for line in lines[i:i+12]]
        if not all(mem):
            continue
        got, regs, disps, bases = zip(*(m.groups() for m in mem))
        if (got == ops and [integer(n or '0') for n in disps] == offsets
                and regs[:6] == regs[6:] and regs[::2] == regs[1::2]
                and len(set(regs[:6])) == 3 and set(bases[:6]) == {'$sp'}
                and len(set(bases[6:])) == 1 and bases[6] != '$sp' and bases[6] not in regs
                and any(re.fullmatch(r'addiu\s+\$sp,\s*\$sp,\s*-(?:0x10|16)', row) for row in lines[:i])):
            return True
    return False


def _word_copy(lines, size=24, *, base=None):
    if not any(re.fullmatch(rf'addiu\s+\$sp,\s*\$sp,\s*-(?:0x{size:X}|{size})', line, re.I)
               for line in lines):
        return False
    stack = [m for line in lines if (m := MEMORY.fullmatch(line)) and m[1] == 'sw' and m[4] == '$sp']
    if [integer(m[3] or '0') for m in stack] != list(range(0, size, 4)):
        return False
    first = next((i for i, line in enumerate(lines) if (m := MEMORY.fullmatch(line))
                  and m[1] == 'sw' and m[4] == '$sp'), 0)
    copies = [MEMORY.fullmatch(line) for line in lines[max(0, first-3):first-3+(size//2)]]
    if len(copies) != size//2 or not all(copies):
        return False
    loads = []
    for offset in range(0, size//4, 3):
        count = min(3, size//4 - offset)
        loads.extend(copies[2*offset:2*offset+count])
    if not (len({m[4] for m in loads}) == 1 and loads[0][4] != '$sp'
            and (base is None or base == loads[0][4])
            and all(m[1] == 'lw' for m in loads)
            and [integer(m[3] or '0') for m in loads] == list(range(0, size, 4))
            and [m[2] for m in loads] == [m[2] for m in stack]):
        return False
    for i, line in enumerate(lines[:-2]):
        shift = re.fullmatch(r'sll\s+(\$\w+),\s*\$\w+,\s*(?:2|0x2)', line)
        address = re.fullmatch(r'addu\s+(\$\w+),\s*(\$\w+),\s*\$sp', lines[i+1])
        load = MEMORY.fullmatch(lines[i+2])
        if shift and address and load and shift[1] == address[2] and load[1] == 'lw' and load[4] == address[1]:
            return True
    return False


def applies(asm):
    """Which other cached KMC drafts to regenerate."""
    if ('swr' in asm and 'lwr' in asm
            and (stack_copy(asm, (('lbu', 4), ('lbu', 5), ('lbu', 6))) or _outgoing_copy(_lines(asm)))):
        return True
    if channel_status_drafts.RESULT in asm and channel_status_drafts.evidence(_lines(asm)):
        return True
    if 'osCreateMesgQueue' in asm and message_frame_drafts.evidence(_lines(asm)):
        return True
    if 'nor' in asm and formatted_stack_draft.target(_lines(asm)):
        return True
    return asm.count('($sp)') >= 6 and 'sll' in asm and _word_copy(_lines(asm))


def _external(part, context, symbol, ctype):
    """Only replace a declaration owned by the draft and used once outside it."""
    pattern = re.compile(rf'\bextern\s+{ctype}\s+{symbol}\s*;')
    match = pattern.search(part.clean, 0, part.opening)
    if (not match or re.search(rf'\b{symbol}\b', context)
            or len(re.findall(rf'\b{symbol}\b', part.clean)) != 2):
        return None
    return match


def _body(part):
    end = len(part.clean[:part.end].rstrip()) - 1
    body = ' '.join(part.clean[part.opening+1:end].split())
    locals_ = {}
    while hit := DECL.match(body):
        if hit['name'] in locals_:
            return {}, '', end
        locals_[hit['name']] = hit['type'] + ('*' if hit['pointer'] else '')
        body = body[hit.end():]
    return locals_, body, end


_RELOCATED_PACKET = re.compile(
    rf'(?:(?P<read>{IDENT}) = (?P<payload>{IDENT}); )?'
    rf'(?P<dest>{IDENT}) = (?:\(char \*\))?&(?P<base>{IDENT}) \+ (?P<offset>{NUMBER}); '
    rf'(?:(?P<write>{IDENT}) = &sp4; |(?P<clear>{IDENT}) = 3; )'
    rf'M2C_FIELD\(&(?P=base), s32 \*, (?P<ready>{NUMBER})\) = 1; '
    rf'sp0 = (?P<byte0>{NUMBER}); sp1 = (?P<byte1>{NUMBER}); sp2 = (?P<byte2>{NUMBER}); sp3 = (?P<arg>{IDENT}); '
    rf'(?:do {{ \*(?P=write) = \*(?P=read); (?P=write) \+= 1; (?P=read) \+= 1; }} '
    rf'while \(\(s32\) (?P=write) < \(s32\) &spC\); (?P<counter>{IDENT}) = 3; )?'
    rf'do {{ \*(?P=dest) = 0; (?P<loop>{IDENT}) -= 1; (?P=dest) \+= 1; }} while \((?P=loop) >= 0\); '
    r'M2C_FIELD\((?P=dest), s8 \*, 0\) = M2C_UNALIGNED32\(sp0\); '
    r'M2C_FIELD\((?P=dest), M2C_UNK \*, 4\) = M2C_UNALIGNED32\(sp4\); '
    r'M2C_FIELD\((?P=dest), M2C_UNK \*, 8\) = M2C_UNALIGNED32\(sp8\); '
    rf'M2C_FIELD\((?P=dest), s8 \*, 0xC\) = (?P<end>{NUMBER});'
)


def _relocated_packet(part, name, context, loc, body, end, lines):
    match = _RELOCATED_PACKET.fullmatch(body)
    if not match:
        return None
    signature = re.search(PARAMS.format(name=re.escape(name)), part.clean[:part.opening])
    expected = {f'sp{i}': 's8' for i in range(4)} | {match['dest']: 's8*', match['loop']: 's32'}
    payload = match['payload']
    if payload:
        expected.update({'sp4': 'u8', 'spC': 'M2C_UNK', match['read']: 'u8*', match['write']: 'u8*'})
    base = match['base']
    params = f's8 {match["arg"]}' + (f', u8 *{payload}' if payload else '')
    if (loc != expected or not signature or signature['parameters'] != params
            or match['loop'] != (match['counter'] if payload else match['clear'])
            or not re.search(rf'\bextern M2C_UNK {base};', part.clean[:part.opening])
            or re.search(rf'\bvolatile\b[^;{{}}\n]*\b{base}\b', context)):
        return None
    text = '\n'.join(' '.join(line.split()) for line in lines)
    for op, offset in (('addiu', match['offset']), ('sw', match['ready'])):
        region = re.findall(rf'{op} [^\n]+%lo\({base} \+ (?:\()?({NUMBER})(?: & 0xFFFF\))?\)', text)
        if integer(offset) not in map(integer, region):
            return None
    dests = re.findall(rf'addiu (\$\w+), \$zero, ({NUMBER})\nsb \1, ({NUMBER})?\(\$sp\)', text)
    values = [integer(match[f'byte{i}']) for i in range(3)]
    if ([(integer(offset or '0'), integer(value)) for _, value, offset in dests] != list(enumerate(values))
            or not re.search(r'sb \$a0, (?:0x3|3)\(\$sp\)', text)
            or not any(integer(num) == integer(match['end']) for _, num in re.findall(
                rf'addiu (\$\w+), \$zero, ({NUMBER})\nsb \1, (?:0x[cC]|12)\(\$\w+\)', text))):
        return None
    if payload:
        copied = re.search(r'lbu (\$\w+), (?:0x0|0)?\(\$a1\)\nsb \1, (?:0x0|0)?\(\$\w+\)', text)
        if not copied or not all(re.search(rf'addiu \$\w+, \$sp, (?:0x{slot:X}|{slot})(?:\n|$)', text, re.I)
                                 for slot in (4, 12)):
            return None
    p = P
    initial = ''.join(f'    {p}packet.bytes[{i}] = {value};\n' for i, value in enumerate(values))
    source_decl = f'    u8 *{p}src;\n' if payload else ''
    fill = (f'    {p}src = {payload};\n'
            f'    for ({p}i = 4; {p}i < 12; {p}i++) {p}packet.bytes[{p}i] = *{p}src++;\n') if payload else ''
    counter = f'    {p}i = 3;\n'
    before, after = ('', counter) if payload else (counter, '')
    return (part.source[:signature.start()] + f'''typedef struct {{ u8 bytes[12]; }} {p}packet_t;
{signature['signature']} {{
    {p}packet_t {p}packet;
    s32 {p}i;
    s8 *{p}dst;
{source_decl}
    {p}dst = (char *)&{base} + {match['offset']};
{before}    M2C_FIELD(&{base}, s32 *, {match['ready']}) = 1;
{initial}    {p}packet.bytes[3] = {match['arg']};
{fill}{after}    do {{
        *{p}dst = 0;
        {p}i -= 1;
        {p}dst += 1;
    }} while ({p}i >= 0);
    *({p}packet_t *){p}dst = {p}packet;
    M2C_FIELD({p}dst, u8 *, 0xC) = {match['end']};
}}''' + part.source[end+1:])


def _packet(part, name, context, loc, body, end):
    match = OUTGOING.fullmatch(body)
    signature = re.search(PARAMS.format(name=re.escape(name)), part.clean[:part.opening])
    if not match or not signature:
        return None
    params = re.fullmatch(rf'[su]8 (?P<page>{IDENT})(?:, u8 \*(?P<payload>{IDENT}))?', signature['parameters'])
    if not params or params['payload'] != match['payload']:
        return None
    slots = re.findall(rf'sp([0-3]) = ({NUMBER}|{IDENT});', match['bytes'])
    if [offset for offset, _ in slots] != list('0123') or slots[-1][1] != params['page']:
        return None
    if any(not re.fullmatch(NUMBER, value) or integer(value) > 255 for _, value in slots[:3]):
        return None
    transfer = match['payload'] is not None
    types = {f'sp{i}': 's8' for i in range(4)} | {match['dest']: 's8*', match['loop']: 's32'}
    if transfer:
        types.update({'sp4': 'u8', 'spC': 'M2C_UNK', match['read']: 'u8*', match['write']: 'u8*'})
    if (loc != types or len(types) != (10 if transfer else 6)
            or match['loop'] != (match['counter'] if transfer else match['clear'])):
        return None
    decl = _external(part, context, match['base'], 's8')
    if not decl:
        return None
    p = P
    initial = ''.join(f'    {p}packet.bytes[{i}] = {value};\n' for i, value in slots)
    cursor = f'    u8 *{p}src = {match["payload"]};\n' if transfer else ''
    fill = f'    for ({p}i = 4; {p}i < 12; {p}i++) {p}packet.bytes[{p}i] = *{p}src++;\n' if transfer else ''
    return (part.source[:decl.start()] + f'extern u8 {match["base"]}[];' + part.source[decl.end():signature.start()]
            + f'''typedef struct {{ u8 bytes[12]; }} {p}packet_t;
{signature['signature']} {{
    {p}packet_t {p}packet;
    u8 *{p}dst = {match['base']};
{cursor}    s32 {p}i;

    {match['ready']} = {match['ready_value']};
{initial}{fill}    for ({p}i = 3; {p}i >= 0; {p}i--) *{p}dst++ = 0;
    *({p}packet_t *){p}dst = {p}packet;
    {p}dst[12] = {match['end']};
}}''' + part.source[end+1:])


def _reply(part, name, context, loc, body, end, lines, resolve):
    match = INCOMING.fullmatch(body)
    signature = re.search(PARAMS.format(name=re.escape(name)), part.clean[:part.opening])
    if not match or not signature:
        return None
    params = re.fullmatch(rf's8 \*({IDENT}), s16 \*({IDENT})', signature['parameters'])
    if not params or params.groups() != (match['return'], match['arg']):
        return None
    types = {'sp0': 'M2C_UNK', 'sp4': 'u8', match['out']: 's16*', match['input']: 'M2C_UNK*',
             match['flags']: 's8', match['index']: 's32', match['bytes']: 'void*', match['status']: 'u32'}
    if match['offset']:
        types[match['input']] = 'void*'
    if loc != types or len(types) != 8 or integer(match['mask']) > 255 or integer(match['shift']) > 7:
        return None
    source = match['source']
    count = match['count']
    prefix = part.source[:signature.start()]
    if match['count_base']:
        if not match['offset'] or not resolve:
            return None
        count_base, count_off = match['count_base'], integer(match['count_off'])
        text = '\n'.join(' '.join(line.split()) for line in lines)
        bound = rf'lui (\$\w+), %hi\({count_base} \+ ({NUMBER})\)\nlbu \1, %lo\({count_base} \+ \2\)\(\1\)'
        offsets = [integer(offset) for _, offset in re.findall(bound, text)]
        cursor = rf'lui (\$\w+), %hi\({source} \+ ({NUMBER})\)\naddiu \1, \1, %lo\({source} \+ \2\)'
        if not any(integer(value) == integer(match['offset']) for _, value in re.findall(cursor, text)):
            return None
        base = resolve(count_base)
        if offsets != [count_off, count_off] or base is None or not 0 <= base + count_off <= 0xffffffff:
            return None
        count = f'D_{base + count_off:08X}'
        if re.search(rf'\b{count}\b', part.clean + context):
            return None
        prefix += f'extern u8 {count};\n'
        source = f'(u8 *)&{source} + {match["offset"]}'
    else:
        if match['offset']:
            return None
        decl = _external(part, context, source, 'M2C_UNK')
        if not decl:
            return None
        prefix = part.source[:decl.start()] + f'extern u8 {source}[];' + part.source[decl.end():signature.start()]
    p = P
    return (prefix
            + f'''typedef struct {{ u8 bytes[8]; }} {p}reply_t;
typedef struct {{ u16 word; u8 status; u8 error; }} {p}output_t;
{signature['signature']} {{
    {p}output_t *{p}out = ({p}output_t *){match['arg']};
    u8 *{p}cursor;
    {p}reply_t {p}reply;
    int {p}i;
    u8 {p}flags = 0;
    {p}cursor = {source};
    for ({p}i = 0; {p}i < {count}; {p}i++, {p}cursor += 8, {p}out++) {{
        {p}reply = *({p}reply_t *){p}cursor;
        {p}out->error = ({p}reply.bytes[2] & {match['mask']}) >> {match['shift']};
        if ({p}out->error == 0) {{
            {p}out->word = {p}reply.bytes[4] | ({p}reply.bytes[5] << 8);
            {p}out->status = {p}reply.bytes[6];
            {p}flags |= 1 << {p}i;
        }}
    }}
    *{match['return']} = {p}flags;
}}''' + part.source[end+1:])


def _words(part, name, context, loc, body, end, lines):
    signature = re.search(rf'\bs32\s+{re.escape(name)}\(s32 ({IDENT})\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    stores = []
    while hit := WORD_RUN.match(body):
        stores.append(hit)
        body = body[hit.end():].lstrip()
    result = WORD_RETURN.fullmatch(body)
    offsets = list(range(0, 24, 4))
    if (not result or result['index'] != signature[1] or len(stores) != 6 or not _word_copy(lines)
            or [integer(m['off']) for m in stores] != offsets
            or [integer('0x'+m['local'][2:]) for m in stores] != offsets
            or loc != {m['local']: 's32' for m in stores} or len({m['base'] for m in stores}) != 1):
        return None
    base = stores[0]['base']
    # The declaration is used once per copied word. Reject unrelated consumers.
    decl = re.search(rf'\bextern (?:M2C_UNK|s32) {base};', part.clean[:part.opening])
    if not decl or re.search(rf'\b{base}\b', context) or len(re.findall(rf'\b{base}\b', part.clean)) != 7:
        return None
    return (part.source[:decl.start()]
            + f'typedef struct {{ s32 words[6]; }} {P}words_t;\nextern {P}words_t {base};'
            + part.source[decl.end():part.opening+1] + f'''
    {P}words_t {P}table = {base};
    return {P}table.words[{result['index']}];
}}''' + part.source[end+1:])


def rewrite(source, name, asm, context='', resolve=None):
    """Leave drafts with incomplete copy or source evidence to ordinary generation."""
    if channel_status_drafts.RESULT in source and channel_status_drafts.RESULT in asm:
        if fixed := channel_status_drafts.rewrite(source, name, context, _lines(asm)):
            return fixed
    if 'osCreateMesgQueue' in source and 'osCreateMesgQueue' in asm:
        if fixed := message_frame_drafts.rewrite(source, name, context, _lines(asm)):
            return fixed
    if 'u8 sp' in source and 'nor' in asm and (target := formatted_stack_draft.target(_lines(asm))):
        if fixed := formatted_stack_draft.rewrite(source, name, context, target):
            return fixed
    if (('M2C_UNALIGNED32(' not in source and '+ sp)' not in source)
            or re.search(r'\b__m2c_copy_\w+\b', source+'\n'+context)
            or re.search(r'^\s*#\s*define\s+(bytes|word|status|error|words)\b', source+'\n'+context, re.M)):
        return None
    part = view(source, name)
    if not part:
        return None
    loc, body, end = _body(part)
    lines = _lines(asm)
    if _outgoing_copy(lines):
        return (_packet(part, name, context, loc, body, end)
                or _relocated_packet(part, name, context, loc, body, end, lines))
    if (copy := stack_copy(asm, (('lbu', 4), ('lbu', 5), ('lbu', 6)))) and copy[0] == 0:
        return _reply(part, name, context, loc, body, end, lines, resolve)
    return _words(part, name, context, loc, body, end, lines)
