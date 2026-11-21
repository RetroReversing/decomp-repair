"""Restore typed cursors and local records split into stack words by m2c."""

import re
from textwrap import dedent, indent

from .integer_repair_support import IDENT, NUMBER, integer, view
from .mips_returns import instructions
from .pattern_repairs import close
from .stack_read_retry import _decimal

FAMILY = 'ido_stack_iterator'
_SLOT = r'sp[0-9A-Fa-f]+'
_SAVE = r'\$s[0-7]'
_REG = r'\$\w+'
_GLOBAL = rf'(?P<global>{IDENT})'
_ENCODED = re.compile(r'/\*\s*[0-9a-fA-F]+\s+([0-9a-fA-F]{8})\s+([0-9a-fA-F]{8})\s*\*/')

# The two iterator calls share a state argument. The next-request load and
# pointer update must use the same offset and the same saved register.
_CALLS = re.compile(
    rf'jal (?P<start>{IDENT})\nor \$a1, (?P<req>{_SAVE}), \$zero\n'
    rf'or \$a0, (?P<iter_reg>{_SAVE}), \$zero\njal (?P<read>{IDENT})\n'
    rf'or \$a1, (?P<record_reg>{_SAVE}), \$zero\n'
)
_NEXT = re.compile(
    rf'lw (?P<head>{_REG}), (?P<stride>\d+)\((?P<base>{_SAVE})\)\n'
    r'addiu (?P=base), (?P=base), (?P=stride)\nbnel (?P=head), \$zero, \.L(?P<back>[0-9a-fA-F]{8})\n'
)
_WORD = re.compile(rf'lw {_REG}, (\d+)\(\$sp\)')

_SCAN = re.compile(
    rf'M2C_UNK (?P<it>{_SLOT}); M2C_UNK (?P<buffer>{_SLOT}); M2C_UNK (?P<record>{_SLOT}); '
    rf'(?P<slot_type>{IDENT}) \*(?P<slot>{IDENT}); s32 (?P<next>{IDENT}); s32 (?P<cursor>{IDENT}); '
    rf'(?P=cursor) = {_GLOBAL}; if \(\*(?P=cursor) != 0\) \{{ do \{{ '
    rf'(?P<start>{IDENT})\(&(?P=it), \(void \*\) (?P=cursor)\); '
    rf'if \((?P<read>{IDENT})\(&(?P=it), &(?P=record)\) != 0\) \{{ do \{{ '
    rf'if \((?P<index>{_SLOT}) >= 0\) \{{ '
    rf'(?P=slot) = &\(&(?P<table>{IDENT})\)\[(?P=index)\]; '
    rf'(?P<copy>{IDENT})\(&(?P=slot)->(?P<member>{IDENT})\[(?P<byte>{NUMBER})\], &(?P=buffer)\); '
    rf'M2C_FIELD\((?P=slot), s32 \*, (?P<store>{NUMBER})\) = (?P<word>{_SLOT}); \}} '
    rf'(?P<advance>{IDENT})\(&(?P=it)\); \}} while \((?P=read)\(&(?P=it), &(?P=record)\) != 0\); \}} '
    rf'(?P=next) = M2C_FIELD\((?P=cursor), s32 \*, (?P<stride>{NUMBER})\); (?P=cursor) \+= (?P=stride); '
    r'\} while \((?P=next) != 0\); \}'
)

_LOOKUP = re.compile(
    rf'M2C_UNK (?P<it>{_SLOT}); M2C_UNK (?P<buffer>{_SLOT}); M2C_UNK (?P<record>{_SLOT}); '
    rf's32 \*(?P<slot>{IDENT}); s32 (?P<item>{IDENT}); s32 (?P<next>{IDENT}); s32 (?P<cursor>{IDENT}); '
    rf's32 (?P<index_local>{IDENT}); u8 \*(?P<out_cursor>{IDENT}); u8 (?P<c>{IDENT}); u8 (?P<last>{IDENT}); '
    rf'(?P=slot) = &(?P<table>{IDENT})\[(?P<key>{IDENT})\]; (?P=item) = \*(?P=slot); '
    rf'(?P=cursor) = {_GLOBAL}; if \((?P=item) != 0\) \{{ '
    rf'(?P=c) = M2C_FIELD\((?P=item), u8 \*, (?P<byte>{NUMBER})\); (?P=index_local) = 0; '
    rf'\*(?P<out>{IDENT}) = (?P=c); if \((?P=c) != 0\) \{{ (?P=out_cursor) = (?P=out); do \{{ '
    r'(?P=index_local) \+= 1; (?P=out_cursor) \+= 1; '
    r'(?P=last) = M2C_FIELD\(\(\*(?P=slot) \+ (?P=index_local)\), u8 \*, (?P=byte)\); '
    r'\*(?P=out_cursor) = (?P=last); \} while \((?P=last) != 0\); \} return (?P<cached>\d+); \} '
    rf'if \(\*(?P=cursor) != 0\) \{{ (?P<outer>loop_\d+): '
    rf'(?P<start>{IDENT})\(&(?P=it), \(void \*\) (?P=cursor)\); '
    rf'if \((?P<read>{IDENT})\(&(?P=it), &(?P=record)\) != 0\) \{{ (?P<inner>loop_\d+): '
    rf'if \((?P<index>{_SLOT}) == (?P=key)\) \{{ '
    rf'(?P<copy>{IDENT})\((?P=out), &(?P=buffer)\); return (?P<found>\d+); \}} '
    rf'if \((?P<advance>{IDENT})\(&(?P=it)\) < 0\) \{{ return (?P<failure>{IDENT}); \}} '
    r'if \((?P=read)\(&(?P=it), &(?P=record)\) == 0\) \{ goto (?P<finish>block_\d+); \} goto (?P=inner); \} '
    rf'(?P=finish): (?P<cleanup>{IDENT})\(&(?P=it)\); '
    rf'(?P=next) = M2C_FIELD\((?P=cursor), s32 \*, (?P<stride>{NUMBER})\); (?P=cursor) \+= (?P=stride); '
    r'if \((?P=next) == 0\) \{ goto (?P<done>block_\d+); \} goto (?P=outer); \} (?P=done): return 0;'
)


