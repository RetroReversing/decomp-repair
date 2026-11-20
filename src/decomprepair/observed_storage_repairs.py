"""Small storage repairs enabled by measured reloads and stack displacements."""

import re

from .call_lifetime_repairs import block_path
from .compiler_phase_repairs import fresh
from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, plain_repair_view
from .pattern_repairs import close

RELOAD = 'staged_field_reload'
STACK = 'adjacent_stack_redistribution'
FIELD = rf'{IDENT}\s*->\s*{IDENT}'
FLOAT = r'(?:f32|float|f64|double)'
ARRAY = re.compile(rf'(?P<type>{FLOAT}|u8|s8|u16|s16|u32|s32|char|short|int)\s+'
                   rf'(?P<name>{IDENT})\s*\[\s*(?P<count>{NUMBER})\s*\]\s*;')
WIDTH = {'float':4, 'f32':4, 'double':8, 'f64':8, 'u8':1, 's8':1, 'char':1,
         'u16':2, 's16':2, 'short':2, 'u32':4, 's32':4, 'int':4}


def _float_field(context, base, field):
    types = set(re.findall(rf'\b((?:struct\s+)?{IDENT})\s*\*\s*{base}\s*(?=[,);=])',context))
    if len(types) != 1:
        return None
    wanted = ' '.join(types.pop().split())
    fields = []
    for record in re.finditer(rf'\b(typedef\s+)?struct(?:\s+({IDENT}))?\s*{{',context):
        end = close(context,record.end()-1,'{','}')
        if not end:
            continue
        alias = re.match(rf'\s*({IDENT})\s*;',context[end:]) if record[1] else None
        if wanted == f'struct {record[2]}' or alias and wanted == alias[1]:
            member = re.search(rf'(?:^|;)\s*({FLOAT})\s+{field}\s*;',context[record.end():end-1])
            if member:
                fields.append(member[1])
    return fields[0] if len(fields) == 1 else None


def staged_reload(source, name, header, width):
    part = plain_repair_view(source, name, header)
    if not part or width not in {4, 8} or re.search(r'\b(?:asm|__asm__|goto|volatile)\b', part.body):
        return []
    context = _blank(header)+'\n'+part.clean
    stores = re.compile(rf'(?P<field>{FIELD})\s*=(?!=)\s*[^;{{}}]+;')
    options = []
    for write in stores.finditer(part.clean, part.opening+1, part.end-1):
        base, field = re.split(r'\s*->\s*', write['field'])
        prefix = part.clean[part.opening+1:write.start()].rstrip()
        if prefix and prefix[-1] not in ';{}':
            continue
        kind = _float_field(context, base, field)
        if WIDTH.get(kind) != width:
            continue
        between = re.compile(rf'\s*{base}\s*->\s*(?!{field}\b){IDENT}\s*=(?!=)\s*(?:{NUMBER}|{IDENT})\s*;')
        end = write.end()
        while (store := between.match(part.clean, end)) and end-write.end() < 300:
            end = store.end()
        if end == write.end():
            continue
        copy = re.match(rf'\s*{base}\s*->\s*(?!{field}\b){IDENT}\s*=\s*'
                        rf'(?P<read>{base}\s*->\s*{field})\s*;', part.clean[end:])
        if not copy:
            continue
        lhs = source[write.start('field'):write.end('field')]
        # Use a compound statement so the temporary declaration works on C89
        # compilers without moving the original write into a declaration.
        temp = fresh(source, header, 'repair_reload')
        stop = end+copy.end()
        options.append(edit(source, [
            (write.start(), write.start(), f'{{ {kind} {temp}; '),
            (write.end(), write.end(), f' {temp} = *(volatile {kind} *)&({lhs});'),
            (end+copy.start('read'), end+copy.end('read'), temp),
            (stop, stop, ' }'),
        ]))
        if len(options) > 1:
            return []
    return [(RELOAD, candidate) for candidate in options]


def redistribute(source, name, header, displacements):
    part = plain_repair_view(source, name, header)
    if not part or not displacements or re.search(r'\b(?:asm|__asm__|goto)\b', part.body):
        return []
    arrays = [a for a in ARRAY.finditer(part.clean, part.opening+1, part.end-1)
              if block_path(part, a.start()) == [part.opening]
              and part.clean[part.opening+1:a.start()].rstrip()[-1:] in ('', ';')]
    result = []
    for first, second in zip(arrays, arrays[1:]):
        if part.clean[first.end():second.start()].strip() or first['type'] != second['type']:
            continue
        tail = part.clean[second.end():part.end]
        for spare, used in ((first, second), (second, first)):
            spare_name, used_name = spare['name'], used['name']
            if re.search(rf'\b{spare_name}\b', tail) or not re.search(rf'\b{used_name}\b', tail):
                continue
            if re.search(rf'\bsizeof(?:\s*\()*\s*{used_name}\b|&\s*{used_name}\b(?!\s*\[)', tail):
                continue
            width = WIDTH[used['type']]
            amounts = sorted({abs(delta)//width for delta in displacements if delta and delta % width == 0})
            # An 8-byte slot can move by one aligned slot when a 4-byte
            # element crosses its boundary. Try the exact delta first.
            if width == 4 and 2 in amounts and 1 not in amounts:
                amounts.append(1)
            for amount in amounts[:2]:
                if not 0 < amount < integer(spare['count']):
                    continue
                result.append((STACK, edit(source, [
                    (*spare.span('count'), str(integer(spare['count'])-amount)),
                    (*used.span('count'), str(integer(used['count'])+amount)),
                ])))
                if len(result) == 4:
                    return result
    return result
