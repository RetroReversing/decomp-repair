"""KMC repairs for measured scalar, stack, and loop lifetimes."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_NARROW = _shape('''
    u16 @narrow; void *@record;
    @record = M2C_FIELD(@context, void **, @pointer);
    @narrow = M2C_FIELD(@input, u16 *, 0);
    if (M2C_FIELD(@record, s32 *, @field) != @narrow) {
        M2C_FIELD(@record, s32 *, @field) = (s32) @narrow;
        if ((*M2C_FIELD(@context, s32 **, @test) < @bound) && (M2C_FIELD(@input, s32 *, @flag) == @enabled)) {
            M2C_FIELD(&@global, s8 *, @byte) = (s8) @narrow;
        }
    }
''', numbers=('pointer', 'field', 'test', 'bound', 'flag', 'enabled', 'byte'))
_COPY = _shape('''
    int @zero; s32 @index; u8 *@src; u8 *@dst; u8 @byte;
    @src = @input; @dst = @output; @index = 0; @zero = 0;
    if (@count > @zero) {
        do {
            @byte = *@src; @src += 1; @index += 1; *@dst = @byte; @dst += 1;
        } while (@index < @count);
    }
''')
_BOUND = _shape('''
    int @zero; s32 @index; s32 @result; void *@cursor;
    @result = 1;
    @cursor = M2C_FIELD(&@table, void **, @base);
    @index = 0; @zero = 0;
    if (M2C_FIELD(&@count, s32 *, @offset) > @zero) {
        do {
            @index += 1;
            @result &= -(M2C_FIELD(@cursor, s32 *, @key) != M2C_FIELD(@input, s32 *, @compare));
            @cursor += @step;
        } while ((@index < M2C_FIELD(&@count, s32 *, @offset)) & (@result != 0));
    }
    return @result;
''', numbers=('base', 'offset', 'key', 'compare', 'step'))
_RECORD = _shape('''
    s32 @state;
    @state = @call(1);
    ((@desttype*)@object)->@destvalue = (s32) ((@srctype*)@global)->@srcvalue;
    ((@desttype*)@object)->@head = (void *) ((@srctype*)@global)->@head;
    ((@srctype*)@global)->@head = @object;
    if (((@srctype*)@global)->@tail == NULL) {
        ((@srctype*)@global)->@tail = @object;
    }
    @call(@state, @global);
''')
_BUFFER = re.compile(
    rf'\bM2C_UNK (?P<base>sp[0-9A-Fa-f]+); s8 (?P<end>sp[0-9A-Fa-f]+); '
    rf'(?P<lead>void \*{IDENT}; [^{{}}]+; )(?P=end) = 0; '
    rf'(?P<write>{IDENT})\(&(?P=base), &{IDENT}, M2C_FIELD\(&{IDENT}, u8 \*, {NUMBER}\)\); '
    rf'(?P<read>{IDENT})\({IDENT}, M2C_FIELD\({IDENT}, s16 \*, {NUMBER}\), '
    rf'M2C_FIELD\({IDENT}, s16 \*, {NUMBER}\), &(?P=base)\);'
)
_INTERPOLATION = re.compile(
    rf'\b(?P<value>{IDENT}) = (?P<load>M2C_FIELD\({IDENT}, f32 \*, {NUMBER}\)); '
    rf'(?:{IDENT} = |(?P<store>(?P=load) = \(f32\) \())'
    r'(?P<rhs>\(\((?:\d+\.\d+f) - (?P=value)\) \* (?:\d+\.\d+f)\) \+ (?P=value))(?(store)\));'
)
_INDEXED_START = re.compile(
    rf's32 (?P<offset>{IDENT}); (?P=offset) = (?P<index>{IDENT}) \* (?P<stride>{NUMBER}); '
)
_INDEXED_STORE = re.compile(
    rf'\*\(&(?P<global>{IDENT}) \+ (?P<offset>{IDENT})\) = '
    rf'M2C_FIELD\((?P<source>{IDENT}), s32 \*, (?P<field>{NUMBER})\);'
)
_INDEXED_TARGET = re.compile(
    rf'lui \$v1, %hi\((?P<index>{IDENT})\)\nlw \$v1, %lo\((?P=index)\)\(\$v1\)\n'
    r'lw \$a1, \d+\(\$a0\)\nsll \$v0, \$v1, 1\naddu \$v0, \$v0, \$v1\nsll \$v0, \$v0, 3\n'
)
_INDEXED_RELOC = re.compile(
    rf'lui \$at, %hi\((?P<global>{IDENT})\)\naddu \$at, \$at, \$v0\n'
    rf'(?:jr \$ra\n)?sw \$[av][01], %lo\((?P=global)\)\(\$at\)'
)

_REG = r'\$[a-z0-9]+'
_NARROW_TARGET = re.compile(
    rf'lhu (?P<value>{_REG}), \(\$a0\)\n'
    rf'lw (?P<old>{_REG}), (?P<field>\d+)\((?P<record>{_REG})\)\n'
    r'beq (?P=old), (?P=value), \d+\nnop\nsw (?P=value), (?P=field)\((?P=record)\)'
    rf'(?:\n[^\n]+){{8,11}}\nsb (?P=value), [^\n]+\({_REG}\)'
)
_COPY_TARGET = re.compile(
    r'addiu \$sp, \$sp, -8\nblez \$a2, 40\nmove \$v1, \$zero\nlbu \$v0, \(\$a0\)\n'
    r'addiu \$a0, \$a0, 1\naddiu \$v1, \$v1, 1\nsb \$v0, \(\$a1\)\n'
    r'slt \$v0, \$v1, \$a2\nbnez \$v0, 12\naddiu \$a1, \$a1, 1\n'
    r'addiu \$sp, \$sp, 8\njr \$ra\nnop'
)
_BUFFER_TARGET = re.compile(
    rf'addiu \$a0, \$sp, (?P<base>\d+)\nlui \$a1, %hi\((?P<format>{IDENT})\)\n'
    rf'addiu \$a1, \$a1, %lo\((?P=format)\)\njal (?P<write>{IDENT})\n'
    rf'sb \$zero, (?P<end>\d+)\(\$sp\)\nlh \$a1, \d+\(\$s0\)\n'
    rf'lh \$a2, \d+\(\$s0\)\nmove \$a0, \$s0\njal (?P<read>{IDENT})\n'
    r'addiu \$a3, \$sp, (?P=base)'
)
_RECORD_TARGET = re.compile(
    rf'jal (?P<call>{IDENT})\naddiu \$a0, \$zero, 1\nlui \$a1, %hi\((?P<global>{IDENT})\)\n'
    r'lw \$a1, %lo\((?P=global)\)\(\$a1\)\nlw \$v1, \d+\(\$a1\)\nsw \$v1, \d+\(\$s0\)\n'
    r'lw \$v1, \(\$a1\)\nsw \$v1, \(\$s0\)\nlw \$v1, (?P<tail>\d+)\(\$a1\)\n'
    r'bnez \$v1, \d+\nsw \$s0, \(\$a1\)\nsw \$s0, (?P=tail)\(\$a1\)\n'
    r'jal (?P=call)\nmove \$a0, \$v0'
)
_FLOAT_TARGET = re.compile(
    rf'lui \$at, \d+\nmtc1 \$at, (?P<constant>{_REG})\nlwc1 (?P<field>{_REG}), '
    rf'(?P<offset>\d+)\((?P<base>{_REG})\)\nsub\.s (?P<value>{_REG}), (?P=constant), (?P=field)\n'
    rf'lui \$at, \d+\nori \$at, \$at, \d+\nmtc1 \$at, (?P<scale>{_REG})\nnop\n'
    r'mul\.s (?P=value), (?P=value), (?P=scale)\nadd\.s (?P=value), (?P=value), (?P=field)\n'
    r'swc1 (?P=value), (?P=offset)\((?P=base)\)'
)
_BOUND_TARGET = re.compile(
    rf'lui (?P<bound>{_REG}), %hi\((?P<count>{IDENT})\)\n'
    r'lw (?P=bound), %lo\((?P=count)\)\((?P=bound)\)\n'
    rf'lui \$a3, %hi\((?P<table>{IDENT})\)\nlw \$a3, %lo\((?P=table)\)\(\$a3\)\n'
    r'blez (?P=bound), \d+\nmove \$a1, \$zero\nlw \$a0, (?P<compare>\d+)\(\$a0\)\n'
    r'lw \$v0, (?P<key>\d+)\(\$a3\)\naddiu \$a1, \$a1, 1\nxor \$v0, \$v0, \$a0\n'
    r'sltu \$v0, \$zero, \$v0\nnegu \$v0, \$v0\nand \$a2, \$a2, \$v0\n'
    r'slt \$v0, \$a1, (?P=bound)\nsltu \$v1, \$zero, \$a2\nand \$v0, \$v0, \$v1\n'
    r'bnez \$v0, \d+\naddiu \$a3, \$a3, (?P<step>\d+)'
)


def variants(source, name, header, rows):
    if not 14 <= len(rows) <= 72:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changes = [normalized_integer_lines((left, right)) for tag, left, right in rows if tag != ' ']
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    body = ' '.join(part.body.split())
    if ((evidence := _NARROW_TARGET.search(target)) and (draft := _NARROW.fullmatch(body))
            and any(not left and re.fullmatch(rf'andi {_REG}, {_REG}, 65535', right) for left, right in changes)):
        family, fixed = 'measured_narrow_word_carrier', _narrow(part, draft, evidence, source + header)
    elif (_COPY_TARGET.fullmatch(target) and (draft := _COPY.fullmatch(body))
          and ('', 'jr $ra') in changes and ('jr $ra', '') in changes):
        family, fixed = 'measured_guarded_byte_copy', _copy(part, name, draft)
    elif ((evidence := _BUFFER_TARGET.search(target)) and (draft := _BUFFER.fullmatch(body))
          and (f'addiu $a0, $sp, {evidence["base"]}', '') in changes
          and (f'sb $zero, {evidence["end"]}($sp)', f'addiu $a0, $sp, {evidence["base"]}') in changes):
        family, fixed = 'measured_terminated_stack_buffer', _buffer(part, draft, evidence, source + header)
    elif ((evidence := _RECORD_TARGET.search(target)) and (draft := _RECORD.fullmatch(body))
          and ('', f'lui $a1, %hi({evidence["global"]})') in changes
          and ('', f'lw $a1, %lo({evidence["global"]})($a1)') in changes):
        family, fixed = 'measured_call_record_carrier', _record(part, draft, evidence, source + header)
    elif ((evidence := _FLOAT_TARGET.search(target)) and (draft := _INTERPOLATION.search(body))
          and ('', f'lwc1 {evidence["field"]}, {evidence["offset"]}({evidence["base"]})') in changes
          and (f'lwc1 {evidence["field"]}, {evidence["offset"]}({evidence["base"]})', 'nop') in changes):
        family, fixed = 'measured_float_interpolation_load', _interpolation(part, draft, evidence)
    elif ((evidence := _INDEXED_TARGET.match(target)) and ('sll $v0, $v0, 3', 'sll $v0, $v0, 5') in changes
          and ('', target.splitlines()[-1]) in changes and (target.splitlines()[-1], 'nop') in changes):
        family, fixed = 'measured_indexed_byte_stores', _indexed(part, name, body, target, evidence)
    elif ((evidence := _BOUND_TARGET.search(target)) and (draft := _BOUND.fullmatch(body))
          and any(not left and re.fullmatch(rf'move {re.escape(evidence["bound"])}, {_REG}', right)
                  for left, right in changes)):
        family, fixed = 'measured_cached_loop_bound', _bound(part, draft, evidence, source + header)
    else:
        return []
    return [(family, fixed)] if fixed else []


def _fresh(source, token):
    return not re.search(rf'\b{token}\b', source)


def _replace(part, replacements):
    """Preserve the draft's formatting outside the matched fragments."""
    changes = []
    for fragment, replacement in replacements:
        pattern = re.escape(fragment).replace(r'\ ', r'\s+')
        if fragment[0].isalnum() or fragment[0] == '_':
            pattern = r'(?<!\w)' + pattern
        hits = list(re.finditer(pattern, part.body))
        if not hits:
            return None
        changes.extend((part.opening + 1 + hit.start(), part.opening + 1 + hit.end(), replacement) for hit in hits)
    return edit(part.source, changes)


