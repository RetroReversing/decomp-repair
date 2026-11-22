"""Recover KMC source lifetimes for measured address and call operands."""

import re
from collections import Counter

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_NORMALIZE = _shape('''
    f32 @x; f32 @y; f32 @z; f32 @length;
    @x = M2C_FIELD(@src, f32 *, 0); @y = M2C_FIELD(@src, f32 *, 4); @z = M2C_FIELD(@src, f32 *, 8);
    @length = sqrtf((@x * @x) + (@y * @y) + (@z * @z));
    if (@length == 0.0f) { @length = 1.0f; }
    M2C_FIELD(@dst, f32 *, 0) = (f32) (@x / @length);
    M2C_FIELD(@dst, f32 *, 4) = (f32) (M2C_FIELD(@src, f32 *, 4) / @length);
    M2C_FIELD(@dst, f32 *, 8) = (f32) (M2C_FIELD(@src, f32 *, 8) / @length);
    return @length;
''')

_NORMALIZE_TARGET = '''lwc1 $f6, ($a0)
mul.s $f4, $f6, $f6
lwc1 $f0, 4($a0)
mul.s $f0, $f0, $f0
lwc1 $f2, 8($a0)
mul.s $f2, $f2, $f2
add.s $f4, $f4, $f0
add.s $f4, $f4, $f2
sqrt.s $f2, $f4
mtc1 $zero, $f0
nop
c.eq.s $f2, $f0
nop
nop
bc1fl @
div.s $f4, $f6, $f2
lui $at, 16256
mtc1 $at, $f2
nop
div.s $f4, $f6, $f2
swc1 $f4, ($a1)
lwc1 $f0, 4($a0)
div.s $f0, $f0, $f2
swc1 $f0, 4($a1)
lwc1 $f0, 8($a0)
div.s $f0, $f0, $f2
swc1 $f0, 8($a1)
jr $ra
mov.s $f0, $f2'''

_INDEX = re.compile(
    rf'lui \$v1, %hi\((?P<base>{IDENT})\)\nlw \$v1, %lo\((?P=base)\)\(\$v1\)\n'
    r'andi \$a0, \$a0, 255\nsll \$v0, \$a0, 1\naddu \$v0, \$v0, \$a0\nsll \$v0, \$v0, 3\n'
    r'addu \$v1, \$v1, \$v0\nlw \$v0, (?P<field>\d+)\(\$v1\)\nxori \$v0, \$v0, (?P<value>\d+)\n'
    r'jr \$ra\nsltiu \$v0, \$v0, 1'
)

_INLINE = re.compile(
    rf'lui \$v0, %hi\((?P<base>{IDENT})\)\nlw \$v0, %lo\((?P=base)\)\(\$v0\)\n'
    r'addiu \$sp, \$sp, -24\nsw \$s0, 16\(\$sp\)\nsll \$s0, \$a0, (?P<left>\d+)\nsw \$ra, 20\(\$sp\)\n'
    r'lw \$v0, (?P<extra>\d+)\(\$v0\)\nsra \$s0, \$s0, (?P<right>\d+)\naddiu \$a0, \$s0, (?P<bias>\d+)\n'
    rf'jal (?P<call>{IDENT})\naddu \$a0, \$v0, \$a0\n'
    r'lui \$v0, %hi\((?P=base)\)\nlw \$v0, %lo\((?P=base)\)\(\$v0\)\nlw \$v0, (?P=extra)\(\$v0\)\n'
    r'addu \$s0, \$s0, \$v0\nlw \$v0, (?P=bias)\(\$s0\)\n'
    r'lw \$ra, 20\(\$sp\)\nlw \$s0, 16\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 24'
)

_FORWARD = re.compile(
    r'addiu \$sp, \$sp, -24\nmove \$a3, \$a0\nsw \$ra, 16\(\$sp\)\n'
    r'lbu \$v0, (?P<flag>\d+)\(\$a3\)\nbnez \$v0, @\nmove \$t0, \$a1\n'
    r'lw \$v1, \(\$a3\)\nlw \$a1, 4\(\$a3\)\nlw \$a0, 8\(\$a3\)\n'
    r'addiu \$v0, \$zero, 1\nsb \$v0, (?P=flag)\(\$a3\)\n'
    r'addu \$v1, \$v1, \$t0\naddu \$a1, \$a1, \$t0\naddu \$a0, \$a0, \$t0\n'
    r'sw \$a1, 4\(\$a3\)\nmove \$a1, \$t0\nsw \$v1, \(\$a3\)\n'
    rf'jal (?P<call>{IDENT})\nsw \$a0, 8\(\$a3\)\nlw \$ra, 16\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 24'
)


