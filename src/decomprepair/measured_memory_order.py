"""Memory-order hypotheses supported by the measured MIPS instruction sequence."""

import re

from .integer_repair_support import IDENT, edit, integer, locals_for, view
from .pattern_repairs import close
from .repair_source_view import read

REG = r'\$\w+'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
LOAD = re.compile(rf'lwc1\s+({REG}),\s*({NUM})?\(({REG})\)')
CALL = re.compile(rf'jal\s+({IDENT})')
RESET = re.compile(r'move\s+(\$s[0-7]),\s*\$zero')


def reordered_pair(source, part, rows, changed):
    if len(changed) != 2 or changed[1] != changed[0]+1:
        return None
    first,second = (rows[i] for i in changed)
    if (first[1],second[1]) != (second[2],first[2]):
        return None
    a,b = LOAD.fullmatch(first[1]),LOAD.fullmatch(second[1])
    if not a or not b or a[3] != b[3] or a[1] == b[1] or a[2] == b[2]:
        return None
    assignment = (rf'(?P<{{tag}}>{IDENT})\s*=\s*M2C_FIELD\s*\(\s*(?P<base{{tag}}>{IDENT})\s*,\s*f32\s*\*\s*,\s*'
                  rf'(?P<off{{tag}}>{NUM})\s*\)')
    pair = re.compile(r'(?:&&|\|\||[;{])\s*\(\s*(?P<first>'+assignment.format(tag='x')+r')\s*,\s*'
                      +'(?P<second>'+assignment.format(tag='y')+r')(?=\s*,)')
    floats = {name.strip() for group in re.findall(r'(?<=[;{])\s*f32\s+([^;{}]+);',part.clean)
              for name in group.split(',') if re.fullmatch(IDENT,name.strip())}
    candidates = []
    for m in pair.finditer(part.clean,part.opening+1,part.end):
        if ({m['x'],m['y']} - floats or m['x']==m['y'] or m['basex']!=m['basey']
                or m['basex'] in (m['x'],m['y'])
                or (integer(m['offx']),integer(m['offy']))!=(integer(b[2] or '0'),integer(a[2] or '0'))):
            continue
        if any(re.search(rf'&\s*{m[k]}\b',part.body) for k in ('x','y')):
            continue
        if re.search(r'/[*/]', source[m.start('first'):m.end('second')]):
            continue
        candidates.append(edit(source, [(*m.span('first'), source[slice(*m.span('second'))]),
                                        (*m.span('second'), source[slice(*m.span('first'))])]))
    return candidates[0] if len(candidates) == 1 else None


def reset_call(rows, changed):
    if len(changed) != 4 or changed[-1]-changed[0] != 4:
        return None
    window = rows[changed[0]:changed[-1]+1]
    target,prior = ([row[side] for row in window if row[side]] for side in (1,2))
    if len(target) != 3 or len(prior) != 3 or target != prior[::-1]:
        return None
    call,reset = CALL.fullmatch(prior[1]), RESET.fullmatch(prior[0])
    if not call or not reset or re.search(rf'{re.escape(reset[1])}\b',prior[2]):
        return None
    return call[1]


def reset_after_call(source, part, rows, changed):
    callee = reset_call(rows,changed)
    if not callee:
        return None
    pattern = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<reset>(?P<name>{IDENT})\s*=\s*0\s*;)'
                         rf'(?P<gap>\s+)(?P<callee>{callee})\s*\(')
    directives = re.findall(r'(?m)^[ \t]*#\s*define[^\n]*', source)
    macros = set(re.findall(rf'(?m)^\s*#\s*(?:define|undef)\s+({IDENT})',
                            source[part.opening:part.end]))
    external = set(re.findall(IDENT, '\n'.join(directives)))
    for hit in pattern.finditer(part.clean,part.opening+1,part.end):
        name = hit['name']
        prefix = part.clean[part.opening+1:hit.start()].rstrip()
        if (not prefix or prefix[-1] not in ';{}' or name in external or callee in external
                or not any(decl['name'] == name for decl in locals_for(part))):
            continue
        end = close(part.clean,hit.end()-1)
        if not end or part.clean[end:end+1] != ';' or re.search(rf'\b{name}\b',part.clean[hit.end():end]):
            continue
        if macros & set(re.findall(IDENT,part.clean[hit.start('reset'):end+1])):
            continue
        statement = source[hit.start('callee'):end+1]
        gap = source[slice(*hit.span('gap'))]
        if re.search(r'/[*/]|#',gap):
            continue
        return edit(source,[(hit.start('reset'),end+1,statement+gap+source[slice(*hit.span('reset'))])])
    return None


def _earlier_word_load(rows, changed):
    if len(changed) != 2:
        return None
    first, last = changed
    earlier, later = rows[first], rows[last]
    if (earlier[0] != 'o' or later[0] != 'o' or earlier[2] or later[1]
            or earlier[1] != later[2] or last - first != 3):
        return None
    return re.fullmatch(rf'lw ({REG}),\s*({NUM})?\(({REG})\)', earlier[1])


