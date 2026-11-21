"""Recover byte-width operations corroborated by a linked KMC instruction diff."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TABLE = re.compile(
    rf'lui (?P<base>\$\w+), %hi\((?P<symbol>{IDENT})\)\n'
    r'addu (?P=base), (?P=base), (?P<index>\$\w+)\n(?:(?:jal|jr) [^\n]+\n)?'
    r'lbu \$\w+, %lo\((?P=symbol)\)\((?P=base)\)'
)
_TEST = re.compile(
    rf'lui \$v1, %hi\((?P<gate>{IDENT})\)\nlbu \$v1, %lo\((?P=gate)\)\(\$v1\)\n'
    r'addiu \$v0, \$zero, (?P<mode>\d+)\nbne \$v1, \$v0, 44\naddiu \$a1, \$zero, 1\n'
    rf'lui \$v0, %hi\((?P<status>{IDENT})\)\nlh \$v0, %lo\((?P=status)\)\(\$v0\)\n'
    r'sltu \$v0, \$zero, \$v0\nandi \$v1, \$a0, 255\nslt \$v0, \$v0, \$v1\n'
    r'xori \$a1, \$v0, 1\njr \$ra\nandi \$v0, \$a1, 255'
)
_TEST_SOURCE = re.compile(
    rf'\s*s32 (?P<result>{IDENT});\s*(?P=result) = 1;\s*if \((?P<gate>{IDENT}) == (?P<mode>{NUMBER})\) '
    rf'\{{\s*(?P=result) = (?P<status>\({IDENT}\)) >= \((?P<arg>{IDENT}) & 0xFF\);\s*\}}'
    r'\s*return (?P=result) & 0xFF;\s*'
)
_FLAGS = re.compile(
    rf'lui \$v1, %hi\((?P<base>{IDENT})\)\nlw \$v1, %lo\((?P=base)\)\(\$v1\)\n'
    rf'lbu \$(?P<reg>a[12]), (?P<offset>\d+)\(\$v1\)\nmove \$s0, \$v0\nmove \$a0, \$s0\n'
    r'(?P<op>andi|ori) \$(?P=reg), \$(?P=reg), (?P<value>\d+)\n'
    rf'(?:move \$a1, \$a2\n)?jal (?P<call>{IDENT})\nsb \$(?P=reg), (?P=offset)\(\$v1\)'
)
_FLAG_SOURCE = re.compile(
    rf'\b(?P<value>{IDENT}) = M2C_FIELD\((?P<base>{IDENT}), u8 \*, (?P<offset>{NUMBER})\)'
    r' (?P<op>[&|]) (?P<mask>' + NUMBER + r');\s+'
    rf'M2C_FIELD\((?P=base), u8 \*, (?P=offset)\) = (?P=value);\s+'
    rf'(?P<call>{IDENT})\({IDENT}, (?P=value)\);'
)

_CLAMP_TARGET = re.compile(
    r'addiu \$sp, \$sp, -24\nandi \$v0, \$a0, 65535\nsltiu \$v0, \$v0, (?P<width>\d+)\n'
    r'bnez \$v0, 24\nsw \$ra, 16\(\$sp\)\naddiu \$a0, \$zero, (?P<col>\d+)\n'
    r'andi \$v0, \$a1, 65535\nsltiu \$v0, \$v0, (?P<height>\d+)\n'
    r'beql \$v0, \$zero, 40\naddiu \$a1, \$zero, (?P<row>\d+)\n'
    r'andi \$v0, \$a1, 65535\nsll \$v1, \$v0, (?P<lead>\d+)\naddu \$v1, \$v1, \$v0\n'
    r'sll \$v1, \$v1, (?P<tail>\d+)\naddu \$a0, \$a0, \$v1\nandi \$v0, \$a0, 65535\n'
    rf'lui \$a0, %hi\((?P<table>{IDENT})\)\naddu \$a0, \$a0, \$v0\njal (?P<call>{IDENT})\n'
    r'lbu \$a0, %lo\((?P=table)\)\(\$a0\)\nlw \$ra, 16\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 24'
)
_CLAMP_SOURCE = re.compile(
    rf'\s*s32 (?P<col>{IDENT});\s*s32 (?P<row>{IDENT});\s*(?P=col) = (?P<a>{IDENT});\s*(?P=row) = (?P<b>{IDENT});'
    rf'\s*if \(\(u32\) \((?P=col) & 0xFFFF\) >= (?P<width>{NUMBER})\) \{{\s*(?P=col) = (?P<x>{NUMBER});\s*\}}'
    rf'\s*if \(\(u32\) \((?P=row) & 0xFFFF\) >= (?P<height>{NUMBER})\) \{{\s*(?P=row) = (?P<y>{NUMBER});\s*\}}'
    rf'\s*(?P<call>{IDENT})\(\*\(&(?P<table>{IDENT}) \+ \(\((?P=col) \+ \(\((?P=row) & 0xFFFF\) \*'
    rf' (?P<stride>{NUMBER})\)\) & 0xFFFF\)\), (?P=row)\);\s*'
)

_SHARED_BUFFER = re.compile(
    r'sll \$s1, \$s2, (?P<lead>\d+)\naddu \$s1, \$s1, \$s2\nsll \$s1, \$s1, (?P<shift>\d+)\n'
    rf'lui \$s0, %hi\((?P<base>{IDENT})\)\naddiu \$s0, \$s0, %lo\((?P=base)\)\nmove \$a0, \$s2\n'
    rf'jal (?P<prepare>{IDENT})\naddu \$a1, \$s1, \$s0\naddiu \$s0, \$s0, -(?P<delta>\d+)\n'
    rf'lui \$a0, %hi\((?P<table>{IDENT})\)\naddu \$a0, \$a0, \$s2\nlbu \$a0, %lo\((?P=table)\)\(\$a0\)\n'
    rf'addu \$a1, \$s1, \$s0\njal (?P<consume>{IDENT})\naddiu \$a2, \$zero, (?P<length>\d+)'
)


def variants(source, name, header, rows, resolve=None):
    if not 12 <= len(rows) <= 30 or not any(mark != ' ' for mark, _, _ in rows):
        return []
    ops = ['\n'.join(normalized_integer_lines(row[side] for row in rows if row[side])) for side in (1, 2)]
    target, candidate = ops
    table, old_table = _TABLE.search(target), _TABLE.search(candidate)
    flags, old_flags = _FLAGS.search(target), _FLAGS.search(candidate)
    clamp = None
    if table and old_table and resolve and _word_scale(rows, table, old_table, resolve):
        clamp = _CLAMP_TARGET.fullmatch(target)
        family, build, witness = 'measured_byte_table_index', _table_index, table
    elif flags and old_flags and _flag_registers(flags, old_flags, candidate):
        family, build, witness = 'measured_word_flag_argument', _word_flags, flags
    elif (status := _TEST.fullmatch(target)) and any(
        ' '.join(left.split()) == 'sltu $v0, $zero, $v0' and not right for _, left, right in rows
    ):
        family, build, witness = 'measured_halfword_status_test', _status_test, status
    else:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    if clamp and (fixed := _clamped_index(part, name, clamp)):
        return [('measured_clamped_byte_index', fixed)]
    fixed = build(part, name, header, rows, witness)
    return [(family, fixed)] if fixed else []


def _word_scale(rows, target, candidate, resolve):
    start, wrong = resolve(target['symbol']), resolve(candidate['symbol'])
    if start is None or wrong is None or wrong != start + 3:
        return False
    shift = re.compile(rf'sll {re.escape(candidate["index"])}, \$\w+, 2')
    return any(not left and shift.fullmatch(op) for left, op in zip(
        (row[1] for row in rows), normalized_integer_lines(row[2] for row in rows)))


def _table_index(part, _name, header, rows, target):
    symbol = target['symbol']
    access = list(re.finditer(rf'\*\(\s*&{symbol}\s*\+\s*', part.body))
    if len(access) != 1 or not re.search(
        rf'(?m)^\s*extern\s+(?:M2C_UNK|s32|u32)\s+{symbol}\s*;', part.clean[:part.opening]
    ):
        return None
    start = part.opening + 1 + access[0].start()
    edge = part.opening + 1 + access[0].end()
    end = close(part.clean, start + 1)
    if not end or not edge < end <= part.end or re.search(r'[;{}]', part.clean[edge:end - 1]):
        return None
    index = part.source[edge:end - 1]
    changes = [(start, end, f'((u8 *)&{symbol})[{index}]')]
    if buffer := _scaled_buffer(part, header, rows, end, index):
        changes.append((*buffer.span('type'), 'u8'))
    else:
        changes.extend(_shared_buffer_casts(part, rows, start, end, index, symbol))
    return edit(part.source, changes)


def _scaled_buffer(part, header, rows, after, index):
    if not re.fullmatch(IDENT, index):
        return None
    # The same mistaken word width can scale a neighboring call argument.
    aligned = list(zip(*(normalized_integer_lines(row[side] for row in rows) for side in (1, 2))))
    if not any((match := re.fullmatch(r'sll \$a1, \$a1, (\d+)', a))
               and b == f'sll $a1, $a1, {int(match[1]) + 2}' for a, b in aligned):
        return None
    expression = re.match(rf'\s*,\s*\({index}\s*\*\s*(?P<stride>{NUMBER})\)\s*\+\s*&(?P<base>{IDENT})'
                          rf'\s*,\s*(?P<length>{NUMBER})\s*\)', part.clean[after:part.end])
    if not expression or integer(expression['stride']) != integer(expression['length']):
        return None
    base = expression['base']
    if re.search(rf'\b{base}\b', _blank(header) + part.clean[part.end:]) or len(
        re.findall(rf'\b{base}\b', part.clean)
    ) != 2:
        return None
    if not any(a == b == f'lui $v0, %hi({base})' for a, b in aligned) or not any(
        a == b == f'addiu $a2, $zero, {integer(expression["length"])}'
        for a, b in aligned
    ):
        return None
    return re.search(rf'(?m)^\s*extern\s+(?P<type>M2C_UNK|s32|u32)\s+{base}\s*;', part.clean[:part.opening])


def _shared_buffer_casts(part, rows, before, after, index, table):
    if not re.fullmatch(IDENT, index):
        return []
    aligned = list(zip(*(normalized_integer_lines(row[side] for row in rows) for side in (1, 2))))
    trace = '\n'.join(left for left, _ in aligned if left)
    if not (target := _SHARED_BUFFER.search(trace)) or target['table'] != table:
        return []
    base, prepare, consume = (target[k] for k in ('base', 'prepare', 'consume'))
    shift, lead, delta, width = (int(target[k]) for k in ('shift', 'lead', 'delta', 'length'))
    if not (0 < lead < 8 and 0 < shift < 8 and 0 < delta <= 8191 and base != table
            and width == (((1 << lead) + 1) << shift)):
        return []
    prior_shift = re.compile(rf'sll (\$s[0-7]), \1, {shift + 2}')
    prior_delta = re.compile(rf'addiu (\$s[0-7]), \1, -{delta * 4}')
    if not any(left == f'sll $s1, $s1, {shift}' and prior_shift.fullmatch(right) for left, right in aligned):
        return []
    if not any(left == f'addiu $s0, $s0, -{delta}' and prior_delta.fullmatch(right) for left, right in aligned):
        return []
    if not re.search(rf'(?m)^\s*extern\s+(?:M2C_UNK|s32|u32)\s+{base}\s*;', part.clean[:part.opening]):
        return []
    lead_source = re.search(
        rf'\b(?P<stride>{IDENT})\s*=\s*{index}\s*\*\s*(?P<width>{NUMBER});\s*'
        rf'{prepare}\({index},\s*(?P=stride)\s*\+\s*(?P<first>&{base})\);\s*{consume}\(\s*$',
        part.clean[part.opening + 1:before],
    )
    if not lead_source or integer(lead_source['width']) != width:
        return []
    stride = lead_source['stride']
    tail_source = re.match(
        rf',\s*{stride}\s*\+\s*\((?P<second>&{base})\s*-\s*(?P<delta>{NUMBER})\),\s*(?P<width>{NUMBER})\);',
        part.clean[after:part.end],
    )
    if not tail_source or integer(tail_source['delta']) != delta or integer(tail_source['width']) != width:
        return []
    return [
        (part.opening + 1 + lead_source.start('first'), part.opening + 1 + lead_source.start('first'), '(u8 *)'),
        (after + tail_source.start('second'), after + tail_source.start('second'), '(u8 *)'),
    ]


def _flag_registers(target, candidate, trace):
    return (target['reg'] == 'a1' and candidate['reg'] == 'a2'
            and all(target[key] == candidate[key] for key in ('offset', 'op', 'value', 'call', 'base'))
            and 'move $a1, $a2\njal ' + candidate['call'] in trace)


def _word_flags(part, _name, _header, _rows, target):
    hit = _FLAG_SOURCE.search(part.body)
    if not hit or hit['call'] != target['call'] or hit['base'] != target['base'] or integer(hit['offset']) != int(target['offset']):
        return None
    mask = integer(hit['mask'])
    if mask != int(target['value']) or (target['op'] == 'andi') != (hit['op'] == '&') or mask > 255:
        return None
    value = hit['value']
    if len(re.findall(rf'\b{value}\b', part.body)) != 4:
        return None
    declaration = re.search(rf'\bu8(?=\s+{value}\s*;)', part.body[:hit.start()])
    if not declaration:
        return None
    start = part.opening + 1
    return edit(part.source, [(start + declaration.start(), start + declaration.end(), 's32')])


def _status_test(part, name, header, _rows, target):
    helper = '__repair_halfword_nonzero'
    signature = re.search(rf'\bs32\s+{re.escape(name)}\(s32 ({IDENT})\)\s*$', part.clean[:part.opening])
    source = _TEST_SOURCE.fullmatch(part.body)
    if not source or not signature or source['arg'] != signature[1] or helper in part.source or helper in header:
        return None
    status = target['status']
    if source['status'] != f'({status})' or source['gate'] != target['gate'] or integer(source['mode']) != int(target['mode']):
        return None
    if not re.search(rf'\bextern\s+s16\s+{status}\s*;', part.clean[:part.opening]):
        return None
    start = part.opening + 1
    return edit(part.source, [
        (signature.start(), signature.start(), f'static inline s32 {helper}(s16 value) {{ return value != 0; }}\n'),
        (start + source.start('status'), start + source.end('status'), f'({helper}({status}))'),
    ])


def _clamped_index(part, name, target):
    source = _CLAMP_SOURCE.fullmatch(part.body)
    signature = re.search(
        rf'\bvoid\s+{re.escape(name)}\(s32 ({IDENT}), s32 ({IDENT})\)\s*$', part.clean[:part.opening])
    if (not source or not signature or signature.groups() != (source['a'], source['b'])
            or source['call'] != target['call'] or source['call'] == name or source['table'] != target['table']):
        return None
    if len({source[key] for key in ('a', 'b', 'col', 'row', 'table', 'call')}) != 6:
        return None
    width, height, x, y, stride = (integer(source[key]) for key in ('width', 'height', 'x', 'y', 'stride'))
    lead, tail = int(target['lead']), int(target['tail'])
    if (not 0 < lead < 16 or not 0 < tail < 16 or stride != (((1 << lead) + 1) << tail)
            or (width, height, x, y) != tuple(int(target[key]) for key in ('width', 'height', 'col', 'row'))
            or not 0 <= x < width <= 65535 or not 0 <= y < height <= 65535
            or (height - 1) * stride >= 2**31 - 65535):
        return None
    col, arg, row = source['col'], source['a'], source['b']
    fixed = f"""
    u16 {col} = {arg};

    if ({col} >= {width}) {{
        {col} = {x};
    }}
    if ((u16){row} >= {height}) {{
        {row} = {y};
    }}
    {col} += (u16){row} * {stride};
    {source['call']}(((u8 *)&{source['table']})[{col}], {row});
"""
    return edit(part.source, [(part.opening + 1, part.end - 1, fixed)])