def _member_byte_add_order(source, name, header, rows, flags):
    """Preserve the byte offset as the first input to repeated pointer sums."""
    if '-mgp32' not in flags or {'-mgp64', '-mabi=64', '-mabi=n32'} & set(flags):
        return None
    add = re.compile(r'addu (\$\w+), (\$\w+), (\$\w+)')
    swaps = Counter()
    for mark, left, right in rows:
        if mark != 'r' or not (target := add.fullmatch(left)) or not (actual := add.fullmatch(right)):
            continue
        if target[2] != target[3] and target.groups() == (actual[1], actual[3], actual[2]):
            swaps[target.groups()] += 1
    if len(swaps) != 1 or not 2 <= (count := next(iter(swaps.values()))) <= 8:
        return None
    part = view(source, name)
    if not part:
        return None
    pattern = re.compile(
        rf'(?P<offset>{IDENT})\s*\+\s*\(\s*\(\s*char\s*\*\s*\)\s*'
        rf'(?P<base>{IDENT}\s*->\s*{IDENT})\s*\)'
    )
    sites = list(pattern.finditer(part.clean, part.opening + 1, part.end))
    if len(sites) != count or len({hit['offset'] for hit in sites}) != 1:
        return None
    offset = sites[0]['offset']
    member = sites[0]['base'].split('->')[1].strip()
    if any(hit['base'].split('->')[1].strip() != member for hit in sites):
        return None
    if len(re.findall(rf'(?m)^[ \t]*(?:s32|u32|int)\s+{offset}\s*;', part.body)) != 1:
        return None
    context = header + '\n' + part.clean[:part.opening]
    if not re.search(rf'\b{IDENT}\s*\*\s*{member}\s*;', context) or re.search(
        rf'(?m)^[ \t]*#\s*define\s+(?:{offset}|u32)\b', context
    ):
        return None
    if any(re.search(r'/[*/]', source[hit.start():hit.end()]) for hit in sites):
        return None
    return edit(source, [(hit.start(), hit.end(), f'(u32){offset} + (u32){source[slice(*hit.span("base"))]}')
                         for hit in sites])


def variants(source, name, header, rows, flags=()):
    if candidate := _member_byte_add_order(source, name, header, rows, flags):
        return [('measured_member_byte_add_order', candidate)]
    changed = [i for i, (mark, _, _) in enumerate(rows) if mark != ' ']
    if not changed or len(rows) not in (11, 12, 20, 21, 22, 29) or '__repair_address_' in source + header:
        return []
    ops = normalized_integer_lines(row[1] for row in rows if row[1])
    target = '\n'.join(re.sub(r'^(bc1fl|bnez \$v0,) \S+$', r'\1 @', row) for row in ops)
    if '-ffast-math' in flags and '-fno-fast-math' not in flags and target == _NORMALIZE_TARGET:
        family, pattern, build = 'staged_float_normalization', True, _normalize
    elif pattern := _INDEX.fullmatch(target):
        family, build = 'staged_indexed_context', _indexed
    elif pattern := _INLINE.fullmatch(target):
        family, build = 'inline_staged_address_sum', _inline
    elif pattern := _FORWARD.fullmatch(target):
        family, build = 'forwarded_third_record_argument', _forward
    else:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    candidate = build(part, name, header, end, pattern)
    return [(family, candidate)] if candidate else []


def _protected(name, header, earlier):
    return re.search(rf'\b{re.escape(name)}\s*\(', header + earlier)


def _normalize(part, name, header, end, _):
    sig = re.search(rf'\bf32\s+{re.escape(name)}\(void \*({IDENT}), void \*({IDENT})\)\s*$',
                    part.clean[:part.opening])
    if not sig or _protected(name, header, part.clean[:sig.start()]):
        return None
    match = _NORMALIZE.fullmatch(' '.join(part.clean[part.opening + 1:end - 1].split()))
    if not match or (match['src'], match['dst']) != sig.groups():
        return None
    src, dst = sig.groups()
    x, y, z, d, q = ('__repair_address_' + n for n in ('x', 'y', 'z', 'length', 'quotient'))
    fixed = f'''f32 {name}(f32 *{src}, f32 *{dst}) {{
    f32 {x}, {d}, {y}, {z}, {q};
    {x} = {src}[0];
    {y} = {src}[1];
    {z} = {src}[2];
    {d} = {x} * {x} + {y} * {y};
    {d} += {z} * {z};
    {z} = __builtin_sqrtf({d});
    if ({z} == 0.0f) {z} = 1.0f;
    {d} = {x} / {z};
    {dst}[0] = {d};
    {q} = {z};
    {dst}[1] = {src}[1] / {q};
    {dst}[2] = {src}[2] / {z};
    return {z};
}}'''
    return edit(part.source, [(sig.start(), end, fixed)])


