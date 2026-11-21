"""Measured KMC repairs for input cursors, indexed records, and call arguments."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_CURSOR_TARGET = re.compile(
    r'lbu \$v0, \(\$a1\)\naddiu \$a1, \$a1, 1\nsb \$v0, (?P<first>\d+)\(\$a0\)\n'
    r'lbu \$v0, \(\$a1\)\naddiu \$a1, \$a1, 1\nsb \$v0, (?P<second>\d+)\(\$a0\)\n'
    r'lbu \$v0, \(\$a1\)\n'
    rf'(?:sb \$v0, (?P<byte>\d+)\(\$a0\)\njr \$ra\naddiu \$v0, \$a1, 1|'
    rf'lui \$at, %hi\((?P<scale>{IDENT})\)\nldc1 \$f2, %lo\((?P=scale)\)\(\$at\)\n'
    r'mtc1 \$v0, \$f0\nnop\ncvt\.s\.w \$f0, \$f0\n(?P<negative>neg\.s \$f0, \$f0\n)?'
    r'cvt\.d\.s \$f0, \$f0\nmul\.d \$f0, \$f0, \$f2\naddiu \$v0, \$a1, 1\n'
    r'cvt\.s\.d \$f0, \$f0\njr \$ra\nswc1 \$f0, (?P<float>\d+)\(\$a0\))'
)
_CURSOR_DRAFT = re.compile(
    rf'void \*(?P<local>{IDENT}); (?P=local) = (?P<input>{IDENT}) \+ 1; '
    rf'M2C_FIELD\((?P<object>{IDENT}), u8 \*, (?P<first>{NUMBER})\) = \(u8\) M2C_FIELD\((?P=input), u8 \*, 0\); '
    rf'M2C_FIELD\((?P=object), u8 \*, (?P<second>{NUMBER})\) = \(u8\) M2C_FIELD\((?P=input), u8 \*, 1\); '
    rf'(?:M2C_FIELD\((?P=object), u8 \*, (?P<byte>{NUMBER})\) = \(u8\) M2C_FIELD\((?P=local), u8 \*, 1\);|'
    rf'M2C_FIELD\((?P=object), f32 \*, (?P<float>{NUMBER})\) = \(f32\) \(\(f64\) (?P<negative>-)?'
    rf'\(f32\) M2C_FIELD\((?P=local), u8 \*, 1\) \* (?P<scale>{IDENT})\);) return (?P=local) \+ 1 \+ 1;'
)
_WRAPPER_TARGET = re.compile(
    rf'move \$s0, \$a0\n(?:sw [^\n]+\n|move [^\n]+\n){{5,7}}jal (?P<get>{IDENT})\nmove \$s6, \$a3\n'
    r'lw \$a1, (?P<field>\d+)\(\$v0\)\nmove \$a0, \$s0\nmove \$a2, \$fp\nandi \$a3, \$s6, 255\n'
    r'addiu \$v1, \$a1, 8\n(?:[^\n]+\n){5,14}'
    rf'jal (?P<draw>{IDENT})\nsw \$s5, 32\(\$sp\)'
)
_WRAPPER_DRAFT = _shape('''
    void *@cursor; void *@context; @context = @get();
    @cursor = M2C_FIELD(@context, void **, @field);
    M2C_FIELD(@context, void **, @field) = (void *) (@cursor + 8);
    M2C_FIELD(@cursor, s32 *, 0) = @word;
    M2C_FIELD(@cursor, s32 *, 4) = -1;
    @draw(@first, @second, @third, @fourth & 0xFF, (s32) @fifth, (s32) @sixth, (s32) @seventh, (s32) @eighth, (s32) @ninth);
''', numbers=('field', 'word'))

_RECORD_TARGET = re.compile(
    rf'jal (?P<prepare>{IDENT})\nmove \$s0, \$a0\n'
    rf'lui \$v1, %hi\((?P<record>{IDENT})\)\nlw \$v1, %lo\((?P=record)\)\(\$v1\)\n'
    rf'sb \$s0, (?P<index>\d+)\(\$v1\)\nlui \$a0, %hi\((?P<table>{IDENT})\)\n'
    rf'lw \$a0, %lo\((?P=table)\)\(\$a0\)\nlui \$v0, %hi\((?P<first>{IDENT})\)\n'
    rf'addiu \$v0, \$v0, %lo\((?P=first)\)\nsw \$v0, (?P<left>\d+)\(\$v1\)\n'
    rf'lui \$v0, %hi\((?P<second>{IDENT})\)\naddiu \$v0, \$v0, %lo\((?P=second)\)\n'
    r'sw \$v0, (?P<right>\d+)\(\$v1\)\nlui \$v1, %hi\((?P=record)\)\n'
    r'lw \$v1, %lo\((?P=record)\)\(\$v1\)\naddu \$a0, \$a0, \$s0\n'
    r'lbu \$v0, (?P<byte>\d+)\(\$a0\)\nsb \$v0, (?P<copied>\d+)\(\$v1\)\n'
    r'lui \$v1, %hi\((?P=record)\)\nlw \$v1, %lo\((?P=record)\)\(\$v1\)\n'
    r'lbu \$a0, (?P=index)\(\$v1\)\nmove \$v0, \$zero\nsb \$a0, (?P<backup>\d+)\(\$v1\)'
)
_RECORD_DRAFT = _shape('''
    @prepare();
    M2C_FIELD(@record, u8 *, @index) = @argument;
    M2C_FIELD(@record, M2C_UNK **, @left) = &@first;
    M2C_FIELD(@record, M2C_UNK **, @right) = &@second;
    M2C_FIELD(@record, u8 *, @copied) = (u8) M2C_FIELD((M2C_FIELD(&@owner, s32 *, @address) + @argument), u8 *, @byte);
    M2C_FIELD(@record, u8 *, @backup) = (u8) M2C_FIELD(@record, u8 *, @index);
    return 0;
''', numbers=('index', 'left', 'right', 'copied', 'address', 'byte', 'backup'))

_MASK_HEAD = _shape('''
    s32 @index; s32 @bits; void *@entry;
    @index = @slot & 0xFF;
    @entry = (void *)(@global); @entry = (void *)((char *)@entry + (s32)((@index * @stride)));
    @bits = (@pressed & M2C_FIELD(@entry, s32 *, @first)) != 0;
''', numbers=('stride', 'first'))
_MASK_ARM = _shape('''
    if (@pressed & M2C_FIELD(@entry, s32 *, @field)) { @bits |= @flag; }
''', numbers=('field', 'flag'))
_MASK_CALL = _shape('@call(@index, @bits, @pressed, @entry);')
_MASK_TARGET = re.compile(
    rf'lui \$v1, %hi\((?P<global>{IDENT})\)\nlw \$v1, %lo\((?P=global)\)\(\$v1\)\n'
    r'andi \$a0, \$a0, 255\nsll \$v0, \$a0, 3\nsubu \$v0, \$v0, \$a0\nsll \$v0, \$v0, 3\n'
    r'sw \$ra, \d+\(\$sp\)\naddu \$a3, \$v1, \$v0\nlw \$v0, (?P<first>\d+)\(\$a3\)\n'
    r'move \$a2, \$a1\nlw \$v1, (?P<second>\d+)\(\$a3\)\nand \$v0, \$a2, \$v0\n'
    r'and \$v1, \$a2, \$v1\nbeqz \$v1, \d+\nsltu \$a1, \$zero, \$v0'
)
_MASK_ALIAS = re.compile(
    r'lw \$v0, (?P<guard>\d+)\(\$a3\)\nand \$v0, \$a2, \$v0\n'
    r'(?:[^\n]+\n){0,4}move \$v1, \$a3\n(?:[^\n]+\n){0,4}'
    r'lw \$v0, (?P<first>\d+)\(\$v1\)\n(?:[^\n]+\n){1,5}'
    r'lw \$v0, (?P<second>\d+)\(\$v1\)\n(?:[^\n]+\n){1,5}'
    r'lw \$v0, (?P<third>\d+)\(\$v1\)'
)


def variants(source, name, header, rows, resolve=None):
    if not 10 <= len(rows) <= 80:
        return []
    changes = {normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' '}
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    if ((hit := _CURSOR_TARGET.fullmatch(target))
            and ('addiu $a1, $a1, 1', '') in changes
            and ('addiu $v0, $a1, 1', 'addiu $v0, $a1, 3') in changes):
        family, rewrite = 'measured_three_byte_input_cursor', _cursor
    elif ((hit := _WRAPPER_TARGET.search(target))
          and ('move $s0, $a0', 'move $s5, $a0') in changes
          and ('move $s6, $a3', 'move $fp, $a3') in changes):
        family, rewrite = 'measured_narrow_forwarded_call_argument', _wrapper
    elif (resolve and (hit := _RECORD_TARGET.search(target)) and ('', 'andi $s0, $s0, 255') in changes):
        family, rewrite = 'measured_indexed_callback_record', _record
    elif ((hit := _MASK_TARGET.search(target)) and ('move $v1, $a3', '') in changes):
        family, rewrite = 'measured_mask_word_inputs', _mask
    else:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    fixed = rewrite(part, name, header, ' '.join(part.body.split()), hit, target, resolve)
    return [(family, fixed)] if fixed else []


def _signature(part, name, header, result, arguments):
    match = re.search(rf'\b{result}\s*{re.escape(name)}\({arguments}\)\s*$', part.clean[:part.opening])
    if (match and not re.search(rf'\b{re.escape(name)}\b',
                                part.clean[:match.start()] + part.clean[part.end:] + _blank(header))):
        return match
    return None


def _body(part, text, changes=()):
    return edit(part.source, [*changes, (part.opening + 1, part.end - 1, '\n' + text + '\n')])


def _offsets(draft, evidence, keys):
    return all(integer(draft[key]) == int(evidence[key]) for key in keys)


def _cursor(part, name, header, body, hit, _target, _resolve):
    draft = _CURSOR_DRAFT.fullmatch(body)
    sig = _signature(part, name, header, r'void\s*\*', rf'void \*({IDENT}), (?P<type>void) \*({IDENT})')
    form = 'byte' if hit['byte'] else 'float'
    if (not draft or not sig or (sig[1], sig[3]) != (draft['object'], draft['input'])
            or not draft[form] or not _offsets(draft, hit, ('first', 'second', form))
            or draft['scale'] != hit['scale'] or bool(draft['negative']) != bool(hit['negative'])
            or len({draft[key] for key in ('object', 'input', 'local')}) != 3):
        return None
    obj, cursor = draft['object'], draft['input']
    lines = [f'    M2C_FIELD({obj}, u8 *, {draft[key]}) = (u8) *{cursor}++;' for key in ('first', 'second')]
    if form == 'byte':
        lines.append(f'    M2C_FIELD({obj}, u8 *, {draft["byte"]}) = (u8) *{cursor}++;')
    else:
        neg = draft['negative'] or ''
        lines.append(f'    M2C_FIELD({obj}, f32 *, {draft["float"]}) = (f32) ((f64) {neg}(f32) *{cursor}++ * {draft["scale"]});')
    lines.append(f'    return {cursor};')
    return _body(part, '\n'.join(lines), [(*sig.span('type'), 'u8')])


def _wrapper(part, name, header, body, hit, _target, _resolve):
    draft = _WRAPPER_DRAFT.fullmatch(body)
    args = rf's32 ({IDENT}), M2C_UNK ({IDENT}), M2C_UNK ({IDENT}), (?P<type>s32) ({IDENT})' + rf', u8 ({IDENT})' * 5
    sig = _signature(part, name, header, 'void', args)
    keys = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth')
    if (not draft or not sig or sig.groups()[:3] + sig.groups()[4:] != tuple(draft[key] for key in keys)
            or draft['get'] != hit['get'] or draft['draw'] != hit['draw'] or not _offsets(draft, hit, ('field',))):
        return None
    first, fourth, get = (draft[key] for key in ('first', 'fourth', 'get'))
    # An unprototyped C declaration still permits the incoming argument.
    if not re.search(rf'\bvoid\s*\*{get}\(\);', part.clean[:part.opening]):
        return None
    raw = part.source[part.opening + 1:part.end - 1]
    fixed = raw.replace(f'{get}();', f'{get}({first});').replace(f'{fourth} & 0xFF', fourth)
    return edit(part.source, [(*sig.span('type'), 'u8'), (part.opening + 1, part.end - 1, fixed)])


def _record(part, name, header, body, hit, _target, resolve):
    draft = _RECORD_DRAFT.fullmatch(body)
    locals_ = ('__repair_record', '__repair_table')
    if not draft or any(token in part.clean + _blank(header) for token in locals_):
        return None
    keys = ('prepare', 'record', 'first', 'second')
    sig = _signature(part, name, header, 's32', rf'(?P<type>u8) ({IDENT})')
    base = resolve(draft['owner'])
    table = hit['table']
    if (not sig or sig[2] != draft['argument'] or base is None
            or resolve(table) != base + integer(draft['address']) or table in (draft['owner'], draft['record'])
            or any(draft[key] != hit[key] for key in keys)
            or not _offsets(draft, hit, ('index', 'left', 'right', 'copied', 'byte', 'backup'))):
        return None
    prefix = part.clean[:part.opening]
    if not re.search(rf'\bextern void\s*\*{draft["record"]}\s*;', prefix):
        return None
    context = part.clean + _blank(header)
    declaration = []
    if re.search(rf'\b{table}\b', context):
        if not re.search(rf'\bextern char\s*\*{table}\s*;', prefix + _blank(header)):
            return None
    else:
        declaration = [(sig.start(), sig.start(), f'extern char *{table};\n\n')]
    record, lookup = locals_
    root, index, arg = draft['record'], draft['index'], draft['argument']
    fixed = f'''    char *{record};
    char *{lookup};
    {draft["prepare"]}();
    {record} = {root};
    M2C_FIELD({record}, u8 *, {index}) = {arg};
    {lookup} = {table};
    M2C_FIELD({record}, M2C_UNK **, {draft["left"]}) = &{draft["first"]};
    M2C_FIELD({record}, M2C_UNK **, {draft["right"]}) = &{draft["second"]};
    M2C_FIELD({root}, u8 *, {draft["copied"]}) = (u8) M2C_FIELD(({lookup} + {arg}), u8 *, {draft["byte"]});
    M2C_FIELD({root}, u8 *, {draft["backup"]}) = (u8) M2C_FIELD({root}, u8 *, {index});
    return 0;'''
    return _body(part, fixed, [*declaration, (*sig.span('type'), 's32')])


def _mask(part, name, header, body, hit, target, _resolve):
    draft = _MASK_HEAD.match(body)
    alias = _MASK_ALIAS.search(target)
    if not draft or not alias or draft['global'] != hit['global'] or integer(draft['stride']) != 56:
        return None
    arms = list(_MASK_ARM.finditer(body, draft.end()))
    tail = _MASK_CALL.fullmatch(body[arms[-1].end():].strip()) if arms else None
    sig = _signature(part, name, header, 'void', rf's32 ({IDENT}), s32 ({IDENT})')
    if not tail or not sig or sig.groups() != (draft['slot'], draft['pressed']):
        return None
    if (len(arms) != 13 or integer(draft['first']) != int(hit['first'])
            or integer(arms[0]['field']) != int(hit['second'])
            or [integer(arm['field']) for arm in arms[8:12]] != [int(alias[key]) for key in ('guard', 'first', 'second', 'third')]
            or any(body[prev.end():after.start()].strip() for prev, after in zip([draft, *arms[:-1]], arms))
            or any(arm[key] != draft[key] for arm in [*arms, tail] for key in ('entry', 'bits', 'pressed'))
            or tail['index'] != draft['index'] or f'jal {tail["call"]}\nnop' not in target):
        return None
    base, local, first, second = ('__repair_base', '__repair_alias', '__repair_first', '__repair_second')
    if any(token in part.clean + _blank(header) for token in (base, local, first, second)):
        return None
    entry, index, bits, pressed = (draft[key] for key in ('entry', 'index', 'bits', 'pressed'))
    fixed = f'''    s32 {index};
    s32 {bits};
    void *{base};
    void *{entry};
    void *{local};
    u32 {first}, {second};

    {base} = (void *){draft["global"]};
    {index} = {draft["slot"]} & 0xFF;
    {entry} = (void *)((u8 *){base} + {index} * {draft["stride"]});
    {first} = M2C_FIELD({entry}, u32 *, {draft["first"]});
    {second} = M2C_FIELD({entry}, u32 *, {arms[0]["field"]});
    if ({pressed} & {first}) {bits} = 1; else {bits} = 0;'''
    for position, arm in enumerate(arms):
        pointer = local if 9 <= position <= 11 else entry
        cond = second if position == 0 else f'M2C_FIELD({pointer}, s32 *, {arm["field"]})'
        fixed += f'\n    if ({pressed} & {cond}) {{\n        {bits} |= {arm["flag"]};'
        if position == 8:
            fixed += f' {local} = {entry};\n    }} else {local} = {entry};'
        else:
            fixed += '\n    }'
    return _body(part, fixed + f'\n    {tail[0]}')
