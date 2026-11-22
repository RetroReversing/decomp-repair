"""Recover a bounded loop whose draft carries a synthetic first-iteration test."""

import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines

BODY = _shape('''
    s32 @flag; s32 @mode; s32 @carry; u32 @index; u8 @count;
    @count = M2C_FIELD(M2C_FIELD(&@source, void **, @srcoff), u8 *, @byteoff);
    @mode = M2C_FIELD(@obj, s32 *, @modeoff);
    @index = 1;
    if (@count != 0) {
        @flag = (@mode != 0) & (@mode != @modeval);
        @carry = 1U < 2U;
        do {
            if (@carry == 0) {
                if (@flag != 0) { goto @label; }
            } else {
@label:
                M2C_FIELD(&@dest, s32 *, @destoff) = @call(@obj, @index & 0xFF);
                @next(@obj);
            }
            @index += 1;
            @carry = @index < 2U;
        } while (@count >= @index);
    }
''', numbers=('srcoff','byteoff','modeoff','modeval','destoff'))
TARGET = re.compile(
    r'and \$s3, \$v1, \$v0\nmove \$s2, \$a0\nsltiu \$v0, \$s0, 2\n'
    r'bnez \$v0, [^\n]+\nmove \$a0, \$s1\nbeql \$s3, \$zero, [^\n]+\n'
    r'addiu \$s0, \$s0, 1\nmove \$a0, \$s1\njal '
)
CANDIDATE = re.compile(
    r'and \$s3, \$v1, \$v0\naddiu \$v1, \$zero, 1\nmove \$s2, \$a0\n'
    r'bnez \$v1, [^\n]+\nmove \$a0, \$s1\nbeql \$s3, \$zero, '
)


def variants(source,name,header,rows):
    target = '\n'.join(normalized_integer_lines(a for _,a,_ in rows if a))
    candidate = '\n'.join(normalized_integer_lines(b for _,_,b in rows if b))
    part = view(source,name)
    if not TARGET.search(target) or not CANDIDATE.search(candidate) or not part:
        return []
    draft = BODY.fullmatch(' '.join(part.body.split()))
    signature = re.fullmatch(rf'\s*void\s+{re.escape(name)}\s*\(\s*void\s*\*\s*({IDENT})\s*\)\s*',
                             part.clean[find(source,name)[0]:part.opening])
    if not draft or not signature or signature[1]!=draft['obj']:
        return []
    names = [draft[k] for k in ('flag','mode','carry','index','count','source','obj','dest','call','next','label')]
    context = header+'\n'+source
    definitions = re.findall(r'^\s*#\s*define\s+M2C_FIELD([^\n]*)',context,re.M)
    if (len(definitions)!=1 or re.sub(r'\s+','',definitions[0]) !=
            '(expr,type_ptr,offset)(*(type_ptr)((s8*)(expr)+(offset)))' or
            re.search(r'^\s*#\s*undef\s+M2C_FIELD\b',context,re.M)):
        return []
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')',_blank(context),re.M))
    if len(set(names))!=len(names) or macros & set(names):
        return []
    window = part.clean[part.opening+1:part.end-1]
    begin = re.search(rf'\b{re.escape(draft["index"])}\s*=\s*1\s*;',window)
    if not begin:
        return []
    start = part.opening+1+begin.start()
    stop = part.end-1
    if re.search(r'/\*|//',source[start:stop]):
        return []
    idx,count,mode = (draft[k] for k in ('index','count','mode'))
    body = (f'for ({idx} = 1; {idx} <= {count}; {idx}++) {{\n'
            f'        if ({idx} < 2U || (({mode} != 0) & ({mode} != {draft["modeval"]}))) {{\n'
            f'            M2C_FIELD(&{draft["dest"]}, s32 *, {draft["destoff"]}) = '
            f'{draft["call"]}({draft["obj"]}, {idx} & 0xFF);\n'
            f'            {draft["next"]}({draft["obj"]});\n        }}\n    }}\n')
    return [('carried_first_iteration_test',edit(source,[(start,stop,body)]))]
