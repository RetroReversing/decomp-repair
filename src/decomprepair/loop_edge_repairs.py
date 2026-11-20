"""Small source repairs at proven loop entry, retry, and back edges."""

import re

from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, integer
from .measured_control_repairs import automatic_integers
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible
from .pattern_repairs import close

SINK = 'loop_guard_sink_initializer'
RETRY = 'retry_edge_counter_reset'
ORDINARY = 'ordinary_backedge_byte_read'
CLAMP = 'shared_remask_clamp'
GUARD_CONSTANT = 'null_guard_store_constant'


def _statement(part, pos):
    return part.clean[part.opening+1:pos].rstrip()[-1:] in ('',';','{','}')


def sink_entry_initializer(source, name, header, steps):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    init = re.compile(rf'(?:(?P<type>{INTEGER})\s+)?(?P<var>{IDENT})\s*=\s*0(?:[uU])?\s*;')
    declared = _typed_locals(part,INTEGER)
    out = []
    for hit in init.finditer(part.clean,part.opening+1,part.end-1):
        var = hit['var']
        if not _statement(part,hit.start()) or _escaped(part.body,var):
            continue
        if re.search(rf'#\s*define\s+[^\n]*\b{var}\b',context):
            continue
        if not hit['type'] and (var not in declared or not _in_scope(part,declared[var][1],hit.start())):
            continue
        if len(re.findall(rf'\b{INTEGER}\s+{var}\b',part.body))>1:
            continue
        # Only independent scalar declarations may occur before the guard.
        guard = re.match(rf'\s*(?:(?:{INTEGER})\s+{IDENT}\s*=\s*{IDENT}\s*;\s*)*if\s*\(',
                         part.clean[hit.end():part.end-1])
        test_end = close(part.clean,hit.end()+guard.end()-1) if guard else None
        if not test_end or re.search(rf'\b{var}\b',part.clean[hit.end():test_end]):
            continue
        brace = re.match(r'\s*{',part.clean[test_end:part.end])
        enter = test_end+brace.end()-1 if brace else None
        end = close(part.clean,enter,'{','}') if enter is not None else None
        if not end or re.search(rf'\b{var}\b',part.clean[end:part.end]):
            continue
        loop = re.match(rf'(?P<setup>(?:\s*{IDENT}\s*=\s*&?{IDENT}\s*;)*)\s*(?P<loop>do|for|while)\b',
                        part.clean[enter+1:end-1])
        if not loop or re.search(rf'\b{var}\b',loop['setup']):
            continue
        inside = part.clean[enter+1+loop.start('loop'):end-1]
        changes = re.findall(rf'\b{var}\s*\+=\s*({NUMBER})\s*;',inside)
        if not set(map(integer,changes)) & steps and not (1 in steps and re.search(rf'\b{var}\+\+',inside)):
            continue
        if re.search(r'\bgoto\b|[;{}]\s*\w+\s*:',inside):
            continue
        at = enter+1+loop.start('loop')
        declaration = f"{hit['type']} {var};" if hit['type'] else ''
        out.append((SINK,edit(source,[(hit.start(),hit.end(),declaration),(at,at,f'{var} = 0; ')])))
        if len(out)==2:
            break
    return out


def reset_retry_counter(source, name, header, steps):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    locals_ = _typed_locals(part,INTEGER)
    available = automatic_integers(part,name) | {v for v in locals_ if not _escaped(part.body,v)}
    label = re.compile(rf'(?P<label>{IDENT})\s*:\s*(?P<offset>{IDENT})\s*=\s*0\s*;'
                       rf'\s*(?P<reset>(?P<counter>{IDENT})\s*=\s*0\s*;)\s*do\s*{{')
    out = []
    for hit in label.finditer(part.clean,part.opening+1,part.end-1):
        counter,offset,entry = hit['counter'],hit['offset'],hit['label']
        if counter==offset or not {counter,offset} <= available or re.search(
            rf'\bvolatile\s+[^;{{}}\n]*\b(?:{counter}|{offset})\b|#\s*define\s+[^\n]*\b(?:{counter}|{offset})\b',
            context,
        ):
            continue
        if any(v in locals_ and not _in_scope(part,locals_[v][1],hit.start()) for v in (counter,offset)):
            continue
        if len(re.findall(rf'\bgoto\s+{entry}\s*;',part.body))!=1:
            continue
        body_end = close(part.clean,hit.end()-1,'{','}')
        if not body_end:
            continue
        body = part.clean[hit.end():body_end-1]
        loop_steps = {integer(token) for token in re.findall(rf'\b{offset}\s*\+=\s*({NUMBER})\s*;',body)}
        if not loop_steps & steps or not re.search(rf'\b{counter}\s*(?:\+\+|\+=\s*1\s*;)',body):
            continue
        retry = re.search(rf'\bif\s*\(\s*{counter}\s*!=\s*{IDENT}\s*\)\s*(?P<edge>goto\s+{entry}\s*;)',
                          part.clean[body_end:part.end-1])
        if not retry:
            continue
        start,stop = (body_end+index for index in retry.span('edge'))
        out.append((RETRY,edit(source,[(hit.start(),hit.start(),f'{counter} = 0; '),
                                      (*hit.span('reset'),''),
                                      (start,stop,f'{{ {counter} = 0; {source[start:stop]} }}')])))
        if len(out)==2:
            break
    return out