def _target(asm):
    if not asm or 'bnel' not in asm or 'jal' not in asm:
        return None
    rows = instructions(asm)
    if not 30 <= len(rows) <= 128:
        return None
    text = _decimal('\n'.join(' '.join(row.split()) for row in rows) + '\n')
    calls = _CALLS.search(text)
    tail = _NEXT.search(text, calls.end()) if calls else None
    frame = re.search(r'(?m)^addiu \$sp, \$sp, -(\d+)$', text)
    if not tail or not frame or tail['base'] != calls['req']:
        return None
    addresses = _ENCODED.findall(asm)
    if len(addresses) != len(rows):
        return None
    entry = int(addresses[text.count('\n', 0, calls.start())][0], 16)
    pc, word = (int(raw, 16) for raw in addresses[text.count('\n', 0, tail.start()) + 2])
    displacement = word & 0xFFFF
    displacement -= 0x10000 if displacement & 0x8000 else 0
    if word >> 26 != 0x15 or pc + 4 + 4 * displacement != entry or int(tail['back'], 16) != entry:
        return None
    prefix = text[:calls.start()]
    global_load = re.search(rf'(?m)^lw {re.escape(calls["req"])}, %lo\(({IDENT})\)\({re.escape(calls["req"])}\)$', prefix)
    if not global_load or not re.search(rf'lw {_REG}, 0\({re.escape(calls["req"])}\)', prefix):
        return None
    offsets = {}
    for key in ('record', 'iter'):
        if not (match := re.search(rf'(?m)^addiu {re.escape(calls[key + "_reg"])}, \$sp, (\d+)$', prefix)):
            return None
        offsets[key] = int(match[1])
    stride = int(tail['stride'])
    state_size = (int(frame[1]) - offsets['iter']) & ~7
    if (not 8 <= stride <= 128 or stride % 4 or not 16 <= state_size <= 128
            or not 16 <= offsets['record'] < offsets['iter'] or any(n % 4 for n in offsets.values())):
        return None
    return text, calls, tail, global_load[1], offsets, state_size


def applies(asm):
    return _target(asm) is not None


def _word_at(text, slot):
    return any(int(match[1]) == slot for match in _WORD.finditer(text))


def rewrite(source, name, asm, header=''):
    if not source or 'M2C_UNK sp' not in source or '_m2c_iter_' in source + header or not (target := _target(asm)):
        return None
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return None
    clean = ' '.join(part.clean[part.opening + 1:end - 1].split())
    scan = _SCAN.fullmatch(clean)
    draft = scan or _LOOKUP.fullmatch(clean)
    if not draft:
        return None
    text, calls, tail, symbol, offsets, state_size = target
    slots = {key: int(draft[key][2:], 16) for key in ('it', 'record', 'buffer', 'index')}
    if (slots['it'] != offsets['iter'] or slots['record'] != offsets['record'] or slots['index'] != slots['record'] + 4
            or draft['global'] != symbol or integer(draft['stride']) != int(tail['stride'])
            or any(draft[key] != calls[key] for key in ('start', 'read'))):
        return None
    if not _word_at(text, slots['index']) or any(f'jal {draft[key]}\n' not in text for key in ('copy', 'advance')):
        return None
    if re.search(rf'\b{re.escape(draft["index"])}\b', header):
        return None

    if scan:
        body = _scan_body(draft, slots, text, state_size, header)
    else:
        body = _lookup_body(draft, slots, text, state_size, part.clean[:part.opening], name)
    if not body:
        return None
    return source[:part.opening + 1] + '\n' + indent(dedent(body).strip(), '    ') + '\n' + source[end - 1:]