def _indexed(part, name, header, end, target):
    base = target['base']
    sig = re.search(rf'\bs32\s+{re.escape(name)}\(s32 ({IDENT})\)\s*$', part.clean[:part.opening])
    if not sig or re.search(rf'\b{base}\b', header):
        return None
    decl = re.search(rf'(?m)^extern s32 {base};[ \t]*$', part.clean[:sig.start()])
    index = sig[1]
    body = ' '.join(part.clean[part.opening + 1:end - 1].split())
    source = re.fullmatch(
        rf'return M2C_FIELD\(\({base} \+ \(\({index} & 0xFF\) \* (?P<stride>{NUMBER})\)\), '
        rf's32 \*, (?P<offset>{NUMBER})\) == (?P<value>{NUMBER});', body)
    if not decl or not source or [integer(source[k]) for k in ('stride', 'offset', 'value')] != [
            24, int(target['field']), int(target['value'])]:
        return None
    fixed = f'''
    s8 *__repair_address_base;
    s32 __repair_address_offset;
    __repair_address_base = {base};
    __repair_address_offset = ({index} & 0xFF) * 24;
    return *(s32 *)(__repair_address_base + __repair_address_offset + {source['offset']}) == {source['value']};
'''
    return edit(part.source, [(*decl.span(), f'extern s8 *{base};'), (part.opening + 1, end - 1, fixed)])


def _inline(part, name, header, end, target):
    head = part.clean[:part.opening]
    sig = re.search(rf'\bs32\s+{re.escape(name)}\(s32 ({IDENT})\)\s*$', head)
    if not sig or re.search(r'(?m)^\s*#\s*define\s+inline\b', header):
        return None
    base, call = target['base'], target['call']
    body = re.fullmatch(
        rf's32 (?P<local>{IDENT}); (?P=local) = \(s32\) \({sig[1]} << (?P<left>{NUMBER})\) >> (?P<right>{NUMBER}); '
        rf'{call}\(M2C_FIELD\({base}, s32 \*, (?P<extra>{NUMBER})\) \+ \((?P=local) \+ (?P<bias>{NUMBER})\)\); '
        rf'return M2C_FIELD\(\((?P=local) \+ M2C_FIELD\({base}, s32 \*, (?P=extra)\)\), s32 \*, (?P=bias)\);',
        ' '.join(part.clean[part.opening + 1:end - 1].split()))
    if not body or any(integer(body[k]) != int(target[k]) for k in ('left', 'right', 'extra', 'bias')):
        return None
    add = '__repair_address_add'
    helper = f'static inline s32 {add}(s32 x, s32 y) {{ return x + y; }}\n'
    fixed = f'''
    s32 {body['local']};
    {body['local']} = (s32) ({sig[1]} << {body['left']}) >> {body['right']};
    {call}(M2C_FIELD({base}, s32 *, {body['extra']}) + {add}({body['local']}, {body['bias']}));
    return M2C_FIELD({add}({body['local']}, M2C_FIELD({base}, s32 *, {body['extra']})), s32 *, {body['bias']});
'''
    return edit(part.source, [(sig.start(), sig.start(), helper), (part.opening + 1, end - 1, fixed)])


def _forward(part, name, header, end, target):
    head = part.clean[:part.opening]
    sig = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*({IDENT}), s32 ({IDENT})(?P<end>\))\s*$', head)
    if not sig or _protected(name, header, head[:sig.start()]):
        return None
    call = target['call']
    if _protected(call, header, ''):
        return None
    decl = re.search(rf'(?m)^M2C_UNK {call}\(s32, s32, (?P<third>void \*)\);[^\n]*', head)
    if not decl:
        return None
    obj, base = sig.group(1, 2)
    field = f'M2C_FIELD({obj}, s32 *,'
    source = re.compile(
        rf's32 (?P<ptr>{IDENT}); if \(M2C_FIELD\({obj}, u8 \*, (?P<flag>{NUMBER})\) == 0\) \{{ '
        rf'M2C_FIELD\({obj}, u8 \*, (?P=flag)\) = 1U; '
        + ''.join(rf'{re.escape(field)} {off}\) = \(s32\) \({re.escape(field)} {off}\) \+ {base}\); '
                  for off in (0, 4))
        + rf'(?P=ptr) = {re.escape(field)} 8\) \+ {base}; {re.escape(field)} 8\) = (?P=ptr); '
        + rf'{call}\((?P=ptr), {base}, {obj}\); \}}')
    if not (match := source.fullmatch(' '.join(part.clean[part.opening + 1:end - 1].split()))) or integer(
            match['flag']) != int(target['flag']):
        return None
    use = re.search(rf'{call}\({match["ptr"]}, {base}, (?P<arg>{obj})\);', part.clean[part.opening + 1:end - 1])
    if not use:
        return None
    a, b = (part.opening + 1 + i for i in use.span('arg'))
    fresh = '__repair_address_forward'
    return edit(part.source, [(*decl.span('third'), 's32'), (sig.start('end'), sig.start('end'), f', s32 {fresh}'),
                              (a, b, fresh)])