def ordinary_backedge_read(source, name, header):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    # An ordinary struct member accessed through a plain local or pointer
    # parameter. No absolute addresses or other volatile fields are changed.
    read = re.compile(rf'\*\(\s*(?P<qual>volatile\s+)(?:u8|unsigned\s+char)\s*\*\s*\)\s*&\s*'
                      rf'(?P<field>\(\(\s*(?P<type>{IDENT})\s*\*\s*\)\s*{IDENT}\s*\)\s*->\s*(?P<member>{IDENT}))')
    out = []
    for loop in re.compile(r'\b(?:while\s*\([^;{}]*\)|for\s*\(\s*;\s*;\s*\)|do)\s*{').finditer(
            part.clean,part.opening+1,part.end-1):
        end = close(part.clean,loop.end()-1,'{','}')
        if not end:
            continue
        tail = re.search(rf'\b{IDENT}\s*=\s*(?P<read>{read.pattern})\s*;\s*$',part.clean[loop.end():end-1])
        if not tail:
            continue
        if not any(re.sub(r'\s+','',m['field'])==re.sub(r'\s+','',tail['field']) for m in
                   read.finditer(part.clean,part.opening+1,loop.start())):
            continue
        declared = False
        for record in re.finditer(r'\btypedef\s+struct(?:\s+\w+)?\s*{',context):
            close_record = close(context,record.end()-1,'{','}')
            if close_record and re.match(rf'\s*{tail["type"]}\s*;',context[close_record:]):
                fields = context[record.end():close_record-1]
                declared = bool(re.search(rf'(?:^|;)\s*(?:u8|unsigned\s+char)\s+{tail["member"]}\s*;',fields))
                break
        if declared:
            out.append((ORDINARY,edit(source,[(loop.end()+tail.start('qual'),loop.end()+tail.end('qual'),'')])))
            if len(out)==2:
                break
    return out


def shared_remask(source, name, header, bounds):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    shape = re.compile(rf'if\s*\(\s*(?P<key>{IDENT})\s*<\s*(?P<lo>{NUMBER})\s*\)\s*'
                       rf'(?P<brace1>{{)?\s*(?P<out>{IDENT})\s*=\s*(?P<left>{NUMBER})\s*;\s*(?(brace1)}})\s*'
                       rf'(?:else\s+)?if\s*\(\s*(?P=key)\s*(?P<op>>=|>)\s*(?P<hi>{NUMBER})\s*\)\s*'
                       rf'(?P<brace2>{{)?\s*(?P=out)\s*=\s*(?P<right>{NUMBER})\s*;\s*(?(brace2)}})\s*'
                       rf'(?P=key)\s*=\s*\(\s*(?:u16|unsigned\s+short)\s*\)\s*(?P=out)\s*;')
    types = _typed_locals(part,INTEGER)
    out = []
    for hit in shape.finditer(part.clean,part.opening+1,part.end-1):
        low,high = integer(hit['lo']),integer(hit['hi'])+(hit['op']=='>')
        key,dest = hit['key'],hit['out']
        if ((low,high) not in bounds or low>=high or integer(hit['left'])!=low or integer(hit['right'])!=high-1
                or key==dest or not _statement(part,hit.start())):
            continue
        if not all(v in types and _in_scope(part,types[v][1],hit.start()) and not _escaped(part.body,v) for v in (key,dest)):
            continue
        if re.search(rf'#\s*define\s+[^\n]*\b(?:{key}|{dest})\b|volatile\s+[^;{{}}]*\b(?:{key}|{dest})\b',context):
            continue
        text = f"{dest} = {key} < {hit['lo']} ? {hit['left']} : {key} {hit['op']} {hit['hi']} ? {hit['right']} : {dest}; {key} = (unsigned short){dest};"
        out.append((CLAMP,edit(source,[(hit.start(),hit.end(),text)])))
        if len(out)==2:
            break
    return out


def null_guard_constant(source, name, header, evidence):
    data = _visible(source,name,header)
    if not data:
        return []
    part,_ = data
    out = []
    for guard in re.compile(rf'\bif\s*\(\s*(?P<ptr>{IDENT})\s*!=\s*(?:NULL|0)\s*\)\s*{{').finditer(
            part.clean,part.opening+1,part.end-1):
        if not _statement(part,guard.start()):
            continue
        stop = close(part.clean,guard.end()-1,'{','}')
        if not stop:
            continue
        alt = re.match(r'\s*else\b',part.clean[stop:])
        if alt:
            continue
        body = part.clean[guard.end():stop-1]
        if re.search(r'\bgoto\b|(?:^|[;{}])\s*\w+\s*:',body):
            continue
        stores = re.compile(rf'\*\(\s*(?:s8|u8|signed\s+char|unsigned\s+char)\s*\*\s*\)\s*[^;={{}}]*?'
                            rf'\+\s*(?P<offset>{NUMBER})\s*\)+\s*=\s*(?P<value>{NUMBER})\s*;')
        for value,offsets in evidence:
            sites = [m for m in stores.finditer(body) if integer(m['value'])==value and integer(m['offset']) in offsets]
            if len({integer(m['offset']) for m in sites})<2:
                continue
            token = fresh(source,header,'repair_guard_byte')
            out.append((GUARD_CONSTANT,edit(source,[
                (guard.start(),guard.start(),f'{{ unsigned char {token}; '),
                (*guard.span('ptr'),f'({token} = {value}, {guard["ptr"]})'),
                (stop,stop,' }'),
                *[(guard.end()+m.start('value'),guard.end()+m.end('value'),token) for m in sites],
            ])))
            if len(out)==2:
                return out
    return out