def _narrow(part, draft, target, context):
    saved = '__repair_word'
    if not _fresh(context, saved) or integer(draft['field']) != int(target['field']):
        return None
    value = draft['narrow']
    load = f'{value} = M2C_FIELD({draft["input"]}, u16 *, 0);'
    return _replace(part, [
        (f'u16 {value};', f'u16 {value};\n    u32 {saved};'),
        (load, f'{load}\n    {saved} = {value};'),
        (f'!= {value})', f'!= ({saved} = {value}))'),
        (f'(s32) {value};', f'(s32) {saved};'),
        (f'(s8) {value};', f'(s8) {saved};'),
    ])


def _copy(part, name, draft):
    src, dst, count, index = (draft[key] for key in ('input', 'output', 'count', 'index'))
    signature = rf'\bvoid\s+{re.escape(name)}\(u8\s*\*{src},\s*u8\s*\*{dst},\s*s32 {count}\)\s*$'
    if not re.search(signature, part.clean[:part.opening]) or len(set(draft.groupdict().values())) != 8:
        return None
    # With KMC -g3, the multiline spelling still emitted the return before
    # the stack adjustment. This compact spelling reproduced the target.
    body = f' s32 {index}; for ({index} = 0; {index} < {count}; {index}++) {{ *{dst}++ = *{src}++; }} '
    return part.source[:part.opening + 1] + body + part.source[part.end - 1:]


