"""Expression candidates tied to an observed MIPS instruction difference."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view

REG = r'\$\w+'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
MEMORY = re.compile(rf'(lhu|lw)\s+({REG}),\s*({NUM})?\(({REG})\)')
ADDIU = re.compile(rf'addiu\s+({REG}),\s*({REG}),\s*(-?{NUM})')
SHIFT2 = re.compile(rf'sll\s+({REG}),\s*({REG}),\s*(?:2|0x2)')
ADD = re.compile(rf'addu\s+({REG}),\s*({REG}),\s*({REG})')


def sign_test(source, part, rows, changed):
    if (changed != [len(rows)-1] or len(rows) < 2 or rows[-2][1] != 'jr $ra'
            or rows[-2][2] != 'jr $ra' or rows[-1][1] != 'slti $v0, $v0, 0'
            or not re.fullmatch(r'srl \$v0, \$v0, (?:31|0x1f)',rows[-1][2])):
        return None
    pattern = re.compile(rf'\breturn\s*\(\s*(?P<bit>(?P<value>{IDENT})'
                         r'\s*&\s*0[xX]80000000[uU])\s*\)\s*!=\s*0\s*;')
    sites = list(pattern.finditer(part.clean,part.opening+1,part.end))
    if len(sites) != 1:
        return None
    hit = sites[0]
    if not re.search(rf'\bs32\s+{hit["value"]}\s*(?=[;=])',part.body):
        return None
    return edit(source,[(*hit.span('bit'),f'{hit["value"]} >> 31')])


def field_after_advance(source, header, part, rows, changed):
    if len(changed) != 1 or changed[0]+1 >= len(rows):
        return None
    index = changed[0]
    want,have = (MEMORY.fullmatch(text) for text in rows[index][1:])
    step = ADDIU.fullmatch(rows[index+1][1])
    if (not want or not have or not step or rows[index+1][0] != ' '
            or want[1] != 'lhu' or (want[1],want[2],want[4]) != (have[1],have[2],have[4])
            or step[2] != want[4]):
        return None
    advance = int(step[3],0)
    old = integer(have[3] or '0')-advance
    new = integer(want[3] or '0')-advance
    if advance <= 0 or min(old,new) < 0 or old == new:
        return None
    pattern = re.compile(rf'\b(?P<base>{IDENT})\s*\+=\s*(?P<count>{NUM})\s*;\s*'
                         rf'if\s*\(\s*\(\s*\(\s*(?P<record>{IDENT})\s*\*\s*\)\s*(?P=base)\s*\)'
                         rf'\s*->\s*(?P<member>field_(?P<offset>[0-9a-fA-F]+))\s*!=\s*0\s*\)\s*goto\s+{IDENT}\s*;')
    context = _blank(header)+'\n'+part.clean[:part.opening]
    for hit in pattern.finditer(part.clean,part.opening+1,part.end):
        if integer(hit['count'])*2 != advance or int(hit['offset'],16) != old:
            continue
        if not re.search(rf'\bextern\s+u16\s*\*\s*{hit["base"]}\s*;',context):
            continue
        records = re.findall(rf'\btypedef\s+struct\s*{{([^{{}}]*)}}\s*{hit["record"]}\s*;',context)
        if len(records) != 1:
            continue
        words = {int(offset,16):f'field_{offset}' for offset in
                 re.findall(r'\bu16\s+field_([0-9a-fA-F]+)\s*;',records[0])}
        if old in words and new in words:
            return edit(source,[(*hit.span('member'),words[new])])
    return None


def multiply_window(rows):
    for i in range(len(rows)-5):
        window = rows[i:i+6]
        target = [match.fullmatch(row[1]) for match,row in zip((SHIFT2,ADD,MEMORY,SHIFT2,ADDIU,ADD),window)]
        prior = [match.fullmatch(row[2]) for match,row in zip((SHIFT2,ADD,MEMORY,SHIFT2,ADDIU,ADD),window)]
        if not all(target+prior) or window[0][0] != ' ' or any(row[0] != 'r' for row in window[1:]):
            continue
        shift,add,load,scale,bias,final = target
        if (load[1]!='lw' or (load[1],load[3],load[4]) != (prior[2][1],prior[2][3],prior[2][4])
                or shift.groups() != prior[0].groups() or add.groups() != (shift[1],shift[1],shift[2])
                or prior[1].groups() != (shift[2],shift[1],shift[2])
                or scale.groups() != (shift[1],shift[1]) or prior[3].groups() != (shift[2],shift[2])
                or bias.groups() != (shift[1],shift[1],prior[4][3])
                or final.groups() != (load[2],load[2],shift[1])):
            continue
        literal = int(bias[3],0)
        if -32768 <= literal < 0:
            yield -literal


def bounded_scale(source, part, rows):
    biases = set(multiply_window(rows))
    if not biases:
        return None
    pattern = re.compile(rf'\bs32\s+(?P<acc>{IDENT})\s*=\s*(?P<expr>(?P<value>{IDENT})\s*\*\s*5)\s*;'
                         rf'\s*s32\s+{IDENT}\s*=\s*M2C_FIELD\([^;]+\)\s*;\s*'
                         rf'(?P=acc)\s*=\s*(?P<scale>\(\s*(?P=acc)\s*<<\s*2\s*\))\s*-\s*(?P<bias>{NUM})\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end):
        value = hit['value']
        writes = re.findall(rf'\b{value}\s*(?:=(?!=)\s*([^;]+)|[+\-*/%&|^]=|\+\+|--)',part.body)
        if (integer(hit['bias']) in biases and len(writes)==1
                and len(re.findall(rf'\bs32\s+{value}\s*;',part.body)) == 1
                and re.fullmatch(rf'{IDENT}\s*&\s*(?:0[xX][fF]{{4}}|65535)',writes[0].strip())
                and not re.search(rf'&\s*{value}\b',part.body)):
            return edit(source,[(*hit.span('expr'),f'(({value} << 2) + {value}) << 2'),
                                (*hit.span('scale'),hit['acc'])])
    return None


def staged_negation(source, part, rows, changed):
    if len(changed) != 2:
        return None
    i,j = changed
    old,new = rows[i],rows[j]
    neg = re.fullmatch(rf'neg\.s\s+({REG}),\s*{REG}',new[1])
    if j-i != 4 or j+1 >= len(rows) or not neg or old[1] or old[2] != new[1] or new[2]:
        return None
    cvt = re.fullmatch(rf'cvt\.s\.w\s+({REG}),\s*\1',rows[j-1][1])
    if (not cvt or rows[j-1][0] != ' ' or rows[j+1][0] != ' '
            or rows[j+1][1] != f'c.lt.s {cvt[1]}, {neg[1]}'):
        return None
    pattern = re.compile(rf'\b(?P<negative>{IDENT})\s*=\s*-\s*(?P<arg>{IDENT})\s*;\s*'
                         rf'if\s*\(\s*\(\s*(?P<value>{IDENT})\s*=\s*(?P<convert>\(\s*f32\s*\)\s*'
                         rf'\(\s*(?P<input>{IDENT})\s*>>\s*1\s*\))\s*\)\s*<\s*(?P=negative)\s*\)')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end):
        names = [hit[key] for key in ('negative','arg','value','input')]
        if (len(set(names)) != 4
                or re.search(r'\bvolatile\s+(?:f32|s32)\s+(?:'+'|'.join(names)+r')\b',part.clean)
                or not re.search(rf'\bs32\s+{hit["input"]}\s*;',part.body)
                or not all(re.search(rf'\bf32\s+{name}\s*(?=[,);])',part.clean[:hit.start()])
                           for name in names[:3])):
            continue
        return edit(source,[(*hit.span(),f'do {{ {hit["value"]} = {hit["convert"]}; }} while (0);\n'
                                         f'{hit["negative"]} = -{hit["arg"]};\n'
                                         f'if ({hit["value"]} < {hit["negative"]})')])
    return None


def _byte_lane_merge(part, header, rows, changed):
    """Keep the loaded byte live through the high-lane OR measured before a packed store."""
    if len(changed) != 1:
        return None
    row = changed[0]
    if rows[row][0] != 'r' or row < 5 or row + 2 >= len(rows):
        return None
    op = re.fullmatch(rf'or ({REG}), \1, ({REG})', rows[row][1])
    if not op:
        return None
    byte, flag = (re.escape(value) for value in op.groups())
    have = re.fullmatch(rf'or ({REG}), \1, {flag}', rows[row][2])
    if not have or have[1] == op[1]:
        return None
    result = re.escape(have[1])
    window = [target for _, target, _ in rows[row-5:row+3]]
    if not (re.match(rf'lbu {byte}, ', window[0])
            and window[1] == f'nor {have[1]}, $zero, {op[1]}'
            and re.fullmatch(rf'andi {result}, {result}, (?:255|0xff)', window[2])
            and re.fullmatch(rf'sll {result}, {result}, (?:16|0x10)', window[3])
            and re.fullmatch(rf'lui {flag}, (?:65280|0xff00)', window[4])
            and window[6] == f'or {have[1]}, {have[1]}, {op[1]}'
            and (store := re.fullmatch(rf'sw {result}, ({NUM})\({REG}\)', window[7]))):
        return None

    fresh = '__repair_inverted_byte'
    if fresh in part.source + header or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return None
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]*)(?P<dst>M2C_FIELD\({IDENT}, s32 \*, (?P<offset>{NUM})\))'
        rf' = \(s32\) \(\(\(~(?P<byte>{IDENT}) & (?:0x[fF]{{2}}|255)\) << (?:0x10|16)\)'
        r' \| \((?P=byte) \| 0[xX][fF]{2}000000\)\);'
    )
    sites = list(pattern.finditer(part.clean, part.opening+1, part.end))
    if len(sites) != 1 or integer(sites[0]['offset']) != integer(store[1]):
        return None
    hit = sites[0]
    name, indent = hit['byte'], hit['indent']
    start = part.opening + 1
    before = part.clean[start:hit.start()]
    declaration = re.search(rf'(?m)^[ \t]*(?P<type>u8)\s+{name};', before)
    initial = re.search(rf'(?m)^[ \t]*{name}\s*=\s*(?P<expr>\*\([^;\n]+\));', before)
    if (not declaration or not initial or declaration.start() >= initial.start()
            or len(re.findall(rf'\b{name}\b', part.body)) != 4):
        return None
    a, b = initial.span('expr')
    da, db = declaration.span('type')
    local_end = start + declaration.end()
    original = part.source[start+a:start+b]
    replacement = (f'{indent}{fresh} = (~{name} & 0xFF) << 16;\n'
                   f'{indent}{name} |= 0xFF000000;\n'
                   f'{indent}{hit["dst"]} = {fresh} | {name};')
    return edit(part.source, [(start+da, start+db, 'u32'),
                              (local_end, local_end, f'\n{indent}u32 {fresh};'),
                              (start+a, start+b, f'(u8) {original}'),
                              (*hit.span(), replacement)])


def variants(source, name, header, rows):
    changed = [index for index,(marker,_,_) in enumerate(rows) if marker != ' ']
    if not 1 <= len(changed) <= 6 or not (part := view(source,name)):
        return []
    if candidate := sign_test(source,part,rows,changed):
        return [('measured_sign_test',candidate)]
    if candidate := field_after_advance(source,header,part,rows,changed):
        return [('measured_advanced_field',candidate)]
    if candidate := bounded_scale(source,part,rows):
        return [('measured_scaled_expression',candidate)]
    if candidate := staged_negation(source,part,rows,changed):
        return [('measured_staged_negation',candidate)]
    if candidate := _byte_lane_merge(part,header,rows,changed):
        return [('measured_byte_lane_merge',candidate)]
    return []
