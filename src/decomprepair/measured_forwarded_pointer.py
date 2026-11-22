"""Try an unchanged entry pointer before a target's shifted call arguments."""

import re

from . import m2cfix
from .csource import _blank, find
from .integer_repair_support import IDENT, edit
from .pattern_repairs import close
from .target_call_arity_repairs import _instructions


def variants(source,name,header,asm):
    span = find(source,name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{',span[0],span[1])
    end = close(clean,opening,'{','}') if opening>=0 else None
    if not end:
        return []
    signature = re.fullmatch(rf'\s*void\s+{re.escape(name)}\s*\(\s*void\s*\*\s*({IDENT})\s*,\s*s32\s+({IDENT})\s*\)\s*',
                             clean[span[0]:opening])
    if not signature:
        return []
    ptr,arg = signature.groups()
    body = clean[opening+1:end-1]
    if (ptr==arg or re.search(r'\b(?:if|else|for|while|do|goto|switch|setjmp|longjmp|asm|__asm__)\b',body)
            or re.search(rf'(?<!&)\&\s*{re.escape(ptr)}\b|\b{re.escape(ptr)}\s*(?:=(?!=)|\+\+|--|[+\-*/]=)',body)
            or re.search(rf'\b(?:{IDENT})\s+\**\s*{re.escape(ptr)}\s*[;=,\[]',body)):
        return []
    ops = list(_instructions(asm))
    calls = [(i,args.split('+')[0].strip()) for i,(op,args) in enumerate(ops) if op=='jal']
    if len(calls)!=1:
        return []
    at,callee = calls[0]
    if at+1>=len(ops):
        return []
    allowed = {'addiu','addu','andi','lui','lhu','lw','move','nop','ori','sll','sw'}
    setup = ops[:at]+ops[at+1:at+2]
    if any(op not in allowed for op,_ in setup):
        return []
    a1_writes = []
    argslots = set()
    pointer_loads = 0
    for op,args in setup:
        args = re.sub(r'\s+','',args)
        if op not in {'sw','nop'} and re.match(r'^\$a0(?:,|$)',args):
            return []
        if op not in {'sw','nop'} and re.match(r'^\$a1(?:,|$)',args):
            a1_writes.append((op,args))
        if op=='lhu' and re.fullmatch(r'\$a[23],(?:0x[\da-fA-F]+|\d+)\(\$a0\)',args):
            pointer_loads += 1
        if op=='sw' and (m:=re.fullmatch(r'\$(?!ra\b)\w+,(0x[\da-fA-F]+|\d+)\(\$sp\)',args)):
            argslots.add(int(m[1],0))
    if pointer_loads<2 or len(a1_writes)!=1 or a1_writes[0][0]!='andi':
        return []
    mask = re.fullmatch(r'\$a1,\$a1,(0x[\da-fA-F]+|\d+)',a1_writes[0][1])
    if not mask:
        return []
    sites = list(re.finditer(rf'\b{re.escape(callee)}\s*\(',body))
    declarations = list(re.finditer(rf'\b{IDENT}\s+{re.escape(callee)}\s*\(([^()]*)\)\s*;',clean[:span[0]]))
    if len(sites)!=1 or len(declarations)!=1:
        return []
    site = opening+1+sites[0].end()-1
    stop = close(clean,site)
    if not stop:
        return []
    args = m2cfix._split_top_level(clean[site+1:stop-1])
    proto = declarations[0]
    params = m2cfix._split_top_level(proto[1])
    if (not args or len(params)!=len(args) or not all(re.fullmatch(r'\s*s32\s*',p) for p in params)
            or not re.fullmatch(rf'\s*{re.escape(arg)}\s*&\s*(0x[\da-fA-F]+|\d+)\s*',args[0])):
        return []
    source_mask = re.fullmatch(rf'\s*{re.escape(arg)}\s*&\s*(0x[\da-fA-F]+|\d+)\s*',args[0])
    if int(source_mask[1],0)!=int(mask[1],0):
        return []
    slots = {16+4*i for i in range(max(0,len(args)-3))}
    if argslots!=slots:
        return []
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')',_blank(header+'\n'+source),re.M))
    if macros & {ptr,arg,callee,'s32'}:
        return []
    return [('forward_entry_pointer_hypothesis',edit(source,[(site+1,site+1,ptr+', '),
                                                            (proto.start(1),proto.start(1),'void *, ')]))]
