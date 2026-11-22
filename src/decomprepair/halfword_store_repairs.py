"""Explicit narrowing at proven unsigned-halfword stores; no invented objects or value uses."""
import re

from . import integer_abi, local_flow, macro_address_repairs, narrow_store_repairs
from .integer_repair_support import IDENT, edit, locals_for, view

FAMILY='halfword_store_normalization'
FAMILIES=(FAMILY,)
LIMIT=8
HELPER='__repair_store_halfword'


def sites(source,name,header='',arch=None):
    part=view(source,name)
    context=header+'\n'+source
    if not part or arch not in integer_abi.ARCHES or re.search(r'\b(?:volatile|asm|__asm__|restrict|_Atomic|__LINE__|__COUNTER__)\b',source):return []
    if HELPER in context or integer_abi.scalar('int',context,arch)!=(32,True):return []
    if integer_abi.scalar('short',context,arch)!=(16,True):return []
    keywords=set(re.findall(r'(?m)^\s*#\s*define\s+('+IDENT+r')\b',context))
    if keywords & {'int','short','unsigned','signed','static','inline'}:return []
    declarations={d['name']:d for d in locals_for(part)}
    macros=macro_address_repairs.definitions(source,header,part.opening)
    opaque=set(re.findall(r'(?m)^\s*#\s*define\s+('+IDENT+r')\b',context))-macros.keys()
    try:flow=local_flow.analyze(source,name)
    except (ValueError,RecursionError):return []
    if not flow:return []
    result=[]
    for node in flow.nodes:
        text=part.clean[node.start:node.end]
        hit=re.fullmatch(r'\s*(.+?)\s*=(?!=)\s*('+IDENT+r')\s*;\s*',text,re.S)
        if not hit or hit[2] not in declarations:continue
        decl=declarations[hit[2]]
        # Preserve the parameter's int conversion for every admitted input.
        if integer_abi.scalar(decl['type'],context,arch) not in {(16,False),(16,True),(32,True)}:continue
        # Resolve the actual lexical declaration, not a same-named sibling or parameter.
        if narrow_store_repairs.declared(part,hit[2],node.start,header)!=(decl['type'],''):continue
        if re.search(r'(?<!&)&(?!&)\s*\(*\s*'+re.escape(hit[2])+r'\b',part.body):continue
        lhs=hit[1].strip()
        if set(re.findall(IDENT,lhs+' '+hit[2]))&opaque:continue
        typ=narrow_store_repairs.field_type(part,lhs,node.start,header,arch)
        macro=macro_address_repairs.invocation(lhs,macros)
        if macro:
            kind=macros[macro[0]][0]
            if kind.endswith('*') and not kind.endswith('**') and all(re.fullmatch(r'[\w\s()+\-*/&|^~<>]+',a) and not re.search(r'\+\+|--|\b'+IDENT+r'\s*\(',a) for a in macro[1]):
                typ=kind[:-1]
        # Direct cast/dereference stores; qualifiers and compound/effectful addresses decline.
        direct=re.fullmatch(r'\(?\s*\*\s*\(\s*('+IDENT+r'(?:\s+'+IDENT+r')*)\s*\*\s*\)\s*([\w\s()+\-*/&|^~<>]+?)\s*\)?',lhs)
        if direct:typ=direct[1]
        if integer_abi.scalar(typ or '',context,arch)!=(16,False):continue
        if re.search(r'\+\+|--|\b'+IDENT+r'\s*\(',lhs) and not macro:continue
        start=node.start+hit.start(2);end=node.start+hit.end(2)
        result.append(dict(start=start,end=end,value=hit[2],line=source.count('\n',0,start)+1,lhs=lhs[:100]))
    return result[:LIMIT]


def local_record_sites(source,name,header='',arch=None):
    """Stores into the halfword members of a struct the function declares itself (m2c's `locals`), of a local
    (`locals.a = v;`) or of a halfword cast of one (`locals.a = (s16) v;`). The member's own type may be signed:
    the conversion the store makes is the same, and so is the extra pseudo the compiler keeps for it."""
    part=view(source,name)
    context=header+'\n'+source
    if not part or arch not in integer_abi.ARCHES or re.search(r'\b(?:asm|__asm__|restrict|_Atomic|__LINE__|__COUNTER__)\b',source):return []
    if HELPER in context or integer_abi.scalar('int',context,arch)!=(32,True) or integer_abi.scalar('short',context,arch)!=(16,True):return []
    records={}
    for record in re.finditer(r'(?m)^[ \t]*struct\s*\{(?P<body>[^{}]*)\}\s*(?P<name>'+IDENT+r')\s*;',part.clean[part.opening:part.end]):
        for member in re.finditer(r'(?P<type>(?:unsigned\s+|signed\s+)?'+IDENT+r')\s+(?P<names>'+IDENT+r'(?:\s*,\s*'+IDENT+r')*)\s*;',record['body']):
            for member_name in re.split(r'\s*,\s*',member['names']):
                records.setdefault((record['name'],member_name),member['type'])
    if not records or re.search(r'\bvolatile\b',part.body):return []
    declarations={d['name']:d for d in locals_for(part)}
    for plain in re.finditer(r'(?m)^[ \t]*((?:unsigned\s+|signed\s+)?'+IDENT+r')[ \t]+('+IDENT+r'(?:[ \t]*,[ \t]*'+IDENT+r')+)[ \t]*;',part.clean[part.opening:part.end]):
        for each in re.split(r'\s*,\s*',plain[2]):declarations.setdefault(each,dict(name=each,type=plain[1]))
    result=[]
    for hit in re.finditer(r'(?m)^[ \t]*('+IDENT+r')\.('+IDENT+r')[ \t]*=[ \t]*(?:\(\s*('+IDENT+r')\s*\)\s*)?('+IDENT+r')[ \t]*;',part.clean[part.opening:part.end]):
        record,member,cast,value=hit.groups()
        kind=records.get((record,member))
        if kind is None or integer_abi.scalar(kind,context,arch) not in {(16,True),(16,False)}:continue
        if cast is not None and integer_abi.scalar(cast,context,arch) not in {(16,True),(16,False)}:continue
        if value not in declarations or integer_abi.scalar(declarations[value]['type'],context,arch) not in {(16,False),(16,True),(32,True)}:continue
        if re.search(r'(?<!&)&(?!&)\s*\(*\s*'+re.escape(value)+r'\b',part.body):continue
        start=part.opening+(part.clean[part.opening:].rfind('(',0,hit.start(3)) if cast is not None else hit.start(4));end=part.opening+hit.end(4)
        result.append(dict(start=start,end=end,value=value,line=source.count('\n',0,start)+1,lhs=record+'.'+member))
    return result[:LIMIT]


def variants(source,name,header='',arch=None):
    points=sites(source,name,header,arch)
    from .normalization_repairs import definition_before
    definition=f'static inline short {HELPER}(int x){{x=(unsigned int)x<<16;x=(int)x>>16;return x;}}\n'
    result=[(FAMILY,definition_before(edit(source,[(p['start'],p['end'],HELPER+'('+p['value']+')')]),name,definition)) for p in points]
    members=local_record_sites(source,name,header,arch)
    # one step at a time shows no gain when each narrowing keeps a pseudo the compiler later folds: all of them together
    # is the variant that reserves their slots (a frame three halfword stores short matched only with all three)
    for chosen in ([[m] for m in members]+([members] if len(members)>1 else [])):
        result.append((FAMILY,definition_before(edit(source,[(m['start'],m['end'],HELPER+'('+m['value']+')') for m in chosen]),name,definition)))
    return list(dict.fromkeys(result))
