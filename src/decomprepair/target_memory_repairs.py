"""Bounded rewrites for observed memory accesses and register lifetimes."""

import re

from .csource import find
from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, integer
from .operand_lifetime_repairs import FLOAT, _escaped, _in_scope, _plain_expression, _typed_locals, _visible
from .pattern_repairs import close

POSTFIX = 'volatile_byte_postfix_reload'
ARM_OFFSET = 'one_arm_scaled_offset'
LOAD_DECREMENT = 'split_global_load_decrement'
FLOAT_LITERAL = 'post_call_float_literal'
TIMER = 'direct_countdown_field'
WORD = r'(?:s32|u32|int|unsigned(?:\s+int)?|signed(?:\s+int)?)'


def _statement(part, position):
    prefix = part.clean[part.opening+1:position].rstrip()
    return prefix[-1:] in ('',';','{','}') or bool(re.search(rf'(?:^|[;{{}}])\s*{IDENT}\s*:$',prefix))


def _prefix(part, name):
    return part.clean[:find(part.source,name)[0]]


def volatile_postfix(source, name, header, symbols):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    out = []
    for symbol in sorted(symbols):
        if not re.search(rf'\bextern\s+(?:volatile\s+(?:u8|unsigned\s+char)|(?:u8|unsigned\s+char)\s+volatile)\s+{symbol}\s*;',
                         context):
            continue
        if (re.search(rf'\b(?:{INTEGER})\s+\**\s*{symbol}\b',part.clean[len(_prefix(part,name)):])
                or re.search(rf'#\s*define\s+{symbol}\b',context)):
            continue
        for hit in re.compile(rf'\b{symbol}\s*\+=\s*(?:1[uU]?|0[xX]1[uU]?)\s*;').finditer(
                part.clean,part.opening+1,part.end-1):
            if _statement(part,hit.start()):
                out.append((POSTFIX,edit(source,[(hit.start(),hit.end(),f'{symbol}++;')])))
                if len(out)==2:
                    return out
    return out


def branch_offset(source, name, header, symbols):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    writes = _typed_locals(part,WORD)
    setup = re.compile(rf'(?P<offset>{IDENT})\s*=(?!=)\s*(?P<value>(?P<index>{IDENT})\s*\*\s*{NUMBER})\s*;')
    out = []
    for start in setup.finditer(part.clean,part.opening+1,part.end-1):
        offset,index = start['offset'],start['index']
        if offset==index or not _statement(part,start.start()) or not all(
            v in writes and not _escaped(part.body,v) and _in_scope(part,writes[v][1],start.start()) for v in (offset,index)
        ):
            continue
        if not _plain_expression(start['value'],context) or re.search(
            rf'\bvolatile\b[^;{{}}\n]*\b(?:{index}|{offset})\b|#\s*define\s+[^\n]*\b(?:{index}|{offset})\b',context
        ):
            continue
        # Permit a short enclosing test before the inner diamond. Both arms
        # must be single calls, so the inlined arithmetic has the same inputs.
        for guard in re.compile(r'\bif\s*\(').finditer(part.clean,start.end(),min(start.end()+420,part.end-1)):
            test_end = close(part.clean,guard.end()-1)
            opening = re.match(r'\s*{',part.clean[test_end:]) if test_end else None
            if not opening:
                continue
            first_start = test_end+opening.end()
            first_end = close(part.clean,first_start-1,'{','}')
            alt = re.match(r'\s*else\s*{',part.clean[first_end:]) if first_end else None
            second_start = first_end+alt.end() if alt else None
            second_end = close(part.clean,second_start-1,'{','}') if alt else None
            if not second_end:
                continue
            prefix = part.clean[start.end():first_start]
            if re.search(rf'\b(?:{index}|{offset})\s*(?:=(?!=)|\+\+|--|[-+*/|&^%]=)|'
                         rf'(?:\+\+|--)\s*(?:{index}|{offset})\b|\bgoto\b|(?:^|[;{{}}])\s*\w+\s*:',prefix):
                continue
            arms = [part.clean[first_start:first_end-1],part.clean[second_start:second_end-1]]
            calls = [re.fullmatch(rf'\s*({IDENT})\([^;{{}}]+\);\s*',arm) for arm in arms]
            if not all(calls) or calls[0][1]!=calls[1][1]:
                continue
            matches = [re.search(rf'(?<!\w)&?(?P<symbol>{IDENT})\s*\+\s*(?P<offset>{offset})\b',arm) for arm in arms]
            if not all(matches) or matches[0]['symbol']==matches[1]['symbol']:
                continue
            if any(len(re.findall(rf'\b{offset}\b',arm))!=1 for arm in arms):
                continue
            for beginning,hit in zip((first_start,second_start),matches):
                if hit['symbol'] in symbols:
                    out.append((ARM_OFFSET,edit(source,[(beginning+hit.start('offset'),beginning+hit.end('offset'),
                        f"(({writes[offset][0]})({start['value']}))")])))
                    if len(out)==2:
                        return out
    return out


