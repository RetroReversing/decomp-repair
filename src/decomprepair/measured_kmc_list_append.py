"""Recover a target-proven list append from a draft with an uninitialized index."""

import re

from .compiler_phase_repairs import fresh
from .csource import find
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines

TARGET = re.compile(
    r'lw \$a3, (?P<table>\d+)\(\$a0\)\n'
    r'addiu \$v0, \$zero, (?P<mode>\d+)\n'
    r'bne \$a1, \$v0, [^\n]+\nnop\n'
    r'lw \$v0, (?P<count>\d+)\(\$a0\)\n'
    r'addiu \$v1, \$v0, 1\nsll \$v0, \$v0, 2\n'
    r'addu \$v0, \$v0, \$a3\n'
    r'sw \$v1, (?P=count)\(\$a0\)\nsw \$a2, (?:0)?\(\$v0\)\n'
    r'jr \$ra\nmove \$v0, \$zero'
)
FIELD = rf'M2C_FIELD\(\s*(?P<obj>{IDENT})\s*,\s*s32\s*\*\s*,\s*(?P<count>{NUMBER})\s*\)'
BODY = re.compile(
    rf'\s*s32\s+(?P<idx>{IDENT})\s*;\s*'
    rf'if\s*\(\s*(?P<mode>{IDENT})\s*==\s*(?P<literal>{NUMBER})\s*\)\s*{{\s*'
    rf'(?P<counter>{FIELD})\s*=\s*\(\s*s32\s*\)\s*\(\s*(?P=idx)\s*\+\s*1\s*\)\s*;\s*'
    rf'(?P<reload>(?P=idx)\s*=\s*(?P=counter)\s*;)\s*'
    rf'\*\s*\(\s*s32\s*\*\s*\)\s*\(\s*\(\s*(?P=idx)\s*\*\s*4\s*\)\s*\+\s*'
    rf'(?P<base>M2C_FIELD\(\s*(?P=obj)\s*,\s*s32\s*\*\s*,\s*(?P<table>{NUMBER})\s*\))\s*\)\s*'
    rf'=\s*(?P<value>{IDENT})\s*;\s*}}\s*return\s+0\s*;\s*'
)


def variants(source,name,header,rows):
    target = TARGET.fullmatch('\n'.join(normalized_integer_lines(left for _,left,_ in rows if left)))
    part = view(source,name)
    if not target or not part:
        return []
    definition = find(source,name)[0]
    signature = re.fullmatch(rf'\s*s32\s+{re.escape(name)}\s*\(\s*void\s*\*\s*({IDENT})\s*,\s*'
                             rf's32\s+({IDENT})\s*,\s*s32\s+({IDENT})\s*\)\s*',
                             part.clean[definition:part.opening])
    body = BODY.fullmatch(part.body)
    if not signature or not body or signature.groups()!=(body['obj'],body['mode'],body['value']):
        return []
    if (len({body[k] for k in ('idx','obj','mode','value')})!=4 or
            any(integer(body[key])!=int(target[key]) for key in ('table','count')) or
            integer(body['literal'])!=int(target['mode']) or
            abs(integer(body['table'])-integer(body['count']))<4):
        return []
    context = header+'\n'+source
    definitions = re.findall(r'^\s*#\s*define\s+M2C_FIELD([^\n]*)',context,re.M)
    if (len(definitions)!=1 or re.sub(r'\s+','',definitions[0]) !=
            '(expr,type_ptr,offset)(*(type_ptr)((s8*)(expr)+(offset)))' or
            re.search(r'^\s*#\s*undef\s+M2C_FIELD\b',context,re.M)):
        return []
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')',context,re.M))
    if macros & {body[k] for k in ('idx','obj','mode','value')}:
        return []
    table = fresh(source,header,'repair_list')
    offset = part.opening+1
    # Match offsets are relative to body. Move the existing read before its
    # first use and capture the target's unconditional list-base load.
    edits = [(offset+body.start('reload'),offset+body.end('reload'),''),
             (offset+body.start('counter'),offset+body.start('counter'),f'{body["idx"]} = {body["counter"]};\n        '),
             (offset+body.start('base'),offset+body.end('base'),table),
             (offset+body.start(),offset+body.start(),f'\n    s32 {table} = {body["base"]};')]
    return [('recover_list_append_index',edit(source,edits))]