def _scan_body(d, slots, text, state_size, header):
    scratch = slots['it'] - slots['buffer']
    word = int(d['word'][2:], 16)
    if (slots['buffer'] != slots['record'] + 12 or not 8 <= scratch <= 128
            or word != slots['it'] + 4 or not _word_at(text, word)
            or re.search(rf'\b{re.escape(d["word"])}\b', header)
            or not re.search(rf'addiu {_SAVE}, \$sp, {slots["buffer"]}\n', text)
            or not re.search(rf'jal {d["copy"]}\naddiu \$a0, {_SAVE}, {integer(d["byte"])}\n'
                             rf'lw (?P<word>{_REG}), {word}\(\$sp\)\nsw (?P=word), {integer(d["store"])}\({_SAVE}\)', text)):
        return None
    return f'''
        struct {{ s32 start; s32 word; u8 rest[{state_size - 8}]; }} _m2c_iter_state;
        u8 _m2c_iter_scratch[{scratch}];
        struct {{ s32 start; s32 index; s32 end; }} _m2c_iter_record;
        struct {{ s32 head; u8 rest[{integer(d['stride']) - 4}]; }} *{d['cursor']};
        {d['slot_type']} *{d['slot']};

        {d['cursor']} = (void *){d['global']};
        for (; {d['cursor']}->head != 0; {d['cursor']}++) {{
            {d['start']}((void *)&_m2c_iter_state, (void *){d['cursor']});
            while ({d['read']}((void *)&_m2c_iter_state, (void *)&_m2c_iter_record) != 0) {{
                if (_m2c_iter_record.index >= 0) {{
                    {d['slot']} = &(&{d['table']})[_m2c_iter_record.index];
                    {d['copy']}(&{d['slot']}->{d['member']}[{d['byte']}], _m2c_iter_scratch);
                    M2C_FIELD({d['slot']}, s32 *, {d['store']}) = _m2c_iter_state.word;
                }}
                {d['advance']}((void *)&_m2c_iter_state);
            }}
        }}
    '''


def _lookup_body(d, slots, text, state_size, signature, name):
    # The lookup profile places two unused words between the name array
    # and the next addressed local. The scan profile fills its whole span.
    size = slots['it'] - slots['buffer'] - 8
    signature = re.search(rf'\b{re.escape(name)}\(\s*u8\s*\*\s*{d["out"]},\s*s32\s+{d["key"]}\s*\)\s*$', signature)
    if (not signature or not 4 <= size <= 128 or size % 4 or slots['buffer'] != slots['record'] + 12
            or not re.search(rf'jal {d["copy"]}\naddiu \$a1, \$sp, {slots["buffer"]}\n', text)
            or not re.search(rf'jal {d["cleanup"]}\nor \$a0, {_SAVE}, \$zero\n', text)
            or len(re.findall(rf'lbu \$v0, {integer(d["byte"])}\({_REG}\)', text)) != 2):
        return None
    return f'''
        struct {{ s32 head; u8 rest[{integer(d['stride']) - 4}]; }} *{d['cursor']};
        struct {{ s32 start; s32 word; u8 rest[{state_size - 8}]; }} _m2c_iter_state;
        u8 *_m2c_iter_slot;
        s32 {d['index_local']};
        struct {{ s32 start; s32 index; s32 end; u8 name[{size}]; }} _m2c_iter_record;
        u8 {d['c']};

        _m2c_iter_slot = (u8 *){d['table']}[{d['key']}];
        {d['cursor']} = (void *){d['global']};
        if (_m2c_iter_slot != 0) {{
            {d['c']} = _m2c_iter_slot[{d['byte']}];
            {d['index_local']} = 0;
            {d['out']}[0] = {d['c']};
            if ({d['c']} != 0) {{
                do {{
                    {d['index_local']}++;
                    {d['c']} = ((u8 *){d['table']}[{d['key']}])[{d['index_local']} + {d['byte']}];
                    {d['out']}[{d['index_local']}] = {d['c']};
                }} while ({d['c']} != 0);
            }}
            return {d['cached']};
        }}
        for (; {d['cursor']}->head != 0; {d['cursor']}++) {{
            {d['start']}((void *)&_m2c_iter_state, (void *){d['cursor']});
            while ({d['read']}((void *)&_m2c_iter_state, (void *)&_m2c_iter_record) != 0) {{
                if (_m2c_iter_record.index == {d['key']}) {{
                    {d['copy']}({d['out']}, _m2c_iter_record.name);
                    return {d['found']};
                }}
                if ({d['advance']}((void *)&_m2c_iter_state) < 0) {{
                    return {d['failure']};
                }}
            }}
            {d['cleanup']}((void *)&_m2c_iter_state);
        }}
        return 0;
    '''
