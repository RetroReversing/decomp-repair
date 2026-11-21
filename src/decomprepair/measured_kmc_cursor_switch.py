"""Recover KMC drafts where the diff exposes a cursor step or split value lifetime."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_SWAP = re.compile(
    r'addiu \$sp, \$sp, -24\nsw \$ra, 16\(\$sp\)\nlw \$v1, (?P<pending>\d+)\(\$a0\)\n'
    r'beqz \$v1, 32\nmove \$a1, \$a0\nlw \$v0, (?P<current>\d+)\(\$a0\)\n'
    r'sw \$v1, (?P=current)\(\$a0\)\nsw \$v0, (?P=pending)\(\$a0\)\n'
    rf'jal (?P<call>{IDENT})\nlw \$a0, (?P=current)\(\$a1\)\nlw \$ra, 16\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 24'
)
_SWAP_SOURCE = _shape('''
    s32 @saved;
    s32 @next;
    @next = M2C_FIELD(@obj, s32 *, @pending);
    if (@next != 0) {
        @saved = M2C_FIELD(@obj, s32 *, @current);
        M2C_FIELD(@obj, s32 *, @current) = @next;
        M2C_FIELD(@obj, s32 *, @pending) = @saved;
    }
    @call(M2C_FIELD(@obj, s32 *, @current), @obj);
''', numbers=('pending', 'current'))

_CURSOR = re.compile(
    r'addiu \$sp, \$sp, -32\nsw \$s1, 20\(\$sp\)\nmove \$s1, \$a0\n'
    r'sw \$s0, 16\(\$sp\)\nmove \$s0, \$a1\nsw \$ra, 24\(\$sp\)\nlbu \$a0, \(\$s0\)\n'
    rf'jal (?P<call>{IDENT})\naddiu \$s0, \$s0, 1\nmove \$v1, \$v0\nsb \$v1, (?P<field>\d+)\(\$s1\)\n'
    r'lbu \$a0, \(\$s0\)\naddiu \$v0, \$s0, 1\naddu \$v1, \$v1, \$a0\nsb \$v1, (?P=field)\(\$s1\)\n'
    r'lw \$ra, 24\(\$sp\)\nlw \$s1, 20\(\$sp\)\nlw \$s0, 16\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 32'
)
_CURSOR_SOURCE = _shape('''
    s8 @value;
    @value = @call(M2C_FIELD(@input, u8 *, 0));
    M2C_FIELD(@obj, s8 *, @field) = @value;
    M2C_FIELD(@obj, s8 *, @field) = (s8) (@value + M2C_FIELD(@input, u8 *, 1));
    return @input + 1 + 1;
''', numbers=('field',))

_SWITCH = re.compile(
    r'addiu \$v1, \$zero, 1\naddiu \$v0, \$zero, 1\nbeq \$a2, \$v0, 68\nsllv \$v1, \$v1, \$a1\n'
    r'slti \$v0, \$a2, 2\nbeql \$v0, \$zero, 44\naddiu \$v0, \$zero, 2\nbeql \$a2, \$zero, 60\n'
    rf'nor \$v0, \$zero, \$v1\nj (?P<name>{IDENT})\+72\nnop\nbeql \$a2, \$v0, 72\n'
    r'xor \$a0, \$a0, \$v1\nj (?P=name)\+72\nnop\nj (?P=name)\+72\n'
    r'and \$a0, \$a0, \$v0\nor \$a0, \$a0, \$v1\njr \$ra\nmove \$v0, \$a0'
)
_SWITCH_SOURCE = _shape('''
    s32 @mask;
    s32 @value;
    @value = @input;
    @mask = 1 << @bit;
    switch (@mode) {
    case 0: @value &= ~@mask; break;
    case 2: @value ^= @mask; break;
    case 1: @value |= @mask; break;
    }
    return @value;
''')

_ELSE_CALL = re.compile(
    rf'lui \$v0, %hi\((?P<flag>{IDENT})\)\nlbu \$v0, %lo\((?P=flag)\)\(\$v0\)\n'
    r'bnez \$v0, 108\naddiu \$a0, \$zero, 1\n'
    rf'jal (?P<prepare>{IDENT})\naddiu \$a1, \$s0, (?P<first>\d+)\n'
    rf'addiu \$a0, \$s0, (?P<second>\d+)\njal (?P<other>{IDENT})\nmove \$s0, \$v0\n'
    rf'lui \$a1, %hi\((?P<table>{IDENT})\)\naddiu \$a1, \$a1, %lo\((?P=table)\)\n'
    rf'jal (?P<finish>{IDENT})\nmove \$a0, \$s0\nj (?P<name>{IDENT})\+116\nnop\n'
    rf'jal (?P<call>{IDENT})\nnop\nlw \$ra, 20\(\$sp\)\nlw \$s0, 16\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 24$'
)
_ELSE_SOURCE = re.compile(
    rf'if \((?P<flag>{IDENT}) == 0\) \{{\s*(?P<handle>{IDENT}) = (?P<prepare>{IDENT})\(1, (?P<input>{IDENT}) \+ (?P<first>{NUMBER})\);'
    rf'\s*(?P<other>{IDENT})\((?P=input) \+ (?P<second>{NUMBER})\);\s*(?P<finish>{IDENT})\((?P=handle), &(?P<table>{IDENT})\);'
    rf'(?P<tail>\s*return;\s*\}}\s*(?P<call>{IDENT})\(1\);)\s*$'
)


_EARLY_CALL = re.compile(
    rf'beqz \$v0, (?P<next>\d+)\naddiu \$a0, \$zero, (?P<code>\d+)\n'
    rf'lui \$v0, %hi\((?P<global>{IDENT})\)\nlw \$v0, %lo\((?P=global)\)\(\$v0\)\n'
    r'lhu \$v1, (?P<field>\d+)\(\$v0\)\naddiu \$v0, \$zero, (?P<guard>\d+)\n'
    r'beq \$v1, \$v0, (?P=next)\naddiu \$a0, \$zero, (?P=code)\n'
    rf'jal (?P<call>{IDENT})\nnop\nj (?P<name>{IDENT})\+\d+\nnop'
)
_EARLY_SOURCE = re.compile(
    rf'^\s*(?:(?:s32 |void \*){IDENT};\s*)*if \(\(\({IDENT} != 0\) \|\| \({IDENT} != 0\) \|\| \({IDENT} != 0\)\) && '
    rf'\(M2C_FIELD\(M2C_FIELD\(&{IDENT}, void \*\*, {NUMBER}\), u16 \*, (?P<field>{NUMBER})\) '
    rf'!= (?P<guard>{NUMBER})\)\) \{{\s*(?P<call>{IDENT})\((?P<arg>{NUMBER})\);\s*return;\s*\}}'
)


def _separate_label_loop_cursor(source, name, header, rows):
    """Split a cursor freshly initialized before each of two label loops."""
    changes = [(want, have) for mark, want, have in rows if mark != ' ']
    if not 4 <= len(changes) <= 16 or any(mark not in (' ', 'r') for mark, _, _ in rows):
        return None
    incoming = re.compile(r'move (\$\w+), (\$\w+)')
    moved = [(a[1], b[1]) for want, have in changes
             if (a := incoming.fullmatch(want)) and (b := incoming.fullmatch(have))
             and a[2] == b[2] and a[2] != '$zero' and a[1] != b[1]]
    if len(moved) != 1 or not (part := view(source, name)):
        return None
    wanted, staged = map(re.escape, moved[0])
    stride = [a[1] for left, right in changes
              if (a := re.fullmatch(rf'addiu {wanted}, {wanted}, ({NUMBER})', left))
              and re.fullmatch(rf'addiu {staged}, {staged}, {re.escape(a[1])}', right)]
    if len(stride) != 1:
        return None
    local = '__repair_first_loop_cursor'
    if local in source + header:
        return None
    start = re.compile(
        rf'(?m)^(?P<indent>[ \t]+)(?P<cursor>{IDENT})\s*=\s*(?P<base>{IDENT});\n'
        rf'[ \t]*(?P<label>{IDENT}):')
    possible = []
    for first in start.finditer(part.clean, part.opening + 1, part.end):
        cursor, label = first['cursor'], first['label']
        later = next((hit for hit in start.finditer(part.clean, first.end(), part.end)
                      if hit['cursor'] == cursor and hit['base'] == first['base']), None)
        if not later:
            continue
        goto = list(re.finditer(rf'\bgoto\s+{label}\s*;', part.body))
        if len(goto) != 1:
            continue
        tail = part.opening + 1 + goto[0].end()
        if not first.end() < tail < later.start() or re.search(rf'\b{cursor}\b', part.clean[tail:later.start()]):
            continue
        declarations = re.compile(rf'(?m)^[ \t]*void\s*\*\s*{cursor};[ \t]*\n')
        bind = list(declarations.finditer(part.clean, part.opening + 1, first.start()))
        if len(bind) != 1:
            continue
        loop = part.clean[first.end():tail]
        steps = re.findall(rf'\b{cursor}\s*\+=\s*({NUMBER});', loop)
        if len(steps) != 1 or integer(steps[0]) != integer(stride[0]) or re.search(rf'&\s*{cursor}\b', loop):
            continue
        if re.search(rf'\bgoto\s+(?!{label}\b){IDENT}|(?m:^[ \t]*{IDENT}:)', loop):
            continue
        read = re.compile(rf'(?<![.>\w]){cursor}\b')
        positions = [(*hit.span(), local) for hit in read.finditer(part.clean, first.start(), tail)]
        possible.append(edit(source, [*positions, (bind[0].end(), bind[0].end(), f'{first["indent"]}void *{local};\n')]))
    return possible[0] if len(possible) == 1 else None


def _cursor_advance_order(source, name, rows):
    """Swap two independent pointer advances around an unchanged step."""
    step = re.compile(rf'addiu (?P<reg>\$\w+), (?P=reg), (?P<stride>{NUMBER})')
    strides = set()
    for first, middle, last in zip(rows, rows[1:], rows[2:]):
        if (first[0] != 'r' or last[0] != 'r' or middle[0] != ' '
                or first[1:] != last[1:][::-1] or middle[1] != middle[2]):
            continue
        a, b, c = map(step.fullmatch, (first[1], middle[1], last[1]))
        if a and b and c and len({a['reg'], b['reg'], c['reg']}) == 3:
            amounts = {integer(hit['stride']) for hit in (a, b, c)}
            if len(amounts) == 1:
                strides.update(amounts)
    if len(strides) != 1 or not (part := view(source, name)):
        return None
    pointer = (rf'(?P<{{label}}>{IDENT}) = \(s32 \*\) '
               rf'\(\(\(u8 \*\) (?P={{label}})\) \+ (?P<{{label}}_step>{NUMBER})\);')
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]+){pointer.format(label="first")}\n'
        rf'(?P=indent)(?P<scalar>{IDENT}) \+= (?P<scalar_step>{NUMBER});\n'
        rf'(?P=indent){pointer.format(label="last")}')
    hits = [hit for hit in pattern.finditer(part.clean, part.opening + 1, part.end)
            if {integer(hit[key]) for key in ('first_step', 'scalar_step', 'last_step')} == strides]
    if len(hits) != 1:
        return None
    hit = hits[0]
    names = [hit[key] for key in ('first', 'scalar', 'last')]
    if (len(set(names)) != 3 or re.search(r'/[*/]', source[hit.start():hit.end()])
            or any(not re.search(rf'(?m)^[ \t]*s32 \*{var};', part.body) for var in names[::2])
            or not re.search(rf'(?m)^[ \t]*(?:u8 \*|[su]32 ){names[1]};', part.body)):
        return None
    offset = hit.start('first')
    last = hit.start('last')
    first_end = source.index('\n', offset)
    return edit(source, [(offset, first_end, source[last:hit.end()]), (last, hit.end(), source[offset:first_end])])


def variants(source, name, header, rows):
    if fixed := _cursor_advance_order(source, name, rows):
        return [('measured_cursor_advance_order', fixed)]
    if fixed := _separate_label_loop_cursor(source, name, header, rows):
        return [('measured_label_loop_cursor', fixed)]
    if len(rows) not in (14, 20, 21, 33):
        return _early_call(source, name, header, rows)
    changes = [(left, right) for tag, left, right in rows if tag != ' ']
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    if (match := _SWAP.fullmatch(target)) and len(changes) == 7 and ('', 'move $a1, $a0') in changes:
        family, draft, rewrite = 'measured_swap_then_field_call', _SWAP_SOURCE, _swap
    elif (match := _CURSOR.fullmatch(target)) and len(changes) == 5 and ('addiu $s0, $s0, 1', '') in changes:
        family, draft, rewrite = 'measured_two_byte_call_cursor', _CURSOR_SOURCE, _cursor
    elif ((match := _SWITCH.fullmatch(target)) and match['name'] == name and len(changes) == 9
          and ('addiu $v1, $zero, 1', '') in changes and ('sllv $v1, $v1, $a1', 'sllv $v1, $v0, $a1') in changes):
        family, draft, rewrite = 'measured_switch_mask_initializer', _SWITCH_SOURCE, _switch
    elif (len(changes) == 1 and changes[0] == ('nop', 'addiu $a0, $zero, 1')
          and (match := _ELSE_CALL.search(target)) and match['name'] == name):
        family, draft, rewrite = 'measured_guarded_no_argument_call', _ELSE_SOURCE, _else_call
    else:
        return _early_call(source, name, header, rows)
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    body = draft.search(part.body) if draft is _ELSE_SOURCE else draft.fullmatch(' '.join(part.body.split()))
    fixed = rewrite(part, name, header, match, body) if body else None
    return [(family, fixed)] if fixed else []


def _prototype(part, header, callee, parameter_types, result_type):
    declaration = re.search(
        rf'(?m)^[ \t]*(?P<ret>{result_type})\s+{callee}\((?P<args>{parameter_types})\);',
        part.clean[:part.opening],
    )
    if not declaration or len(re.findall(rf'\b{callee}\b', part.clean + _blank(header))) != 2:
        return None
    return declaration


def _swap(part, name, header, target, body):
    base, call = '__repair_swap_base', target['call']
    sig = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*({IDENT})\)\s*$', part.clean[:part.opening])
    if (not sig or sig[1] != body['obj'] or body['call'] != call or call == name or base in part.source + header
            or any(integer(body[key]) != int(target[key]) for key in ('pending', 'current'))):
        return None
    declaration = _prototype(part, header, call, r's32, void \*', 'M2C_UNK|s32|void')
    if not declaration or len({body[key] for key in ('obj', 'saved', 'next')}) != 3:
        return None
    current, pending = (f'M2C_FIELD({base}, s32 *, {body[key]})' for key in ('current', 'pending'))
    next_value, saved = body['next'], body['saved']
    fixed = f'''
    void *{base} = {body['obj']};
    s32 {saved};
    s32 {next_value};

    {next_value} = {pending};
    if ({next_value} != 0) {{
        {saved} = {current};
        {current} = {next_value};
        {pending} = {saved};
    }}
    {call}({current});
'''
    return edit(part.source, [(*declaration.span('args'), 's32'), (part.opening + 1, part.end - 1, fixed)])


def _cursor(part, name, header, target, body):
    obj, cursor, value, call = (body[key] for key in ('obj', 'input', 'value', 'call'))
    signature = re.search(
        rf'\bvoid\s*\*\s*{re.escape(name)}\(void \*({IDENT}),\s*(?P<type>void \*)({IDENT})\)\s*$',
        part.clean[:part.opening],
    )
    if (not signature or (signature[1], signature[3]) != (obj, cursor) or call != target['call']
            or integer(body['field']) != int(target['field']) or len({name, obj, cursor, value, call}) != 5):
        return None
    if re.search(rf'\b{re.escape(name)}\b', part.clean[:signature.start()] + part.clean[part.end:] + _blank(header)):
        return None
    declaration = _prototype(part, header, call, 'u8', 's8')
    if not declaration:
        return None
    field = f'M2C_FIELD({obj}, s8 *, {body["field"]})'
    fixed = f'''
    int {value} = {call}(*{cursor}++);
    {field} = {value};
    {value} += *{cursor};
    {field} = {value};
    return {cursor} + 1;
'''
    return edit(part.source, [
        (*declaration.span('ret'), 'int'), (*declaration.span('args'), 'int'), (*signature.span('type'), 'u8 *'),
        (part.opening + 1, part.end - 1, fixed),
    ])


def _switch(part, name, _header, _target, body):
    signature = re.search(rf'\bs32\s+{re.escape(name)}\(s32 ({IDENT}), s32 ({IDENT}), s32 ({IDENT})\)\s*$',
                          part.clean[:part.opening])
    mask, value = body['mask'], body['value']
    if (not signature or signature.groups() != tuple(body[key] for key in ('input', 'bit', 'mode'))
            or len(set(body.groupdict().values())) != 5):
        return None
    position = re.search(rf'(?m)^(?P<indent>[ \t]*){value}\s*=', part.body)
    shift = re.search(rf'\b{mask}\s*=\s*(?P<literal>1)\s*<<', part.body)
    if not position or not shift:
        return None
    start = part.opening + 1
    return edit(part.source, [
        (start + position.start(), start + position.start(), f'{position["indent"]}{mask} = 1;\n'),
        (start + shift.start('literal'), start + shift.end('literal'), mask),
    ])

def _else_call(part, _name, header, target, body):
    prefix = part.body[:body.start()]
    if not prefix.rstrip().endswith(';') or prefix.count('{') != prefix.count('}'):
        return None
    if any(body[key] != target[key] for key in ('flag', 'prepare', 'other', 'finish', 'table', 'call')):
        return None
    if any(integer(body[key]) != int(target[key]) for key in ('first', 'second')):
        return None
    callee = target['call']
    declaration = _prototype(part, header, callee, 'M2C_UNK|s32|int', 'M2C_UNK|s32|void')
    if not declaration:
        return None
    start = part.opening + 1
    return edit(part.source, [
        (*declaration.span('args'), 'void'),
        (start + body.start('tail'), start + body.end('tail'), f'\n    }} else {{\n        {callee}();\n    }}'),
    ])

def _early_call(source, name, header, rows):
    if not 30 <= len(rows) <= 160:
        return []
    changes = [normalized_integer_lines((left, right)) for tag, left, right in rows if tag != ' ']
    if len(changes) != 1 or changes[0][0] != 'nop':
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    evidence = _EARLY_CALL.search(target)
    if (not evidence or evidence['name'] != name or evidence['call'] == name
            or changes[0][1] != f'addiu $a0, $zero, {evidence["code"]}'):
        return []
    part = view(source, name)
    draft = _EARLY_SOURCE.match(part.body) if part else None
    if (not draft or draft['call'] != evidence['call']
            or integer(draft['arg']) != int(evidence['code'])
            or any(integer(draft[key]) != int(evidence[key]) for key in ('field', 'guard'))):
        return []
    declaration = _prototype(part, header, evidence['call'], 'M2C_UNK|s32|int', 'M2C_UNK|s32|void')
    if not declaration:
        return []
    start = part.opening + 1
    fixed = edit(source, [(*declaration.span('args'), 'void'),
                          (start + draft.start('arg'), start + draft.end('arg'), '')])
    return [('measured_guard_exit_without_inferred_argument', fixed)]
