"""Correct a target-proven double-scaled halfword index."""

import re

from . import leaf_frame_repairs
from .csource import _blank, find
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .narrow_store_repairs import declared

INDEX = re.compile(rf'\*\s*\(\s*\(\s*\(\s*(?P<index>{IDENT})\s*&\s*(?P<mask>{NUMBER})\s*\)\s*'
                   rf'\*\s*2\s*\)\s*\+\s*(?P<ptr>{IDENT})\s*\)')


def _masks(rows):
    target = normalized_integer_lines(left for _,left,_ in rows if left)
    candidate = normalized_integer_lines(right for _,_,right in rows if right)
    result = set()
    for lines, shift in ((target,1),(candidate,2)):
        matches = set()
        for a,b,c,d in zip(lines,lines[1:],lines[2:],lines[3:]):
            mask = re.fullmatch(r'andi (\$\w+), (\$\w+), (\d+)',a)
            if not mask:
                continue
            reg = re.escape(mask[1])
            if (re.fullmatch(rf'sll {reg}, {reg}, {shift}',b) and
                    re.fullmatch(rf'addu {reg}, {reg}, \$a0',c) and
                    re.fullmatch(rf'lhu \$\w+, (?:0)?\({reg}\)',d)):
                matches.add((mask[1],mask[2],int(mask[3])))
        result = matches if shift==1 else result & matches
    return {mask for _,_,mask in result}


def variants(source,name,header,rows,asm):
    masks = _masks(rows)
    part = view(source,name)
    if not masks or not part:
        return []
    signature = part.clean[find(source,name)[0]:part.opening]
    param = re.fullmatch(rf'\s*(?:s32|int)\s+{re.escape(name)}\s*\(\s*u16\s*\*\s*({IDENT})\s*\)\s*',signature)
    if not param:
        return []
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')',_blank(header+'\n'+source),re.M))
    out = []
    for hit in INDEX.finditer(part.clean,part.opening+1,part.end-1):
        if (hit['ptr']!=param[1] or integer(hit['mask']) not in masks or
                {hit['ptr'],hit['index']}&macros or
                declared(part,hit['ptr'],hit.start(),header)!=('u16','*') or
                declared(part,hit['index'],hit.start(),header)!=('s32','')):
            continue
        replacement = f'*(({hit["index"]} & {hit["mask"]}) + {hit["ptr"]})'
        fixed = edit(source,[(hit.start(),hit.end(),replacement)])
        out.append(('halfword_index_scale',fixed))
        # A separate existing family accounts for a target-only leaf frame.
        out.extend(('halfword_index_scale_with_frame',candidate)
                   for label,candidate in leaf_frame_repairs.variants(fixed,name,asm)
                   if label==leaf_frame_repairs.FRAME)
        break
    return out
