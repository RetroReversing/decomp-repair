"""Offer a no-argument callback hypothesis for a target's self-register call."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import abi_register_names
from .mips_addresses import resolved
from .sdk_io_repairs import instructions
from .target_call_arity_repairs import _instructions
from .target_memory_repairs import _statement

FIELD = (rf'M2C_FIELD\(\s*&\s*(?P<base>{IDENT})\s*,\s*M2C_UNK\s*'
         rf'\(\s*\*\s*\*\s*\)\s*\(\s*M2C_UNK\s*\)\s*,\s*(?P<offset>{NUMBER})\s*\)')
CALL = re.compile(rf'(?P<field>{FIELD})\s*\(\s*(?P=field)\s*\)\s*;')
HIGH = re.compile(rf'lui \$a0, %hi\((?P<base>{IDENT})(?: \+ (?P<offset>{NUMBER}))?\)')
LOW = re.compile(rf'lw \$a0, %lo\((?P<base>{IDENT})(?: \+ (?P<offset>{NUMBER}))?\)\(\$a0\)')


def variants(source,name,header,rows,asm,resolve):
    if resolve is None or not any(mark!=' ' and a=='nop' and re.fullmatch(r'move \$a0, \$\w+',b)
                                  for mark,a,b in rows):
        return []
    part = view(source,name)
    if not part:
        return []
    context = header+'\n'+source
    definitions = re.findall(r'^\s*#\s*define\s+M2C_FIELD([^\n]*)',context,re.M)
    if (len(definitions)!=1 or re.sub(r'\s+','',definitions[0]) !=
            '(expr,type_ptr,offset)(*(type_ptr)((s8*)(expr)+(offset)))' or
            re.search(r'^\s*#\s*undef\s+M2C_FIELD\b',context,re.M)):
        return []
    lines = [f'{op} {" ".join(args.split())}'.strip() for op,args in _instructions(abi_register_names(asm))]
    words = instructions(asm)
    if len(lines)!=len(words):
        return []
    witnesses = set()
    for i in range(len(lines)-2):
        high,low = HIGH.fullmatch(lines[i]),LOW.fullmatch(lines[i+1])
        if not high or not low or (high['base'],high['offset'])!=(low['base'],low['offset']):
            continue
        base = resolve(high['base'])
        if base is None:
            continue
        address = base+integer(high['offset'] or '0')
        pair = words[i].to_bytes(4,'big')+words[i+1].to_bytes(4,'big')
        if words[i]>>26!=15 or words[i+1]>>26!=35 or resolved(pair).get(4)!=address:
            continue
        for j in range(i+2,len(lines)-1):
            if lines[j]=='jalr $a0' and lines[j+1]=='nop':
                witnesses.add(address)
                break
            # Only stack setup and unrelated direct global stores can lie
            # between the callback load and call; none can redefine $a0.
            if not (re.fullmatch(r'addiu \$sp, \$sp, -?\w+',lines[j]) or
                    re.fullmatch(r'lui \$at, .+',lines[j]) or
                    re.fullmatch(r'sw \$(?!a0\b)\w+, .+',lines[j])):
                break
    if not witnesses:
        return []
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')',_blank(context),re.M))
    out = []
    for hit in CALL.finditer(part.clean,part.opening+1,part.end-1):
        base = resolve(hit['base'])
        if (not _statement(part,hit.start()) or hit['base'] in macros or base is None or
                base+integer(hit['offset']) not in witnesses):
            continue
        # MIPS leaves the callback in the argument register at jalr. That does
        # not prove the C prototype, so this is a judged alternative, not a fact.
        replacement = f'M2C_FIELD(&{hit["base"]}, void (**)(void), {hit["offset"]})();'
        out.append(('indirect_self_call_void_hypothesis',edit(source,[(hit.start(),hit.end(),replacement)])))
    return out[:1]