def _buffer(part, draft, target, context):
    base, end = (int(draft[key][2:], 16) for key in ('base', 'end'))
    new = '__repair_text'
    if (end - base != 4 or base != int(target['base']) or end != int(target['end'])
            or any(draft[key] != target[key] for key in ('write', 'read')) or not _fresh(context, new)
            or len(re.findall(rf'\b{draft["base"]}\b', part.body)) != 3
            or len(re.findall(rf'\b{draft["end"]}\b', part.body)) != 2):
        return None
    return _replace(part, [
        (f'M2C_UNK {draft["base"]}; s8 {draft["end"]};', f's8 {new}[5];'),
        (f'{draft["end"]} = 0;', f'{new}[4] = 0;'),
        (f'&{draft["base"]}', new),
    ])


def _record(part, draft, target, context):
    local = '__repair_record'
    root = draft['global']
    if (root != target['global'] or draft['call'] != target['call'] or not _fresh(context, local)
            or not re.search(rf'\bextern void\s*\*{root}\s*;', context)
            or len(re.findall(rf'\b{root}\b', part.body)) != 6):
        return None
    first = f'{draft["state"]} = {draft["call"]}(1);'
    decl = f's32 {draft["state"]};'
    return _replace(part, [
        (decl, f'void *{local};\n    {decl}'),
        (first, f'{first}\n    {local} = {root};'),
        (f'*){root})', f'*){local})'),
        (f'{draft["state"]}, {root})', f'{draft["state"]}, {local})'),
    ])


