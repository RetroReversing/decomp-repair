"""Expose a target-proven row offset before a small nested copy loop."""

import re

from .compiler_phase_repairs import fresh
from .csource import _blank, find
from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines

BODY = _shape('''
    char *@rowptr; char *@srcptr; f32 @value; s32 @col; s32 @row; s32 @dstptr;
    @rowptr = @src; @row = 0;
    do {
        @col = 0; @srcptr = @rowptr; @dstptr = @dst;
        @label:
        @value = *(f32 *)@srcptr; @srcptr += 4; @col += 1;
        *(f32 *)((@row * 4) + @dstptr) = @value;
        @dstptr += 0x10;
        if (@col < 4) { goto @label; }
        @row += 1; @rowptr += 0x10;
    } while (@row < 4);
''')
TARGET = re.compile(
    r'move \$a3, \$zero\nsll \$t1, \$t0, 2\nmove \$a2, \$a0\nmove \$v1, \$a1\n'
    r'lwc1 \$f0, \(\$a2\)\naddiu \$a2, \$a2, 4\naddu \$v0, \$t1, \$v1\n'
    r'addiu \$a3, \$a3, 1\nswc1 \$f0, \(\$v0\)'
)
CANDIDATE = re.compile(
    r'move \$a3, \$zero\nmove \$a2, \$a0\nmove \$v1, \$a1\n'
    r'lwc1 \$f0, \(\$a2\)\naddiu \$a2, \$a2, 4\naddiu \$a3, \$a3, 1\n'
    r'sll \$v0, \$t0, 2\naddu \$v0, \$v0, \$v1\nswc1 \$f0, \(\$v0\)'
)


def variants(source,name,header,rows):
    target = '\n'.join(normalized_integer_lines(a for _,a,_ in rows if a))
    candidate = '\n'.join(normalized_integer_lines(b for _,_,b in rows if b))
    part = view(source,name)
    if not TARGET.search(target) or not CANDIDATE.search(candidate) or not part:
        return []
    body = BODY.fullmatch(' '.join(part.body.split()))
    signature = re.fullmatch(rf'\s*void\s+{re.escape(name)}\s*\(\s*f32\s*\*\s*({IDENT})\s*,\s*s32\s+({IDENT})\s*\)\s*',
                             part.clean[find(source,name)[0]:part.opening])
    if not body or not signature or signature.groups()!=(body['src'],body['dst']):
        return []
    roles = [body[k] for k in ('rowptr','srcptr','value','col','row','dstptr','src','dst','label')]
    context = _blank(header+'\n'+source)
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')',context,re.M))
    if len(set(roles))!=len(roles) or macros & set(roles):
        return []
    row,col,srcptr,rowptr = (body[k] for k in ('row','col','srcptr','rowptr'))
    window = part.clean[part.opening+1:part.end-1]
    positions = []
    for pattern in (rf'\b{re.escape(srcptr)}\s*=\s*{re.escape(rowptr)}\s*;',
                    rf'\(\s*{re.escape(row)}\s*\*\s*4\s*\)',
                    rf'\b{re.escape(col)}\s*\+=\s*1\s*;',
                    rf'\b{re.escape(col)}\s*<\s*4\b'):
        hits = list(re.finditer(pattern,window))
        if len(hits)!=1:
            return []
        positions.append(hits[0])
    init,offset,increment,condition = positions
    local = fresh(source,header,'repair_row_offset')
    base = part.opening+1
    changes = [(base,base,f'\n    s32 {local};'),
               (base+init.start(),base+init.start(),f'{local} = {row} * 4;\n        '),
               (base+offset.start(),base+offset.end(),local),
               (base+increment.start(),base+increment.end(),''),
               (base+condition.start(),base+condition.end(),f'++{col} < 4')]
    return [('invariant_row_offset',edit(source,changes))]