def split_decrement(source, name, header, symbols):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    out = []
    types = _typed_locals(part,WORD)
    types.update({m[2]:(m[1],m.start()) for m in re.compile(rf'\b({WORD})\s+({IDENT})\s*=(?!=)\s*[^;{{}}]+;')
                  .finditer(part.clean,part.opening+1,part.end-1) if _statement(part,m.start())})
    pat = re.compile(rf'\b(?P<local>{IDENT})\s*=(?!=)\s*(?P<symbol>{IDENT})\s*-\s*(?P<one>1[uU]?)\s*;')
    for hit in pat.finditer(part.clean,part.opening+1,part.end-1):
        var,symbol = hit['local'],hit['symbol']
        if symbol not in symbols or var not in types or not _in_scope(part,types[var][1],hit.start()):
            continue
        if not _statement(part,hit.start()) or _escaped(part.body,var) or re.search(
            rf'\b(?:volatile|{INTEGER})\s+{symbol}\b',part.body
        ):
            continue
        declarations = re.findall(rf'\bextern\s+({INTEGER})\s+(?:{IDENT}\s*,\s*)*'
                                  rf'{symbol}(?:\s*,\s*{IDENT})*\s*;',context)
        if not declarations or len(set(declarations))!=1:
            continue
        signed_words = {'s32','int','signed','signed int'}
        if (types[var][0] in signed_words and (declarations[0] in {'u32','unsigned int'}
                or declarations[0] in signed_words and hit['one']!='1')):
            continue
        if re.search(rf'\bvolatile\b[^;{{}}\n]*\b{var}\b|#\s*define\s+[^\n]*\b{var}\b',context):
            continue
        prior = part.clean[types[var][1]:hit.start()]
        if not re.search(rf'(?:--\s*{var}\b|\b{var}\s*(?:--|-=\s*1\s*;))',prior):
            continue
        out.append((LOAD_DECREMENT,edit(source,[(hit.start(),hit.end(),f'{var} = {symbol}; --{var};')])))
        if len(out)==2:
            break
    return out


def post_call_float_literal(source, name, header, callees):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    literal = r'[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?[fF]?'
    init = re.compile(rf'\b(?P<type>{FLOAT})\s+(?P<var>{IDENT})\s*=\s*{literal}\s*;')
    result = []
    for hit in init.finditer(part.clean,part.opening+1,part.end-1):
        var = hit['var']
        if not _statement(part,hit.start()) or _escaped(part.body,var) or re.search(
            rf'#\s*define\s+[^\n]*\b{var}\b|\bgoto\b',context
        ):
            continue
        tail = part.clean[hit.end():part.end-1]
        stores = re.search(rf'(?P<a>{IDENT}\s*->\s*{IDENT}\s*=\s*{var}\s*;)\s*'
                           rf'(?P<b>{IDENT}\s*->\s*{IDENT}\s*=\s*{var}\s*;)',tail)
        if not stores or len(re.findall(rf'\b{var}\b',tail))!=2:
            continue
        before = tail[:stores.start()]
        reached = list(re.finditer(rf'\b({IDENT})\s*\(',before))
        if not any(m[1] in callees for m in reached):
            continue
        start,stop = hit.end()+stores.start(),hit.end()+stores.end()
        if not _statement(part,start):
            continue
        result.append((FLOAT_LITERAL,edit(source,[(hit.start(),hit.end(),''),
                       (start,start,'{ '+source[hit.start():hit.end()]+' '),(stop,stop,' }')])))
        if len(result)==2:
            break
    return result


