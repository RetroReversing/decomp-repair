"""Typed width and floating lifetime proposals for MIPS register differences."""

import re

from .call_lifetime_repairs import block_path
from .integer_repair_support import IDENT, NUMBER, edit, integer, plain_repair_view

HALFWORD = 'signed_halfword_store_mask'
FLOAT_REUSE = 'dead_float_constant_reuse'
FLOAT = r'(?:f32|f64|float|double)'
FLOAT_VALUE = r'[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+[eE][+-]?[0-9]+)(?:[eE][+-]?[0-9]+)?[fF]?'
SHORT = r'(?:s16|short|signed\s+short)'


def halfword_use(source, name, header, masks):
    part = plain_repair_view(source,name,header)
    if not part:
        return []
    declarations = re.compile(rf'\b(?P<type>{SHORT})\s+(?P<var>{IDENT})\s*;')
    stores = re.compile(r'\*\(\s*(?:s16|u16|short|unsigned\s+short)\s*\*\s*\)[^;{}=]+=(?!=)\s*(?P<rhs>[^;{}]+);')
    result = []
    for decl in declarations.finditer(part.clean,part.opening+1,part.end-1):
        var = decl['var']
        tail = part.clean[decl.end():part.end]
        if len(re.findall(rf'\b{var}\s*=(?!=)',tail))!=1 or re.search(
                rf'(?<!&)&(?!&)\s*\(*\s*{var}\b|\b{var}\s*(?:\+\+|--|(?:[-+*/%|^&]|<<|>>)=)|'
                rf'(?:\+\+|--)\s*{var}\b|\b(?:sizeof|__alignof__)\s*\(?\s*{var}\b',tail):
            continue
        if len(re.findall(rf'\b(?:{SHORT}|s32|u32|int|u16|float|double)\s+{var}\b',part.body))!=1:
            continue
        load = re.search(rf'\b{var}\s*=\s*\*\(\s*{SHORT}\s*\*\s*\)\s*[^;{{}}]+;',tail)
        if not load:
            continue
        for store in stores.finditer(part.clean,decl.end()+load.end(),part.end-1):
            sites = [m for m in re.finditer(rf'\b{var}\b\s*&(?!&)\s*({NUMBER})',store['rhs'])
                     if integer(m[1]) in masks]
            if len(sites)!=1:
                continue
            start = store.start('rhs')+sites[0].start()
            result.append((HALFWORD,edit(source,[(*decl.span('type'),'int'),(start,start,'(unsigned short)')])))
            if len(result)==2:
                return result
    return result


def reused_float(source, name, header):
    part = plain_repair_view(source,name,header)
    if not part:
        return []
    declaration = re.compile(rf'\b(?P<type>{FLOAT})\s+(?P<var>{IDENT})\s*'
                             rf'(?:=\s*(?P<value>{FLOAT_VALUE})\s*)?;')
    locals_ = [d for d in declaration.finditer(part.clean,part.opening+1,part.end-1)
               if block_path(part,d.start()) == [part.opening]
               and part.clean[part.opening+1:d.start()].rstrip()[-1:] in ('',';')]
    types = {d['var']:d['type'] for d in locals_ if sum(e['var']==d['var'] for e in locals_)==1}
    literals = re.compile(rf'(?:(?P<type>{FLOAT})\s+)?(?P<var>{IDENT})\s*=(?!=)\s*(?P<value>{FLOAT_VALUE})\s*;')
    prior = []
    result = []
    for hit in literals.finditer(part.clean,part.opening+1,part.end-1):
        name = hit['var']
        if name not in types or block_path(part,hit.start())!=[part.opening]:
            continue
        if part.clean[part.opening+1:hit.start()].rstrip()[-1:] not in ('',';','}'):
            continue
        if re.search(rf'(?<!&)&(?!&)\s*\(*\s*{name}\b',part.body):
            continue
        tail = part.clean[hit.end():part.end-1]
        # The later constant must have a real use in a floating calculation.
        # Reject competing assignments and scopes that shadow this local.
        if (not re.search(rf'(?:[*/]\s*{name}\b|\b{name}\s*[*/])',tail)
                or re.search(rf'\b(?:{FLOAT}|int)\s+{name}\b|\b{name}\s*(?:=(?!=)|[-+*/]=)|'
                             rf'\b(?:sizeof|__alignof__)\s*\(?\s*{name}\b',tail)):
            prior.append(hit)
            continue
        for donor in reversed(prior):
            old = donor['var']
            if old==name or types[old]!=types[name] or re.search(rf'\b{old}\b',tail):
                continue
            between = part.clean[donor.end():hit.start()]
            if not re.search(rf'\b{old}\b',between) or re.search(rf'\b{old}\s*=(?!=)',between):
                continue
            uses = [m for m in re.finditer(rf'(?<![.>\w]){name}\b',tail)]
            if not uses:
                continue
            value = source[hit.start('value'):hit.end('value')]
            replacement = f'{old} = {value};'
            if hit['type']:
                replacement = f"{hit['type']} {name} = ({old} = {value});"
            result.append((FLOAT_REUSE,edit(source,[
                (hit.start(),hit.end(),replacement),
                *[(hit.end()+use.start(),hit.end()+use.end(),old) for use in uses],
            ])))
            if len(result)==2:
                return result
        prior.append(hit)
    return result
