"""Recover KMC halfword stores that share a value across a guarded exit."""

import re

from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TRIPLE = re.compile(
    rf'lui \$v1, %hi\((?P<gate>{IDENT})\)\nlw \$v1, %lo\((?P=gate)\)\(\$v1\)\n'
    r'addiu \$v0, \$zero, (?P<mode>\d+)\nbne \$v1, \$v0, 64\nnop\n'
    rf'lui \$v0, %hi\((?P<state>{IDENT})\)\nlw \$v0, %lo\((?P=state)\)\(\$v0\)\n'
    r'lhu \$v0, (?P<status>\d+)\(\$v0\)\nbne \$v0, \$v1, 64\n'
    r'addiu \$v0, \$zero, (?P<value>\d+)\n'
    rf'lui \$at, %hi\((?P<destone>{IDENT})\)\nsh \$v0, %lo\((?P=destone)\)\(\$at\)\n'
    rf'lui \$at, %hi\((?P<desttwo>{IDENT})\)\nsh \$v0, %lo\((?P=desttwo)\)\(\$at\)\n'
    rf'j (?P<name>{IDENT})\+92\nnop\n'
    r'lw \$v0, (?P<one>\d+)\(\$a0\)\nlui \$at, %hi\((?P=destone)\)\nsh \$v0, %lo\((?P=destone)\)\(\$at\)\n'
    r'lw \$v0, (?P<two>\d+)\(\$a0\)\nlui \$at, %hi\((?P=desttwo)\)\nsh \$v0, %lo\((?P=desttwo)\)\(\$at\)\n'
    rf'lw \$v0, (?P<three>\d+)\(\$a0\)\nlui \$at, %hi\((?P<destthree>{IDENT})\)\n'
    r'sh \$v0, %lo\((?P=destthree)\)\(\$at\)\njr \$ra\nnop'
)
_TRIPLE_SOURCE = _shape('''
    s32 @valuevar;
    if ((@gate == @mode) &&
        (@valuevar = @value, (M2C_FIELD(M2C_FIELD(&@owner, void **, @stateoff), u16 *, @status) == @gate))) {
        M2C_FIELD(&@dest, s16 *, @outone) = @value;
        M2C_FIELD(&@dest, s16 *, @outtwo) = @value;
    } else {
        M2C_FIELD(&@dest, s16 *, @outone) = (s16) M2C_FIELD(@arg, s32 *, @one);
        M2C_FIELD(&@dest, s16 *, @outtwo) = (s16) M2C_FIELD(@arg, s32 *, @two);
        @valuevar = M2C_FIELD(@arg, s32 *, @three);
    }
    M2C_FIELD(&@dest, s16 *, @outthree) = (s16) @valuevar;
''', numbers=('mode', 'value', 'stateoff', 'status', 'outone', 'outtwo', 'outthree', 'one', 'two', 'three'))


def variants(source, name, rows, resolve=None):
    if len(rows) != 28 or resolve is None:
        return []
    target = _TRIPLE.fullmatch('\n'.join(normalized_integer_lines(left for _, left, _ in rows if left)))
    if not target or target['name'] != name or not any(
        not left and right == f'addiu $a1, $zero, {target["value"]}'
        for left, right in zip(*(normalized_integer_lines(row[side] for row in rows) for side in (1, 2)))
    ):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    body = _TRIPLE_SOURCE.fullmatch(' '.join(part.clean[part.opening + 1:end - 1].split()))
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*({IDENT})\)\s*$', part.clean[:part.opening])
    if not body or not signature or signature[1] != body['arg'] or body['gate'] != target['gate']:
        return []
    literals = ('mode', 'status', 'value', 'one', 'two', 'three')
    if any(integer(body[key]) != int(target[key]) for key in literals):
        return []
    owner, dest = resolve(body['owner']), resolve(body['dest'])
    if owner is None or dest is None or owner + integer(body['stateoff']) != resolve(target['state']):
        return []
    for field in ('one', 'two', 'three'):
        if dest + integer(body['out' + field]) != resolve(target['dest' + field]):
            return []
    var, gate = body['valuevar'], body['gate']
    status = f'M2C_FIELD(M2C_FIELD(&{body["owner"]}, void **, {body["stateoff"]}), u16 *, {body["status"]})'
    left, right, tail = (f'M2C_FIELD(&{body["dest"]}, s16 *, {body["out" + field]})'
                         for field in ('one', 'two', 'three'))
    inputs = [f'M2C_FIELD({body["arg"]}, s32 *, {body[field]})' for field in ('one', 'two', 'three')]
    fixed = f'''
    s32 {var};

    if (({gate} == {body['mode']}) && (({var} = {status}) == {gate})) {{
        {var} = {body['value']};
        {left} = {var};
        {right} = {var};
    }} else {{
        {left} = (s16) {inputs[0]};
        {right} = (s16) {inputs[1]};
        {var} = {inputs[2]};
    }}
    {tail} = (s16) {var};
'''
    return [('measured_shared_halfword_literal', edit(part.source, [(part.opening + 1, end - 1, fixed)]))]
