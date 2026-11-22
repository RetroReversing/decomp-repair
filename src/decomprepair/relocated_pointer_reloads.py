"""Recover direct pointer reloads that a draft expresses as a global field."""

import re

from . import field_struct_view_repairs
from .csource import _blank, find
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import abi_register_names
from .mips_addresses import resolved
from .sdk_io_repairs import instructions
from .target_call_arity_repairs import _instructions

REG = r'\$[a-z0-9]+'
DIRECT = re.compile(rf'lw (?P<value>{REG}), %lo\((?P<symbol>{IDENT})\)\((?P<base>{REG})\)')
INDIRECT = re.compile(rf'lw (?P<value>{REG}), (?:0)?\((?P<base>{REG})\)')
FIELD = re.compile(rf'M2C_FIELD\(\s*&\s*(?P<base>{IDENT})\s*,\s*void\s*\*\s*\*\s*,\s*(?P<offset>{NUMBER})\s*\)')


def _early_halfword(rows):
    for i,(tag,left,_) in enumerate(rows):
        if tag==' ' or not re.fullmatch(r'lhu \$\w+, (?:0x[\da-fA-F]+|\d+)\(\$\w+\)',left):
            continue
        for j in range(i+1,len(rows)):
            if rows[j][2]!=left:
                continue
            middle = [a for _,a,_ in rows[i+1:j]]
            if any(a.startswith('subu ') for a in middle) and any(a.startswith('sw ') for a in middle):
                return True
    return False


def variants(source,name,header,rows,asm,resolve,flags=()):
    if resolve is None or not (part:=view(source,name)):
        return []
    context = header+'\n'+source
    definitions = re.findall(r'^\s*#\s*define\s+M2C_FIELD([^\n]*)',context,re.M)
    if (len(definitions)!=1 or re.sub(r'\s+','',definitions[0]) !=
            '(expr,type_ptr,offset)(*(type_ptr)((s8*)(expr)+(offset)))' or
            re.search(r'^\s*#\s*undef\s+M2C_FIELD\b',context,re.M)):
        return []
    witnesses = {}
    for mark,left,right in rows:
        a,b = DIRECT.fullmatch(left),INDIRECT.fullmatch(right)
        if mark==' ' or not a or not b or a['value']!=a['base'] or a['value']!=b['value']:
            continue
        witnesses.setdefault((a['symbol'],a['value'],b['base']),0)
        witnesses[(a['symbol'],a['value'],b['base'])] += 1
    eligible = []
    for (symbol,value,scratch),count in witnesses.items():
        sym,reg = re.escape(symbol),re.escape(scratch)
        if (count==2 and any(re.fullmatch(rf'lui {reg}, %hi\({sym}\)',y) for _,_,y in rows) and
                any(re.fullmatch(rf'addiu {reg}, {reg}, %lo\({sym}\)',y) for _,_,y in rows)):
            address = resolve(symbol)
            if address is not None:
                eligible.append((value,address))
    if len(eligible)!=1:
        return []
    value,address = eligible[0]
    lines = [f'{op} {" ".join(args.split())}'.strip() for op,args in _instructions(abi_register_names(asm))]
    words = instructions(asm)
    if len(lines)!=len(words):
        return []
    high = re.compile(rf'lui {re.escape(value)}, %hi\((?P<base>{IDENT})(?: \+ (?P<offset>{NUMBER}))?\)')
    low = re.compile(rf'lw {re.escape(value)}, %lo\((?P<base>{IDENT})(?: \+ (?P<offset>{NUMBER}))?\)\({re.escape(value)}\)')
    proven = 0
    for i in range(len(lines)-1):
        a,b = high.fullmatch(lines[i]),low.fullmatch(lines[i+1])
        if not a or not b or (a['base'],a['offset'])!=(b['base'],b['offset']):
            continue
        base = resolve(a['base'])
        pair = words[i].to_bytes(4,'big')+words[i+1].to_bytes(4,'big')
        if (base is not None and base+integer(a['offset'] or '0')==address and
                words[i]>>26==15 and words[i+1]>>26==35 and resolved(pair).get(4)==address):
            proven += 1
    if proven!=2 or not 0<=address<=0xffffffff or address%4:
        return []
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')',_blank(context),re.M))
    sites = []
    for hit in FIELD.finditer(part.clean,part.opening+1,part.end-1):
        base = resolve(hit['base'])
        if base is not None and hit['base'] not in macros and base+integer(hit['offset'])==address:
            sites.append(hit.span())
    alias = f'D_{address:08X}'
    if len(sites)!=2 or resolve(alias)!=address or re.search(rf'\b{alias}\b',context):
        return []
    pos = find(source,name)[0]
    fixed = edit(source,[(pos,pos,f'extern void *{alias};\n\n'),*((a,b,alias) for a,b in sites)])
    out = [('direct_pointer_reloads',fixed)]
    if '-fstrict-aliasing' not in flags and _early_halfword(rows):
        out.extend(('direct_pointer_reloads_with_field_view',candidate)
                   for _,candidate in field_struct_view_repairs.variants(fixed,name))
    return out
