"""Recover a stack record when the linked draft loses the payload store."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'addiu \$sp, \$sp, -(?P<frame>\d+)\n'
    r'addiu \$v0, \$zero, (?P<tag>-?\d+)\naddiu \$a0, \$a0, (?P<delta>-?\d+)\n'
    r'(?P<store>sh|sw) \$a1, (?P<payload>\d+)\(\$sp\)\n'
    r'addiu \$a1, \$sp, (?P<record>\d+)\nmove \$a2, \$zero\n'
    r'sw \$ra, (?P<saved>\d+)\(\$sp\)\n'
    rf'jal (?P<callee>{IDENT})\nsh \$v0, (?P=record)\(\$sp\)\n'
    r'lw \$ra, (?P=saved)\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, (?P=frame)'
)
_SOURCE = re.compile(
    rf'\s*(?P<tagtype>[su]16)\s+(?P<tagvar>{IDENT})\s*;\s*'
    rf'(?P<payloadtype>[su](?:16|32))\s+(?P<payloadvar>{IDENT})\s*;\s*'
    rf'(?P=payloadvar)\s*=\s*(?P<second>{IDENT})\s*;\s*(?P=tagvar)\s*=\s*(?P<tag>-?{NUMBER})\s*;\s*'
    rf'(?P<callee>{IDENT})\s*\(\s*(?P<first>{IDENT})\s*\+\s*(?P<delta>-?{NUMBER})\s*,\s*'
    r'&\s*(?P=tagvar)\s*,\s*0\s*\)\s*;\s*'
)
_PREFIX = '__repair_stack_record'


def _immediate(text):
    return -integer(text[1:]) if text.startswith('-') else integer(text)


def variants(source, name, header, rows):
    if len(rows) != 12 or not rows[3][1] or rows[3][2]:
        return []
    wanted = normalized_integer_lines(left for _, left, _ in rows)
    found = normalized_integer_lines(right for _, _, right in rows)
    target = _TARGET.fullmatch('\n'.join(wanted))
    if not target or _PREFIX in source or _PREFIX in header:
        return []
    frame, record, payload, saved = (int(target[key]) for key in ('frame', 'record', 'payload', 'saved'))
    # The tag and data are four bytes apart. The missing store and shorter
    # frame are the only changes, with the saved return address shifted too.
    pad = saved - record - 8
    if (record < 16 or record % 4 or payload != record + 4 or saved != frame - 8
            or pad <= 0 or pad % 8 or pad > 64):
        return []
    lean_frame, lean_saved = frame - pad, saved - pad
    candidate = (
        f'addiu $sp, $sp, -{lean_frame}', *wanted[1:3], '', *wanted[4:6],
        f'sw $ra, {lean_saved}($sp)', *wanted[7:9], f'lw $ra, {lean_saved}($sp)', 'jr $ra',
        f'addiu $sp, $sp, {lean_frame}',
    )
    if found != candidate or not (part := view(source, name)):
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    body = _SOURCE.fullmatch(part.clean[part.opening + 1:end - 1])
    sig = re.search(
        rf'\bvoid\s+{re.escape(name)}\s*\(\s*(?:[su]32|void\s*\*)\s*({IDENT})\s*,\s*'
        rf'[su](?:16|32)\s+({IDENT})\s*\)\s*$', part.clean[:part.opening])
    if not body or not sig or sig.groups() != (body['first'], body['second']):
        return []
    if (body['callee'] != target['callee'] or body['callee'] == name
            or _immediate(body['tag']) != int(target['tag']) or _immediate(body['delta']) != int(target['delta'])
            or (target['store'] == 'sh') != body['payloadtype'].endswith('16')
            or len({body[key] for key in ('first', 'second', 'payloadvar', 'tagvar', 'callee')}) != 5):
        return []
    # Pass the address of the first member so the draft's pointer prototype
    # remains valid. The payload now belongs to the escaping object.
    obj = _PREFIX
    tag, data = f'{obj}_tag', f'{obj}_data'
    fixed = f'''
    struct {{
        {body['tagtype']} {tag};
        s16 {obj}_gap;
        {body['payloadtype']} {data};
        s32 {obj}_tail[{pad // 4}];
    }} {obj};

    {obj}.{data} = {body['second']};
    {obj}.{tag} = {body['tag']};
    {body['callee']}({body['first']} + {body['delta']}, &{obj}.{tag}, 0);
'''
    return [('measured_tagged_stack_record', edit(part.source, [(part.opening + 1, end - 1, fixed)]))]