def _word_field(context, expression, kind, offsets):
    if call := re.fullmatch(rf'({IDENT})\(\s*{IDENT}\s*,\s*(?P<type>{WORD})\s*,\s*(?P<off>{NUMBER})\s*\)',expression):
        if integer(call['off']) not in offsets or call['type']!=kind:
            return False
        definitions = re.findall(rf'#\s*define\s+{call[1]}\(\s*({IDENT})\s*,\s*({IDENT})\s*,\s*({IDENT})\s*\)\s+([^\n]+)',context)
        return bool(definitions and all(re.sub(r'\s+','',body)==f'(*({typ}*)(({base})+({offset})))'
                                        for base,typ,offset,body in definitions))
    member = re.fullmatch(rf'({IDENT})\s*->\s*({IDENT})',expression)
    if not member:
        return False
    receivers = set(re.findall(rf'\b((?:struct\s+)?{IDENT})\s*\*\s*{member[1]}\s*(?=[,);=])',context))
    if len(receivers)!=1:
        return False
    receiver = ' '.join(receivers.pop().split())
    fields = []
    for record in re.finditer(rf'\b(typedef\s+)?struct(?:\s+({IDENT}))?\s*{{',context):
        end = close(context,record.end()-1,'{','}')
        if not end:
            continue
        alias = re.match(rf'\s*({IDENT})\s*;',context[end:]) if record[1] else None
        if receiver==f'struct {record[2]}' or alias and receiver==alias[1]:
            fields.extend(re.findall(rf'(?:^|;)\s*({WORD})\s+{member[2]}\s*;',context[record.end():end-1]))
    return len(fields)==1 and fields[0]==kind


def direct_timer(source, name, header, offsets):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    if re.search(r'\bvolatile\b',part.body):
        return []
    types = _typed_locals(part,WORD)
    field = rf'(?:{IDENT}\s*->\s*{IDENT}|{IDENT}\(\s*{IDENT}\s*,\s*{WORD}\s*,\s*{NUMBER}\s*\))'
    shape = re.compile(rf'\b(?P<v>{IDENT})\s*=\s*(?P<field>{field})\s*;\s*'
                       rf'if\s*\(\s*(?P=v)\s*(?P<guard>[!<>]=?)\s*0\s*\)\s*{{\s*'
                       rf'(?P=v)\s*(?:-=\s*|=\s*(?P<unsigned>\(\s*(?:u32|unsigned\s+int)\s*\)\s*)?'
                       rf'(?P=v)\s*-\s*)(?P<step>{IDENT}|{NUMBER})\s*;\s*'
                       rf'(?P=field)\s*=\s*(?P=v)\s*;\s*if\s*\(\s*(?P=v)\s*(?P<last><=|>|==)\s*0\s*\)')
    out = []
    for hit in shape.finditer(part.clean,part.opening+1,part.end-1):
        var = hit['v']
        if var not in types or hit['guard'] not in ('!=','>') or not _statement(part,hit.start()):
            continue
        if _escaped(part.body,var) or len(re.findall(rf'\b{var}\b',part.body))!=1+len(re.findall(rf'\b{var}\b',hit[0])):
            continue
        field,step = hit['field'],hit['step']
        if not _word_field(context,field,types[var][0],offsets) or not _plain_expression(step,context):
            continue
        if hit['unsigned']:
            signature = part.clean[find(source,name)[0]:part.opening]
            step_type = re.search(rf'\b(?:u32|unsigned(?:\s+int)?)\s+{step}\s*(?=[,)])',signature)
            if not step_type and step not in [n for n,(kind,_) in types.items() if kind in {'u32','unsigned','unsigned int'}]:
                continue
        changed = f"if ({field} {hit['guard']} 0) {{ {field} -= {step}; if ({field} {hit['last']} 0)"
        out.append((TIMER,edit(source,[(hit.start(),hit.end(),changed)])))
        if len(out)==2:
            break
    return out
