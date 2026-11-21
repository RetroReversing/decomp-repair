"""Recover small KMC wrappers when the linked diff exposes a result lifetime."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_BOOL_MASK = re.compile(
    r'addiu \$sp, \$sp, -(?P<frame>\d+)\nsw \$ra, (?P<ra>\d+)\(\$sp\)\n'
    rf'jal (?P<call>{IDENT})\nnop\nsltu \$v1, \$zero, \$v0\nnegu \$v1, \$v1\n'
    r'lw \$ra, (?P=ra)\(\$sp\)\nand \$v0, \$v0, \$v1\njr \$ra\naddiu \$sp, \$sp, (?P=frame)'
)
_BOOL_SOURCE = re.compile(
    rf'\s*s32 (?P<value>{IDENT});\s*(?P=value)\s*=\s*(?P<call>{IDENT})\(\s*\);'
    r'\s*return\s+(?P=value)\s*&\s*(?P<mask>-\(\s*(?P=value)\s*\))\s*;\s*'
)

_COPY = re.compile(
    r'lw \$v1, \(\$a1\)\nmove \$v0, \$a0\nsw \$v1, (?P<first>\d+)\(\$v0\)\n'
    r'lw \$v1, 4\(\$a1\)\nsw \$v1, (?P<second>\d+)\(\$v0\)\n'
    r'lw \$v1, 8\(\$a1\)\njr \$ra\nsw \$v1, (?P<third>\d+)\(\$v0\)'
)
_COPY_SOURCE = re.compile(
    rf'\s*M2C_FIELD\((?P<dst>{IDENT}), s32 \*, (?P<dstoff>{NUMBER})\)\s*=\s*(?:\(s32\)\s*)?'
    rf'M2C_FIELD\((?P<src>{IDENT}), s32 \*, (?P<srcoff>{NUMBER})\)\s*;'
)

_RETURN_ZERO = re.compile(
    r'lw \$ra, (?P<offset>\d+)\(\$sp\)\nmove \$v0, \$zero\njr \$ra\naddiu \$sp, \$sp, \d+$'
)
_STATEMENT_CALL = re.compile(rf'(?P<call>{IDENT})\s*\([0-9a-fA-FxXuU,\s-]*\);')
_FIELD_WRITE = re.compile(
    rf'M2C_FIELD\((?:{IDENT}|M2C_FIELD\(&{IDENT}, void \*\*, {NUMBER}\)), [su](?:8|16) \*, {NUMBER}\)'
    rf'\s*=\s*{NUMBER};'
)

_IO_TARGET = re.compile(
    r'lui \$v0, (?P<hi>\d+)\nori \$v0, \$v0, (?P<lo>\d+)\nlw \$v0, \(\$v0\)\n'
    r'andi \$v0, \$v0, (?P<mask>\d+)\nbeqz \$v0, 36\n'
    r'lui \$v0, %hi\((?P<out>D_[\da-fA-F]{8})\)\nsw \$a0, %lo\((?P=out)\)\(\$v0\)\n'
    rf'j (?P<name>{IDENT})\+40\nmove \$v0, \$zero\naddiu \$v0, \$zero, -1\njr \$ra\nnop'
)
_IO_SOURCE = re.compile(
    rf'\s*if\s*\(\s*\*\(volatile s32 \*\)(?P<read>{NUMBER})\s*&\s*(?P<mask>{NUMBER})\s*\)'
    rf'\s*\{{\s*goto\s+(?P<label>{IDENT});\s*\}}\s*return\s+-1;\s*(?P=label)\s*:\s*\{{\s*'
    rf'(?P<out>D_[\da-fA-F]{{8}})\s*=\s*(?P<arg>{IDENT});\s*return\s+0;\s*\}}\s*'
)


def variants(source, name, header, rows):
    if not 8 <= len(rows) <= 22 or not any(mark != ' ' for mark, _, _ in rows):
        return []
    target = normalized_integer_lines(left for _, left, _ in rows if left)
    trace = '\n'.join(target)
    if (witness := _COPY.fullmatch(trace)) and _missing(rows, 'move $v0, $a0'):
        family, build = 'measured_return_copy_destination', _copy_destination
    elif (witness := _BOOL_MASK.fullmatch(trace)) and _missing(rows, 'sltu $v1, $zero, $v0'):
        family, build = 'measured_unsigned_nonzero_mask', _unsigned_nonzero
    elif (witness := _IO_TARGET.fullmatch(trace)) and any(
        right.startswith('lui $at, %hi(' + witness['out'] + ')') for _, _, right in rows
    ):
        family, build = 'measured_mmio_write_status', _io_write
    elif (witness := _RETURN_ZERO.search(trace)) and any(
        left.startswith(('lui $v0, %hi(', 'lui $v1, %hi(')) and right.startswith('lui $')
        and left.partition(', ')[2] == right.partition(', ')[2] and left != right
        for _, left, right in rows
    ):
        family, build = 'measured_void_wrapper_callees', _void_callees
    else:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    fixed = build(part, name, header, witness, target)
    return [(family, fixed)] if fixed else []


def _missing(rows, op):
    return any(mark != ' ' and ' '.join(left.split()) == op and not right for mark, left, right in rows)


def _copy_destination(part, name, header, target, _ops):
    signature = re.search(
        rf'\b(?P<type>void\s+){re.escape(name)}\s*\(\s*void\s*\*\s*(?P<dst>{IDENT}),'
        rf'\s*void\s*\*\s*(?P<src>{IDENT})\s*\)\s*$', part.clean[:part.opening])
    if not signature or re.search(rf'\b{re.escape(name)}\b', _blank(header) + part.clean[:signature.start()]
                                 + part.clean[part.end:]):
        return None
    stores = list(_COPY_SOURCE.finditer(part.body))
    if len(stores) != 3 or _COPY_SOURCE.sub('', part.body).strip():
        return None
    for store, field, offset in zip(stores, ('first', 'second', 'third'), (0, 4, 8)):
        if (store['src'] != signature['src'] or store['dst'] != signature['dst']
                or integer(store['srcoff']) != offset or integer(store['dstoff']) != int(target[field])):
            return None
    return edit(part.source, [
        (*signature.span('type'), 'void *'),
        (part.end - 1, part.end - 1, f'    return {signature["dst"]};\n'),
    ])


def _unsigned_nonzero(part, name, _header, target, _ops):
    before = _BOOL_SOURCE.fullmatch(part.body)
    if (not before or before['call'] != target['call'] or target['call'] == name
            or not re.search(rf'\bs32\s+{re.escape(name)}\(\s*void\s*\)\s*$', part.clean[:part.opening])):
        return None
    value = before['value']
    start = part.opening + 1
    left, right = before.span('mask')
    return edit(part.source, [(start + left, start + right, f'-((u32){value} > 0)')])


def _void_callees(part, name, header, witness, ops):
    if (ops[0] not in ('addiu $sp, $sp, -24', 'addiu $sp, $sp, -32')
            or f'sw $ra, {witness["offset"]}($sp)' not in ops):
        return None
    body = ' '.join(part.body.split())
    head, _, end = body.rpartition('return 0;')
    if end or not head or not re.search(rf'\bs32\s+{re.escape(name)}\(\s*void\s*\)\s*$', part.clean[:part.opening]):
        return None
    calls = [hit['call'] for hit in _STATEMENT_CALL.finditer(head)]
    target = [op[4:] for op in ops if op.startswith('jal ')]
    if not 1 <= len(calls) <= 3 or calls != target or name in calls:
        return None
    if _FIELD_WRITE.sub('', _STATEMENT_CALL.sub('', head)).strip() or not _FIELD_WRITE.search(head):
        return None
    if not re.search(r'^(?:sb|sh) .*\(\$v[01]\)$', ops[-5]):
        return None
    edits = []
    for callee in dict.fromkeys(calls):
        prototype = re.compile(rf'(?m)^\s*(?:extern\s+)?(?P<type>M2C_UNK)\s+{callee}\s*\([^(){{}}#]*\)\s*;')
        decls = list(prototype.finditer(part.clean, 0, part.opening))
        if not decls or re.search(rf'\b{callee}\b', _blank(header) + part.clean[part.end:]):
            return None
        decl = decls[0]
        # A separately defined or differently declared callee can settle its
        # interface. Only adjust a lone inferred declaration in the draft.
        earlier = part.clean[:decl.start()] + part.clean[decl.end():part.opening]
        if len(decls) != 1 or re.search(rf'\b{callee}\b', earlier):
            return None
        edits.append((*decl.span('type'), 'void'))
    return edit(part.source, edits)


def _io_write(part, name, header, target, _ops):
    local = '__repair_mmio_status'
    body = _IO_SOURCE.fullmatch(part.body)
    sig = re.search(rf'\bs32\s+{re.escape(name)}\(\s*s32\s+({IDENT})\s*\)\s*$', part.clean[:part.opening])
    if (not body or not sig or sig[1] != body['arg'] or name != target['name'] or body['out'] != target['out']
            or local in part.source or local in header):
        return None
    status = integer(body['read'])
    output = int(body['out'][2:], 16)
    mask = integer(body['mask'])
    if (not 0xA0000000 <= status < 0xC0000000 or not 0xA0000000 <= output < 0xC0000000
            or status % 4 or output % 4 or status == output or mask <= 0
            or status != ((int(target['hi']) << 16) | int(target['lo'])) or mask != int(target['mask'])):
        return None
    fixed = f'''
    s32 {local};

    if (*(volatile s32 *){body['read']} & {body['mask']}) {{
        *(volatile s32 *)0x{output:08X} = {body['arg']};
        {local} = 0;
    }} else {{
        {local} = -1;
    }}
    return {local};
'''
    return edit(part.source, [(part.opening + 1, part.end - 1, fixed)])
