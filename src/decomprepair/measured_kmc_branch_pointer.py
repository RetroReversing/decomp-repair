"""Keep the selected halfword pointer live across a branch."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'addiu \$sp, \$sp, -24\nsw \$s0, 16\(\$sp\)\nsw \$ra, 20\(\$sp\)\n'
    rf'jal (?P<disable>{IDENT})\nmove \$s0, \$a0\nandi \$s0, \$s0, 255\n'
    r'beqz \$s0, \d+\nmove \$a0, \$v0\n'
    rf'lui \$v1, %hi\((?P<pointer>{IDENT})\)\nlw \$v1, %lo\((?P=pointer)\)\(\$v1\)\n'
    rf'lhu \$v0, \(\$v1\)\nj (?P<name>{IDENT})\+\d+\nori \$v0, \$v0, 32\n'
    r'lui \$v1, %hi\((?P=pointer)\)\nlw \$v1, %lo\((?P=pointer)\)\(\$v1\)\n'
    r'lhu \$v0, \(\$v1\)\nandi \$v0, \$v0, 65503\n'
    rf'jal (?P<restore>{IDENT})\nsh \$v0, \(\$v1\)\n'
    r'lw \$ra, 20\(\$sp\)\nlw \$s0, 16\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 24'
)
_SOURCE = _shape('''
    s32 @state; u16 @value;
    @state = @disable();
    if (@input & 0xFF) { @value = *@pointer | 0x20; }
    else { @value = *@pointer & 0xFFDF; }
    *@pointer = @value;
    @restore(@state);
''')


def variants(source, name, header, rows):
    if len(rows) != 25:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    hit = _TARGET.fullmatch(target)
    if not hit or hit['name'] != name:
        return []
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (('', f'lui $v0, %hi({hit["pointer"]})') not in changes
            or ('', f'lw $v0, %lo({hit["pointer"]})($v0)') not in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    signature = re.search(rf'\bvoid {re.escape(name)}\(s32 ({IDENT})\)\s*$', part.clean[:part.opening])
    local = '__repair_branch_pointer'
    if (not draft or not signature or signature[1] != draft['input']
            or any(draft[key] != hit[key] for key in ('pointer', 'disable', 'restore'))
            or local in part.clean + _blank(header)
            or not re.search(rf'\bextern u16\s*\*{draft["pointer"]}\s*;', part.clean[:part.opening])):
        return []
    state, value, pointer = draft['state'], draft['value'], draft['pointer']
    fixed = f'''
    s32 {state};
    u16 {value};
    u16 *{local};

    {state} = {draft["disable"]}();
    if ({draft["input"]} & 0xFF) {{
        {local} = (u16 *){pointer};
        {value} = *{local} | 0x20;
    }} else {{
        {local} = (u16 *){pointer};
        {value} = *{local} & 0xFFDF;
    }}
    *{local} = {value};
    {draft["restore"]}({state});
'''
    return [('measured_branch_halfword_pointer', edit(source, [(part.opening + 1, part.end - 1, fixed)]))]
