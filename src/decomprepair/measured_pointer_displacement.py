"""Stage a byte pointer displacement for a measured MIPS register mismatch."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .narrow_store_repairs import declared
from .operand_lifetime_repairs import _escaped
from .target_memory_repairs import _statement

REG = r'\$[a-z0-9]+'
ADD = re.compile(rf'addu (?P<out>{REG}), (?P<a>{REG}), (?P<b>{REG})')
OFFSET = re.compile(rf'addiu (?P<out>{REG}), (?P<base>{REG}), -(?P<amount>\d+)')
ASSIGN = re.compile(rf'\b(?P<dst>{IDENT})\s*=\s*\(\s*(?P<base>{IDENT})\s*\+\s*(?P<offset>{IDENT})\s*\)\s*-\s*(?P<amount>{NUMBER})\s*;')


def variants(source,name,header,rows):
    target = normalized_integer_lines(left for _,left,_ in rows if left)
    candidate = normalized_integer_lines(right for _,_,right in rows if right)
    evidence = set()
    for first,second in zip(target,target[1:]):
        add,off = ADD.fullmatch(first),OFFSET.fullmatch(second)
        if not add or not off or (off['out'],off['base'])!=(add['out'],add['out']):
            continue
        for a,b in zip(candidate,candidate[1:]):
            peer,step = ADD.fullmatch(a),OFFSET.fullmatch(b)
            if (peer and step and peer.group()==add.group() and step['base']==add['out']
                    and step['out']!=step['base'] and step['amount']==off['amount']):
                evidence.add(int(off['amount']))
    if not evidence:
        return []
    part = view(source,name)
    if not part:
        return []
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')',_blank(header+'\n'+source),re.M))
    for hit in ASSIGN.finditer(part.clean,part.opening+1,part.end-1):
        dst,base,offset = (hit[k] for k in ('dst','base','offset'))
        if (integer(hit['amount']) not in evidence or not _statement(part,hit.start()) or
                len({dst,base,offset})!=3 or {dst,base,offset}&macros or _escaped(part.body,dst) or
                declared(part,dst,hit.start(),header)!=('void','*') or
                declared(part,base,hit.start(),header)!=('void','*') or
                declared(part,offset,hit.start(),header)!=('s32','')):
            continue
        replacement = f'{dst} = {base} + {offset}; {dst} = (void *)((char *){dst} - {hit["amount"]});'
        return [('split_pointer_displacement',edit(source,[(hit.start(),hit.end(),replacement)]))]
    return []