def _interpolation(part, draft, target):
    offset = re.search(rf', ({NUMBER})\)$', draft['load'])
    if not offset or integer(offset[1]) != int(target['offset']):
        return None
    whole = re.escape(draft[0]).replace(r'\ ', r'\s+')
    assignment = re.search(r'(?<!\w)' + whole, part.body)
    if not assignment:
        return None
    prefix = draft[0][:draft.start('rhs') - draft.start()]
    prefix = re.escape(prefix).replace(r'\ ', r'\s+')
    rhs = re.match(prefix, assignment[0])
    if not rhs:
        return None
    start = part.opening + 1 + assignment.start() + rhs.end()
    end = part.opening + 1 + assignment.end()
    expression = re.sub(rf'\b{draft["value"]}\b', f'({draft["load"]})', part.source[start:end])
    return part.source[:start] + expression + part.source[end:]


def _indexed(part, name, body, target, evidence):
    start = _INDEXED_START.match(body)
    if not start or start['index'] != evidence['index'] or integer(start['stride']) != 24:
        return None
    stores = body[start.end():].split('; ')
    if len(stores) != 4:
        return None
    drafts = [_INDEXED_STORE.fullmatch(store.rstrip(';') + ';') for store in stores]
    if not all(drafts):
        return None
    globals_ = [hit['global'] for hit in _INDEXED_RELOC.finditer(target)]
    fields = [integer(field) for field in re.findall(r'lw \$[av][01], (\d+)\(\$a0\)', target)]
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*({IDENT})\)\s*$', part.clean[:part.opening])
    if (not signature or len(set(globals_)) != 4 or [draft['global'] for draft in drafts] != globals_
            or [integer(draft['field']) for draft in drafts] != fields
            or any((draft['source'], draft['offset']) != (signature[1], start['offset']) for draft in drafts)
            or any(not re.search(rf'\bextern M2C_UNK {symbol}\s*;', part.clean[:part.opening]) for symbol in globals_)):
        return None
    # Byte pointers provide the measured stride. KMC -g3 also needs the
    # final store on the closing brace's source line to fill the return slot.
    fixed = body[:start.end()] + ' '.join(
        f'*(s32 *)((u8 *)&{draft["global"]} + {start["offset"]}) = '
        f'M2C_FIELD({draft["source"]}, s32 *, {draft["field"]});' for draft in drafts
    )
    return part.source[:part.opening + 1] + f' {fixed} ' + part.source[part.end - 1:]


def _bound(part, draft, target, context):
    bound = '__repair_count'
    if (not _fresh(context, bound) or draft['count'] == draft['table']
            or any(integer(draft[key]) != int(target[key]) for key in ('key', 'compare', 'step'))):
        return None
    load = f'M2C_FIELD(&{draft["count"]}, s32 *, {draft["offset"]})'
    decl = f's32 {draft["index"]};'
    cursor = f'{draft["cursor"]} = M2C_FIELD'
    return _replace(part, [
        (decl, f's32 {bound};\n    {decl}'),
        (cursor, f'{bound} = {load};\n    {cursor}'),
        (load, bound),
    ])
