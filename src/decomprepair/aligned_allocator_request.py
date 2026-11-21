"""Recover a staged rounded request and the O32 allocator argument positions."""

import re

from .integer_repair_support import edit, view
from .large_stack_drafts import _shape
from .measured_stack_drafts import _lines

TARGET = re.compile(r'''lw \$v0, 16\(\$sp\)
mult \$a3, \$v0
mflo \$a3
lw \$v1, 8\(\$a2\)
lw \$v0, 0\(\$a2\)
addiu \$a0, \$zero, -16
lw \$a1, 4\(\$a2\)
addu \$v0, \$v0, \$v1
addiu \$a3, \$a3, 15
and \$a3, \$a3, \$a0
addu \$a0, \$a1, \$a3
sltu \$v0, \$v0, \$a0
bnez \$v0, (?P<exit>\.L\w+)
move \$t0, \$zero
move \$t0, \$a1
sw \$a0, 4\(\$a2\)
(?P=exit):
jr \$ra
move \$v0, \$t0''')
DRAFT = _shape('''
    u32 @end;
    u32 @start;
    u32 @result;
    @start = M2C_FIELD(arg2, u32 *, 4);
    @end = @start + (((arg3 * arg4) + 0xF) & ~0xF);
    @result = 0;
    if ((u32) (M2C_FIELD(arg2, s32 *, 0) + M2C_FIELD(arg2, s32 *, 8)) >= @end) {
        @result = @start;
        M2C_FIELD(arg2, u32 *, 4) = @end;
    }
    return @result;
''')


def applies(asm):
    if 'sltu' not in asm or 'mflo' not in asm:
        return False
    text = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                     if not line.startswith(('glabel ', 'endlabel ')))
    text = re.sub(r'(?m)^addu (\$\w+), (\$\w+), \$zero$', r'move \1, \2', text)
    text = re.sub(r'(?<!\w)-?0x[0-9a-fA-F]+\b', lambda hit: str(int(hit[0], 0)), text)
    return TARGET.fullmatch(text) is not None


def rewrite(source, name, asm, header=''):
    size = '__repair_alloc_size'
    if size in source + header or 'M2C_FIELD' not in source or not applies(asm):
        return None
    part = view(source, name)
    if not part:
        return None
    signature = re.search(rf'\bu32\s+{re.escape(name)}\((?P<args>(?:s32 arg0, s32 arg1, )?'
                          r'void \*arg2, s32 arg3, s32 arg4)\)\s*$', part.clean[:part.opening])
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    draft = DRAFT.fullmatch(' '.join(part.clean[start:end].split()))
    if not signature or not draft or len(set(draft.groups())) != 3:
        return None
    # The target reads its final argument from the fifth ABI slot. Keep the
    # unused first two parameters and let the compiler schedule the size local.
    body = f'''
    u32 {draft['end']};
    u32 {draft['start']};
    u32 {draft['result']};
    u32 {size};

    {size} = ((arg3 * arg4) + 0xF) & -0x10;
    {draft['start']} = M2C_FIELD(arg2, u32 *, 4);
    {draft['end']} = {draft['start']} + {size};
    {draft['result']} = 0;
    if ((u32) (M2C_FIELD(arg2, s32 *, 0) + M2C_FIELD(arg2, s32 *, 8)) >= {draft['end']}) {{
        {draft['result']} = {draft['start']};
        M2C_FIELD(arg2, u32 *, 4) = {draft['end']};
    }}
    return {draft['result']};
'''
    args = 's32 arg0, s32 arg1, void *arg2, s32 arg3, s32 arg4'
    return edit(source, [(*signature.span('args'), args), (start, end, body)])
