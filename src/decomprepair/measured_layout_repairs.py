"""Small layout candidates with matching stack or word-store evidence."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, integer, split_args, view
from .pattern_repairs import close

NAME = r'D_[0-9A-Fa-f]{8}'
REG = r'\$\w+'
HIGH = re.compile(rf'lui\s+({REG}),\s*%hi\(({NAME})\)')
BASE = re.compile(rf'addiu\s+({REG}),\s*\1,\s*%lo\(({NAME})\)')
LOAD = re.compile(rf'lw\s+({REG}),\s*%lo\(({NAME})\)\(({REG})\)')
STORE = re.compile(rf'sw\s+({REG}),\s*(0x[0-9a-fA-F]+|\d+)?\(({REG})\)')
DECL = re.compile(r'\b(?:char|s8|u8|unsigned\s+char)\s+(?P<name>(?:frame|padding?|pad)\w*)\s*'
                  r'\[\s*(?P<count>0x[0-9a-fA-F]+|\d+)\s*\]\s*;')


def unused_frame_array(source, name, rows, report):
    """A known unused array can account for the exact excess frame size."""
    delta = report.get('frame_delta')
    if (delta not in (-4,-8,-16,-24,-32) or report.get('saved_deltas') != [delta]
            or report.get('local_deltas') not in ([],[0])
            or any(mark not in (' ','s') for mark,_,_ in rows)):
        return []
    part = view(source,name)
    if not part:
        return []
    for hit in DECL.finditer(part.clean,part.opening+1,part.end):
        prefix = part.clean[part.opening+1:hit.start()]
        if (integer(hit['count']) != -delta or prefix.count('{') != prefix.count('}')
                or (prefix.rstrip() and prefix.rstrip()[-1] != ';')
                or len(re.findall(rf'\b{hit["name"]}\b',part.body)) != 1
                or re.search(r'/[*/]',source[slice(*hit.span())])):
            continue
        replacement = '\n' * source[slice(*hit.span())].count('\n')
        return [('measured_unused_frame_array',edit(source,[(*hit.span(),replacement)]))]
    candidate = _trim_generated_frame_view(part, -delta)
    return [('measured_trim_frame_view', candidate)] if candidate else []


def _trim_generated_frame_view(part, excess):
    """Reduce the generated backing extent without moving any typed views."""
    if re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return None
    overlay = re.match(
        r'\s*union\s*\{\s*unsigned char bytes\[(?P<count>\d+)\];(?P<views>.*?)'
        r'\} m2c_initial_frame;', part.body, re.S,
    )
    if not overlay:
        return None
    member = re.compile(
        r'struct \{ (?:unsigned char pad\[(?P<offset>\d+)\]; )?'
        r'(?P<kind>M2C_UNK|[su](?:8|16|32)|f32) value; \} (?P<name>view_sp[0-9A-Fa-f]+);'
    )
    remaining = overlay['views']
    fields = {}
    while remaining := remaining.lstrip():
        hit = member.match(remaining)
        if not hit or hit['name'] in fields:
            return None
        width = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2}.get(hit['kind'], 4)
        offset = int(hit['offset'] or 0)
        if offset % width:
            return None
        fields[hit['name']] = offset + width
        remaining = remaining[hit.end():]
    count = int(overlay['count']) - excess
    if not fields or count < max(fields.values()):
        return None
    tail = part.body[overlay.end():]
    covered = re.sub(r'\bm2c_initial_frame\.(?:' + '|'.join(fields) + r')\.value\b', '', tail)
    if covered == tail or re.search(r'\bm2c_initial_frame\b', covered):
        return None
    start, end = (part.opening + 1 + at for at in overlay.span('count'))
    return edit(part.source, [(start, end, str(count))])


def scoped_frame_array(source, name, rows, report):
    """Reserve only the observed frame gap, after a call using an unchanged local slot."""
    gap = report.get('frame_only_gap')
    if gap not in (8, 16, 24, 32):
        return None
    part = view(source, name)
    fresh = '__repair_stack_padding'
    if not part or fresh in part.clean or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return None

    body = part.clean[part.opening + 1:part.clean.rfind('}', part.opening, part.end)]
    # A separate scope lets KMC retain the earlier object's offset.
    calls = re.finditer(rf'(?:^|(?<=[;}}]))\s*(?P<callee>{IDENT})\s*\(', body)
    for call in calls:
        start = call.end() - 1
        end = close(body, start)
        if not end or body[end:].strip() != ';':
            continue
        prefix = body[:call.start()]
        if prefix.count('{') != prefix.count('}'):
            continue
        callee = f'jal {call["callee"]}'
        matches = [i for i, row in enumerate(rows) if tuple(row) == (' ', callee, callee)]
        if len(matches) != 1:
            return None
        index = matches[0]
        incoming = [left for marker, left, right in rows[max(0, index - 8):index]
                    if marker == ' ' and left == right]
        offsets = {slot['target'] for slot in report['local_operands'] if not slot['delta']}
        arguments = body[start + 1:end - 1]
        for position, (begin, finish) in enumerate(split_args(arguments)[:4]):
            local = re.fullmatch(rf'\s*&\s*({IDENT})\s*', arguments[begin:finish])
            if not local or not re.search(rf'\b{INTEGER}\s+{local[1]}\s*;', prefix):
                continue
            assignment = next((line for line in reversed(incoming) if re.match(rf'\w+ \$a{position},', line)), '')
            setup = re.fullmatch(rf'addiu \$a{position}, \$sp, ({NUMBER})', assignment)
            if setup and integer(setup[1]) in offsets:
                insert = part.clean.index(';', part.opening + 1 + end) + 1
                addition = ('\n    {\n        /* Inferred frame reservation; original purpose unknown. */'
                            f'\n        char {fresh}[{gap}];\n    }}')
                return edit(source, [(insert, insert, addition)])
        return None
    return None


def copy_witness(rows):
    """The target loads each named word and stores them through one resolved destination."""
    target = [(mark,line) for mark,line,_ in rows if line]
    for i in range(1,len(target)-1):
        marker,line = target[i]
        next_marker,next_line = target[i+1]
        a,b = STORE.fullmatch(line),STORE.fullmatch(next_line)
        if not a or not b or marker == next_marker == ' ' or a[3] != b[3]:
            continue
        if integer(a[2] or '0') != 0 or integer(b[2] or '0') != 4 or a[1] == b[1]:
            continue
        window = [text for _,text in target[max(0,i-6):i]]
        if len(window) != 6:
            continue
        dest_hi,base,first_hi,first,second_hi,second = [
            pattern.fullmatch(text) for pattern,text in zip((HIGH,BASE,HIGH,LOAD,HIGH,LOAD),window)
        ]
        if (not all((dest_hi,base,first_hi,first,second_hi,second)) or dest_hi.groups() != base.groups()
                or base[1] != a[3] or first_hi.groups() != (first[3],first[2])
                or second_hi.groups() != (second[3],second[2]) or (first[1],second[1]) != (a[1],b[1])
                or base[1] in (first[1],first[3],second[1],second[3]) or first[1] == second[3]):
            continue
        yield base[2],first[2],second[2]


def paired_word_copy(source, name, header, rows, symbols, flags=()):
    if symbols is None or '-fstrict-aliasing' in flags:
        return []
    part = view(source,name)
    if not part or '__repair_word_pair' in part.clean:
        return []
    context = _blank(header)+'\n'+part.clean[:part.opening]
    for dest,first,second in copy_witness(rows):
        to,lo,hi = (symbols.by_name.get(sym) for sym in (dest,first,second))
        if (not all((to,lo,hi)) or to.size < 8 or (to.address|lo.address) & 3
                or hi.address != lo.address+4 or abs(to.address-lo.address)<8
                or to.kind not in ('data','bss') or any(s.kind not in ('data','bss') for s in (lo,hi))):
            continue
        declared = re.findall(r'\bextern\s+s32\s+([^;{}]+);', context)
        names = {sym.strip() for group in declared for sym in group.split(',')}
        if not {first,second} <= names:
            continue
        forms = (
            rf'M2C_FIELD\s*\(\s*&\s*{dest}\s*,\s*s32\s*\*\s*,\s*0\s*\)\s*=\s*{first}\s*;\s*'
            rf'M2C_FIELD\s*\(\s*&\s*{dest}\s*,\s*s32\s*\*\s*,\s*4\s*\)\s*=\s*{second}\s*;',
            rf'{{\s*s32\s*\*\s*(?P<p>{IDENT})\s*=\s*\(\s*s32\s*\*\s*\)\s*&\s*{dest}\s*;\s*'
            rf'(?P=p)\s*\[\s*0\s*\]\s*=\s*{first}\s*;\s*(?P=p)\s*\[\s*1\s*\]\s*=\s*{second}\s*;\s*}}',
        )
        for pattern in forms:
            hits = list(re.compile(pattern).finditer(part.clean,part.opening+1,part.end))
            if len(hits) != 1:
                continue
            hit = hits[0]
            original = source[slice(*hit.span())]
            if re.search(r'/[*/]', original):
                continue
            replacement = (f'{{ typedef struct {{ s32 words[2]; }} __repair_word_pair; '
                           f'*(__repair_word_pair *)&{dest} = *(__repair_word_pair *)&{first}; }}')
            replacement += '\n' * original.count('\n')
            return [('measured_paired_word_copy',edit(source,[(*hit.span(),replacement)]))]
    return []
