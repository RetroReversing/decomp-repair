"""Repair short KMC drafts when the linked diff identifies the C value that was lost."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_MASKS = re.compile(
    r'lw \$v0, (?P<base>\d+)\(\$a0\)\nandi \$a1, \$a1, 65535\nsll \$a1, \$a1, (?P<scale>[1-8])\n'
    r'andi \$a2, \$a2, 65535\nsll \$a2, \$a2, (?P<left>[1-9]\d*)\naddu \$v0, \$a1, \$v0\n'
    r'sh \$a2, (?P<first>\d+)\(\$v0\)\nlw \$v0, (?P=base)\(\$a0\)\n'
    r'andi \$a3, \$a3, 65535\nsll \$a3, \$a3, (?P<right>[1-9]\d*)\naddu \$a1, \$a1, \$v0\n'
    r'jr \$ra\nsh \$a3, (?P<second>\d+)\(\$a1\)'
)
_MASK_SOURCE = _shape('''
    s32 @off;
    @off = (@index & 0xFFFF) * @scale;
    M2C_FIELD((@off + M2C_FIELD(@obj, s32 *, @base)), s16 *, @first) = (s16) ((@x & 0xFFFF) << @left);
    M2C_FIELD((@off + M2C_FIELD(@obj, s32 *, @base)), s16 *, @second) = (s16) ((@y & 0xFFFF) << @right);
''', numbers=('scale', 'base', 'first', 'second', 'left', 'right'))

_SQRT = '''bltz $a0, 32
move $v0, $zero
mtc1 $a0, $f0
nop
cvt.s.w $f0, $f0
sqrt.s $f0, $f0
trunc.w.s $f2, $f0
mfc1 $v0, $f2
jr $ra
nop'''
_SQRT_SOURCE = _shape('''
    s32 @result;
    @result = 0;
    if (@input >= 0) { @result = (s32) sqrtf((f32) @input); }
    return @result;
''')

_UNSIGNED_STORE = re.compile(
    rf'lui \$v0, %hi\((?P<base>{IDENT})\)\nlw \$v0, %lo\((?P=base)\)\(\$v0\)\n'
    r'andi \$a0, \$a0, 255\nsll \$a0, \$a0, 1\naddu \$a0, \$a0, \$v0\nori \$v0, \$zero, 65535\n'
    r'jr \$ra\nsh \$v0, (?P<field>\d+)\(\$a0\)'
)

_CLEAR_LOOP = re.compile(
    rf'move \$v1, \$zero\nlui \$a0, %hi\((?P<base>{IDENT})\)\naddiu \$a0, \$a0, %lo\((?P=base)\)\n'
    r'andi \$v0, \$v1, 65535\nsll \$v0, \$v0, 2\naddu \$v0, \$v0, \$a0\nsw \$zero, \(\$v0\)\n'
    r'addiu \$v1, \$v1, 1\nandi \$v0, \$v1, 65535\nsltiu \$v0, \$v0, (?P<count>\d+)\n'
    r'bnel \$v0, \$zero, 16\nandi \$v0, \$v1, 65535\njr \$ra\nnop'
)
_CLEAR_SOURCE = re.compile(
    rf'\s*s32 (?P<index>{IDENT});\s*(?P=index) = 0;\s*do \{{\s*'
    rf'(?P<star>\*)\(\(\((?P=index) & 0xFFFF\) \* 4\) \+ \(\(char \*\)&(?P<base>{IDENT}) \+ (?P<offset>{NUMBER})\)\) = 0;'
    rf'\s*(?P=index) \+= 1;\s*\}} while \(\(u32\) \((?P=index) & 0xFFFF\) < (?P<count>{NUMBER})\);\s*'
)

_POINTER_TABLE = re.compile(
    r'beqz \$a0, 32\naddiu \$v0, \$zero, 1\nsll \$v0, \$a0, 2\n'
    rf'lui \$at, %hi\((?P<base>{IDENT})\)\naddu \$at, \$at, \$v0\nlw \$v0, %lo\((?P=base)\)\(\$at\)\n'
    r'addu \$v0, \$v0, \$a1\nlbu \$v0, \(\$v0\)\njr \$ra\nandi \$v0, \$v0, 255'
)
_POINTER_SOURCE = _shape('''
    u8 @value;
    @value = 1;
    if (@first != 0) { @value = *(u8 *)(*(@table + (@first * 4)) + @second); }
    return @value & 0xFF;
''')

_CASE_BYTE = re.compile(
    r'addiu \$v0, \$a0, -(?P<start>\d+)\nandi \$v0, \$v0, 255\nsltiu \$v0, \$v0, (?P<count>\d+)\n'
    rf'bnez \$v0, 28\nmove \$v1, \$a0\nj (?P<name>{IDENT})\+36\nandi \$v0, \$v1, 255\n'
    r'addiu \$v0, \$a0, (?P<adjust>\d+)\nandi \$v0, \$v0, 255\njr \$ra\nnop'
)
_CASE_SOURCE = _shape('''
    if ((u32) ((@arg - @start) & 0xFF) >= @count) { goto @label; }
    return (@arg + @adjust) & 0xFF;
    @label: { return @arg & 0xFF; }
''', numbers=('start', 'count', 'adjust'))


def variants(source, name, header, rows, *, resolve=None, flags=()):
    if len(rows) == 29:
        return _loop_pointer_table(source, name, rows, resolve)
    if len(rows) not in (8, 10, 11, 13, 14):
        return []
    changes = [(left, right) for mark, left, right in rows if mark != ' ']
    if not changes:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    if len(changes) == 2 and (match := _MASKS.fullmatch(target)) and all(
        not have and normalized_integer_lines((want,))[0] == f'andi $a{register}, $a{register}, 65535'
        for register, (want, have) in zip((2, 3), changes)
    ):
        family, build, evidence = 'measured_shared_halfword_mask', _shared_mask, match
    elif target == _SQRT and '-ffast-math' in flags and '-fno-fast-math' not in flags:
        family, build, evidence = 'measured_early_integer_sqrt', _early_sqrt, None
    elif (match := _UNSIGNED_STORE.fullmatch(target)) and len(changes) == 1 and normalized_integer_lines(
        changes[0]
    ) == ('ori $v0, $zero, 65535', 'addiu $v0, $zero, -1'):
        family, build, evidence = 'measured_indexed_unsigned_halfword_store', _unsigned_store, match
    elif (match := _CLEAR_LOOP.fullmatch(target)) and changes == [('sw $zero, ($v0)', 'sb $zero, ($v0)')]:
        family, build, evidence = 'measured_word_clear_loop', _word_clear, match
    elif (match := _POINTER_TABLE.fullmatch(target)) and len(changes) == 1 and changes[0] == (
        f'lw $v0, %lo({match["base"]})($at)', f'lb $v0, %lo({match["base"]})($at)',
    ):
        family, build, evidence = 'measured_byte_pointer_table', _pointer_table, match
    elif len(changes) == 4 and (match := _CASE_BYTE.fullmatch(target)) and match['name'] == name:
        family, build, evidence = 'measured_narrow_case_byte', _case_byte, match
    else:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    fixed = build(part, name, header, resolve, evidence)
    return [(family, fixed)] if fixed else []


def _shared_mask(part, name, header, _resolve, evidence):
    helper = '__repair_shared_halfword_mask'
    match = _MASK_SOURCE.fullmatch(' '.join(part.body.split()))
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*({IDENT}), s32 ({IDENT}), s32 ({IDENT}), s32 ({IDENT})\)\s*$',
                          part.clean[:part.opening])
    if (not match or not signature or signature.groups() != tuple(match[key] for key in ('obj', 'index', 'x', 'y'))
            or helper in part.source + header):
        return None
    if any(integer(match[key]) != int(evidence[key]) for key in ('base', 'first', 'second', 'left', 'right')):
        return None
    if integer(match['scale']) != 1 << int(evidence['scale']):
        return None
    start = part.opening + 1
    body = part.source[start:part.end - 1]
    place = re.search(rf'\b{match["off"]}\s*=', part.body)
    head = body[:place.start()]
    tail = body[place.start():].replace('0xFFFF', helper)
    fixed = f'\n    s32 {helper};' + head + f'{helper} = 0xFFFF;\n    ' + tail
    return edit(part.source, [(start, part.end - 1, fixed)])


def _early_sqrt(part, name, header, _resolve, _evidence):
    signature = re.search(rf'\bs32\s+{re.escape(name)}\(s32 ({IDENT})\)\s*$', part.clean[:part.opening])
    match = _SQRT_SOURCE.fullmatch(' '.join(part.body.split()))
    if not signature or not match or match['input'] != signature[1] or '__builtin_sqrtf' in header:
        return None
    arg = signature[1]
    fixed = f'\n    if ({arg} < 0) return 0;\n    return (s32)__builtin_sqrtf((f32){arg});\n'
    return edit(part.source, [(part.opening + 1, part.end - 1, fixed)])


def _unsigned_store(part, name, _header, _resolve, target):
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(s32 ({IDENT})\)\s*$', part.clean[:part.opening])
    base = target['base']
    if not signature:
        return None
    source = re.fullmatch(
        rf'\s*M2C_FIELD\(\(\(\({signature[1]} & 0xFF\) \* 2\) \+ {base}\), '
        rf'(?P<type>s16) \*, (?P<field>{NUMBER})\) = (?P<value>{NUMBER});\s*', part.body)
    if not source or integer(source['field']) != int(target['field']) or integer(source['value']) != 65535:
        return None
    start = part.opening + 1
    return edit(part.source, [(start + source.start('type'), start + source.end('type'), 'u16')])


def _word_clear(part, name, _header, resolve, target):
    source = _CLEAR_SOURCE.fullmatch(part.body)
    if not source or not resolve or not re.search(rf'\bvoid\s+{re.escape(name)}\(void\)\s*$', part.clean[:part.opening]):
        return None
    base = resolve(source['base'])
    if base is None or base + integer(source['offset']) != resolve(target['base']) or integer(source['count']) != int(target['count']):
        return None
    start = part.opening + 1 + source.end('star')
    return edit(part.source, [(start, start, '(s32 *)')])


def _pointer_table(part, name, header, _resolve, evidence):
    base = evidence['base']
    sig = re.search(rf'\bs32\s+{re.escape(name)}\(s32 ({IDENT}), s32 ({IDENT})\)\s*$', part.clean[:part.opening])
    source = _POINTER_SOURCE.fullmatch(' '.join(part.body.split()))
    decl = re.search(rf'(?m)^\s*extern (?P<type>char) {base}\[\];', part.clean[:part.opening])
    if (not source or not sig or not decl or sig.groups() != (source['first'], source['second'])
            or source['table'] != base or len(re.findall(rf'\b{base}\b', part.clean + _blank(header))) != 2):
        return None
    match = re.search(rf'\*\(u8 \*\)\(\*\({base} \+ \({source["first"]} \* 4\)\) \+ {source["second"]}\)', part.body)
    if not match:
        return None
    start = part.opening + 1
    return edit(part.source, [(*decl.span('type'), 'u8 *'), (start + match.start(), start + match.end(),
                             f'{base}[{source["first"]}][{source["second"]}]')])


def _case_byte(part, name, header, _resolve, evidence):
    signature = re.search(rf'\bs32\s+{re.escape(name)}\((?P<type>s32) ({IDENT})\)\s*$', part.clean[:part.opening])
    match = _CASE_SOURCE.fullmatch(' '.join(part.body.split()))
    if (not signature or not match or signature[2] != match['arg']
            or re.search(rf'\b{re.escape(name)}\b', _blank(header) + part.clean[:signature.start()] + part.clean[part.end:])):
        return None
    if any(integer(match[key]) != int(evidence[key]) for key in ('start', 'count', 'adjust')):
        return None
    arg = match['arg']
    fixed = f'''
    if ((u8)({arg} - {match["start"]}) < {match["count"]}) {{
        return (u8)({arg} + {match["adjust"]});
    }}
    return (u8){arg};
'''
    return edit(part.source, [(*signature.span('type'), 'char'), (part.opening + 1, part.end - 1, fixed)])


def _loop_pointer_table(source, name, rows, resolve):
    """Recover a word-sized table entry in a masked search loop."""
    if not resolve:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    evidence = re.search(
        rf'lui \$t1, %hi\((?P<table>{IDENT})\)\naddiu \$t1, \$t1, %lo\((?P=table)\)\n'
        r'andi \$v0, \$a2, 65535\nsll \$v0, \$v0, 2\naddu \$v0, \$v0, \$t1\n'
        r'lw \$a1, \(\$v0\)\nbeql \$a1, \$zero, \d+\naddiu \$a2, \$a2, 1\n'
        r'lw \$v0, 4\(\$a1\)\nbeql \$v0, \$a0, \d+\naddiu \$t0, \$zero, 1', target,
    )
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (not evidence or ('lw $a1, ($v0)', 'lb $a1, ($v0)') not in changes
            or len(changes) != 3):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    load = re.search(
        rf'(?P<result>{IDENT}) = (?P<star>\*)\(\(\((?P<index>{IDENT}) & 0xFFFF\) \* 4\) \+ '
        rf'\(\(char \*\)&(?P<base>{IDENT}) \+ (?P<offset>{NUMBER})\)\);', part.body,
    )
    if (not load or not re.search(rf'\bvoid \*{load["result"]}\s*;', part.body)
            or not re.search(rf'\bdo\s*\{{[^{{}}]*{re.escape(load[0])}', part.body)
            or not re.search(rf'\b{load["index"]}\s*\+=\s*1;', part.body)
            or not re.search(rf'\b{load["result"]}\s*!=\s*NULL', part.body)):
        return []
    base = resolve(load['base'])
    if base is None or base + integer(load['offset']) != resolve(evidence['table']):
        return []
    pos = part.opening + 1 + load.end('star')
    return [('measured_masked_pointer_search', edit(source, [(pos, pos, '(void **)')]))]
