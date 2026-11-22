"""Recover an evidenced halfword count loop with a prematurely used temporary."""

import re

from .csource import _blank, find
from .integer_repair_support import IDENT, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines

BODY = _shape('''
    s32 @tmp; s32 @idx;
    @idx = 0;
    if (*(&@table + ((@arg & 0xFFFF) * 2)) != 0) {
        do {
            @call(((@start + @tmp) * @stride) + &@data, @tmp);
            @tmp = @idx & 0xFFFF;
            @idx += 1;
        } while ((u32) (@idx & 0xFFFF) < (u16) *(((@arg & 0xFFFF) * 2) + &@table));
    }
''', numbers=('stride',))
COUNT = re.compile(
    rf'andi \$v0, \$a0, 65535\nsll \$v0, \$v0, 1\nlui \$at, %hi\((?P<table>{IDENT})\)\n'
    r'addu \$at, \$at, \$v0\nlhu \$v0, %lo\((?P=table)\)\(\$at\)\nbeqz \$v0, '
)
DATA = re.compile(rf'lui \$s2, %hi\((?P<data>{IDENT})\)\naddiu \$s2, \$s2, %lo\((?P=data)\)')
TABLE = re.compile(
    rf'andi \$v0, \$a0, 65535\nlui \$v1, %hi\((?P<table>{IDENT})\)\n'
    r'addiu \$v1, \$v1, %lo\((?P=table)\)\nsll \$v0, \$v0, 1\naddu \$s1, \$v0, \$v1'
)
LATCH = re.compile(r'lhu \$v1, (?:0)?\(\$s1\)\nsltu \$v0, \$v0, \$v1\nbnez \$v0, ')
CALL = re.compile(
    rf'lui \$v0, %hi\((?P<start>{IDENT})\)\nlhu \$v0, %lo\((?P=start)\)\(\$v0\)\n'
    r'andi \$a1, \$s0, 65535\naddu \$v0, \$v0, \$a1\n'
    r'sll \$a0, \$v0, 1\naddu \$a0, \$a0, \$v0\n'
    r'sll \$a0, \$a0, 3\naddu \$a0, \$a0, \$v0\nsll \$a0, \$a0, 2\n'
    rf'jal (?P<call>{IDENT})\naddu \$a0, \$a0, \$s2'
)


def variants(source,name,header,rows):
    target = '\n'.join(normalized_integer_lines(left for _,left,_ in rows if left))
    count,data,table_site,call,latch = (pattern.search(target) for pattern in (COUNT,DATA,TABLE,CALL,LATCH))
    part = view(source,name)
    if (not all((count,data,table_site,call,latch,part)) or
            not count.start()<data.start()<table_site.start()<call.start()<latch.start()):
        return []
    body = BODY.fullmatch(' '.join(part.body.split()))
    signature = re.fullmatch(rf'\s*void\s+{re.escape(name)}\s*\(\s*s32\s+({IDENT})\s*\)\s*',
                             part.clean[find(source,name)[0]:part.opening])
    if (not body or not signature or signature[1]!=body['arg'] or integer(body['stride'])!=100 or
            any(target_part[key]!=body[key] for target_part,key in
                ((count,'table'),(table_site,'table'),(data,'data'),(call,'start'),(call,'call')))):
        return []
    names = [body[k] for k in ('arg','idx','tmp','table','data','start','call')]
    if len(set(names))!=len(names) or re.search(r'/\*|//',source[part.opening+1:part.end-1]):
        return []
    context = _blank(header+'\n'+source)
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')',context,re.M))
    if macros & set(names):
        return []
    for key,typ in (('table','M2C_UNK'),('data','M2C_UNK'),('start','u16')):
        if not re.search(rf'\bextern\s+{typ}\s+{re.escape(body[key])}\s*;',context):
            return []
    idx,arg,table,start,data_name,callee = (body[k] for k in ('idx','arg','table','start','data','call'))
    count_expr = f'*(u16 *)((char *)&{table} + (({arg} & 0xFFFF) * 2))'
    code = (f'\n    s32 {idx};\n\n    {idx} = 0;\n    if ({count_expr} != 0) {{\n'
            f'        do {{\n            {callee}((({start} + ({idx} & 0xFFFF)) * 0x64) + '
            f'(char *)&{data_name}, ({idx} & 0xFFFF));\n            {idx} += 1;\n'
            f'        }} while ((u32) ({idx} & 0xFFFF) < (u16) {count_expr});\n    }}\n')
    return [('recover_halfword_count_loop',source[:part.opening+1]+code+source[part.end-1:])]