def _flags_before_publish(part, rows, first, last, value, offset, pointer, resolve):
    """Snapshot an object's word before publishing its pointer to a possibly aliased global."""
    if pointer != '$v0' or first < 2 or last + 2 >= len(rows):
        return None
    callee = CALL.fullmatch(rows[first-2][1])
    high = re.fullmatch(rf'lui ({REG}), %hi\(({IDENT})\)', rows[first+1][1])
    if not callee or not high or high[1] in (pointer, value):
        return None
    if rows[first+2][1] != f'sw {pointer}, %lo({high[2]})({high[1]})':
        return None
    imm = re.fullmatch(rf'ori {re.escape(value)}, {re.escape(value)}, ({NUM})', rows[last+1][1])
    low = re.fullmatch(rf'sw {re.escape(value)}, ({NUM})?\(\$v0\)', rows[last+2][1])
    if not imm or not low or integer(low[1] or '0') != offset:
        return None
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]*)(?P<ptr>{IDENT}) = {callee[1]}\([^;\n]+\);\n'
        rf'(?P<publish>[ \t]*M2C_FIELD\(&(?P<global>{IDENT}), void \*\*, (?P<dest>{NUM})\) = (?P=ptr);)\n'
        rf'(?P=indent)(?P<field>M2C_FIELD\((?P=ptr), s32 \*, (?P<offset>{NUM})\))'
        rf' = \(s32\) \((?P=field) \| (?P<mask>{NUM})\);'
    )
    matches = []
    for hit in pattern.finditer(part.clean, part.opening + 1, part.end):
        if integer(hit['offset']) != offset or integer(hit['mask']) != integer(imm[1]):
            continue
        dest = integer(hit['dest'])
        if resolve:
            base, address = resolve(hit['global']), resolve(high[2])
            if base is None or address is None or base + dest != address:
                continue
        elif dest or hit['global'] != high[2]:
            continue
        matches.append(hit)
    if len(matches) != 1:
        return None
    hit = matches[0]
    fresh = '__repair_before_publish'
    if fresh in part.source:
        return None
    indent = hit['indent']
    capture = f'{indent}{fresh} = {hit["field"]};\n'
    assignment = f' = {fresh} | {hit["mask"]};'
    return edit(part.source, [(part.opening+1, part.opening+1, f'\n{indent}s32 {fresh};\n'),
                              (hit.start('publish'), hit.start('publish'), capture),
                              (hit.end('field'), hit.end(), assignment)])


def _link_before_clears(part, name, rows, first, last, value, offset, pointer):
    """Snapshot a list link across the two halfword clears shown by the target."""
    if pointer != '$a1' or first == 0 or last + 3 >= len(rows):
        return None
    clears = [re.fullmatch(rf'{op} \$zero, ({NUM})?\(\$a0\)', rows[row][1])
              for row, op in ((first-1, 'sw'), (first+1, 'sh'), (first+2, 'sh'))]
    store_link = re.fullmatch(rf'sw {re.escape(value)}, ({NUM})?\(\$a0\)', rows[last+1][1])
    set_tail = re.fullmatch(rf'sw \$a0, ({NUM})?\(\$a1\)', rows[last+3][1])
    if not all(clears) or not store_link or not set_tail or rows[last+2][1] != 'jr $ra':
        return None
    if offset != integer(set_tail[1] or '0'):
        return None
    signature = re.search(rf'\bvoid {re.escape(name)}\(void \*(?P<node>{IDENT}), void \*(?P<list>{IDENT})\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None
    node, head = signature['node'], signature['list']
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]*)M2C_FIELD\({node}, s32 \*, (?P<word>{NUM})\) = 0;\n'
        rf'(?P<clears>[ \t]*M2C_FIELD\({node}, s16 \*, (?P<h1>{NUM})\) = 0;\n'
        rf'[ \t]*M2C_FIELD\({node}, s16 \*, (?P<h2>{NUM})\) = 0;\n)'
        rf'[ \t]*M2C_FIELD\({node}, void \*\*, (?P<link>{NUM})\) = '
        rf'(?P<read>\(void \*\) (?P<field>M2C_FIELD\({head}, void \*\*, (?P<old>{NUM})\)));\n'
        rf'[ \t]*M2C_FIELD\({head}, void \*\*, (?P<tail>{NUM})\) = {node};'
    )
    sites = list(pattern.finditer(part.clean, part.opening + 1, part.end))
    if len(sites) != 1:
        return None
    hit = sites[0]
    expected = [integer(clear[1] or '0') for clear in clears] + [integer(store_link[1] or '0'), offset, offset]
    if [integer(hit[key]) for key in ('word', 'h1', 'h2', 'link', 'old', 'tail')] != expected:
        return None
    fresh, indent = '__repair_previous_link', hit['indent']
    if fresh in part.source:
        return None
    return edit(part.source, [(part.opening+1, part.opening+1, f'\n{indent}void *{fresh};\n'),
                              (hit.start('clears'), hit.start('clears'), f'{indent}{fresh} = {hit["field"]};\n'),
                              (*hit.span('read'), fresh)])


def _measured_snapshot(part, name, rows, changed, resolve, header):
    moved = _earlier_word_load(rows, changed)
    if (not moved or 'M2C_FIELD' not in part.body
            or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body)
            or any(token in header for token in ('__repair_before_publish', '__repair_previous_link'))):
        return None
    value, offset, pointer = moved[1], integer(moved[2] or '0'), moved[3]
    args = (*changed, value, offset, pointer)
    return (_flags_before_publish(part, rows, *args, resolve)
            or _link_before_clears(part, name, rows, *args))


def variants(source, name, rows, *, resolve=None, header=''):
    changed = [i for i,(mark,_,_) in enumerate(rows) if mark != ' ']
    if len(changed) not in (2,4):
        return []
    part = view(source,name)
    if part is None:
        if (part := read(source,name)) and (candidate := reset_after_call(source,part,rows,changed)):
            return [('measured_call_reset_order',candidate)]
        return []
    if candidate := _measured_snapshot(part, name, rows, changed, resolve, header):
        return [('measured_earlier_word_load', candidate)]
    if candidate := reordered_pair(source,part,rows,changed):
        return [('measured_comma_load_order',candidate)]
    if candidate := reset_after_call(source,part,rows,changed):
        return [('measured_call_reset_order',candidate)]
    return []
