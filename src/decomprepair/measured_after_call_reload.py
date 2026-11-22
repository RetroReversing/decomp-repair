"""Recover a call followed by a target-proven relocated pointer reload."""

import re

from .csource import _blank, find
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .large_stack_drafts import _shape
from .mips import abi_register_names, normalized_integer_lines
from .mips_addresses import resolved
from .sdk_io_repairs import instructions
from .target_call_arity_repairs import _instructions

BODY = _shape('''
    M2C_FIELD(&@root, s32 *, @dest) = (s32) M2C_FIELD(M2C_FIELD(&@root, void **, @ptr), s32 *, @link);
    @call(M2C_FIELD(M2C_FIELD(&@root, void **, @ptr), s32 *, @link), M2C_FIELD(&@root, void **, @ptr));
''', numbers=('dest','ptr','link'))
ADDR = rf'(?P<base>{IDENT})(?: \+ (?P<off>{NUMBER}))?'
TARGET = re.compile(
    rf'lui \$a1, %hi\((?P<read>{ADDR})\)\n'
    r'lw \$a1, %lo\((?P=read)\)\(\$a1\)\n'
    rf'addiu \$sp, \$sp, -(?P<frame>{NUMBER})\nsw \$ra, (?P<slot>{NUMBER})\(\$sp\)\n'
    rf'jal (?P<call>{IDENT})\nlw \$a0, (?P<link>{NUMBER})\(\$a1\)\n'
    r'lui \$v0, %hi\((?P=read)\)\nlw \$v0, %lo\((?P=read)\)\(\$v0\)\n'
    r'lw \$v0, (?P=link)\(\$v0\)\n'
    rf'lui \$at, %hi\((?P<write>(?P<wbase>{IDENT})(?: \+ (?P<woff>{NUMBER}))?)\)\n'
    r'sw \$v0, %lo\((?P=write)\)\(\$at\)\n'
    r'lw \$ra, (?P=slot)\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, (?P=frame)'
)


def variants(source,name,header,asm,resolve):
    if resolve is None or not (part:=view(source,name)):
        return []
    signature = part.clean[find(source,name)[0]:part.opening]
    if not re.fullmatch(rf'\s*void\s+{re.escape(name)}\s*\(\s*void\s*\)\s*',signature):
        return []
    if re.search(r'/\*|//',source[part.opening+1:part.end-1]):
        return []
    draft = BODY.fullmatch(' '.join(part.body.split()))
    lines = [f'{op} {" ".join(args.split())}'.strip() for op,args in _instructions(abi_register_names(asm))]
    target = TARGET.fullmatch('\n'.join(normalized_integer_lines(lines)))
    words = instructions(asm)
    if not draft or not target or len(lines)!=len(words) or len(words)!=14:
        return []
    if draft['call']!=target['call'] or integer(draft['link'])!=integer(target['link']):
        return []
    source_base,read_base,write_base = (resolve(x) for x in (draft['root'],target['base'],target['wbase']))
    if None in (source_base,read_base,write_base):
        return []
    pointer = source_base+integer(draft['ptr'])
    dest = source_base+integer(draft['dest'])
    if (pointer!=read_base+integer(target['off'] or '0') or
            dest!=write_base+integer(target['woff'] or '0') or pointer%4 or dest%4):
        return []
    for high,low,opcode,expected in ((0,1,35,pointer),(6,7,35,pointer),(9,10,43,dest)):
        pair = words[high].to_bytes(4,'big')+words[low].to_bytes(4,'big')
        if words[high]>>26!=15 or words[low]>>26!=opcode or resolved(pair).get(4)!=expected:
            return []
    context = header+'\n'+source
    definitions = re.findall(r'^\s*#\s*define\s+M2C_FIELD([^\n]*)',context,re.M)
    if (len(definitions)!=1 or re.sub(r'\s+','',definitions[0]) !=
            '(expr,type_ptr,offset)(*(type_ptr)((s8*)(expr)+(offset)))' or
            re.search(r'^\s*#\s*undef\s+M2C_FIELD\b',context,re.M)):
        return []
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')',_blank(context),re.M))
    alias = f'D_{pointer:08X}'
    if (resolve(alias)!=pointer or re.search(rf'\b{alias}\b',context) or
            macros & {draft['root'],draft['call'],'s32'}):
        return []
    code = (f'\n    {draft["call"]}(M2C_FIELD({alias}, s32 *, {draft["link"]}), {alias});\n'
            f'    M2C_FIELD(&{draft["root"]}, s32 *, {draft["dest"]}) = '
            f'(s32) M2C_FIELD({alias}, s32 *, {draft["link"]});\n')
    return [('target_call_then_pointer_reload',edit(source,[(part.opening+1,part.end-1,code),
                                                            (find(source,name)[0],find(source,name)[0],
                                                             f'extern void *{alias};\n\n')]))]
