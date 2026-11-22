"""Recover a saved zero word reinterpreted as a float for a late update."""

import re
from collections import defaultdict

from .balanced_predicate_projection import _ZERO_UNION, _known_zero
from .clamp_return_local import _field
from .compiler_phase_repairs import fresh
from .goto_structure_repairs import _children, _indent_of, _paths, parse
from .integer_repair_support import IDENT, edit, view
from .local_flow import Flow
from .mips_returns import instructions
from .operand_lifetime_repairs import _visible
from .pattern_repairs import close

FAMILY = 'stored_float_zero'
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|0|[1-9]\d*)'
_FPR = r'\$f[astv]?\d+'
_F32 = r'(?:f32|float)'
_MTC = re.compile(rf'mtc1\s+(\$s[0-7]),\s*({_FPR})')
_ADD = re.compile(rf'add\.s\s+({_FPR}),\s*({_FPR}),\s*({_FPR})')
_STORE = re.compile(rf'swc1\s+({_FPR}),\s*({_NUMBER})\((\$s[0-7])\)')
_INCOMING = re.compile(r'(?:addu\s+(\$s[0-7]),\s*\$a0,\s*\$zero|move\s+(\$s[0-7]),\s*\$a0)')
_ZERO = re.compile(r'(?:addu\s+\$s[0-7],\s*\$zero,\s*\$zero|move\s+\$s[0-7],\s*\$zero)')
_REGISTER_USE = re.compile(r'(\w+)\s+(\$s[0-7])(?:,|$)')
_READS = {'sw', 'sb', 'sh', 'sd', 'swl', 'swr', 'mtc1', 'dmtc1', 'ctc1'}
_BRANCH = re.compile(r'(?:b\w*|j\w*)\b')
_FIELD = re.compile(rf'\*{_F32}\*char\*arg0\+({_NUMBER})')
_STACK_ZERO = re.compile(r'sp[0-9a-fA-F]+=0\.0[fF];')
_ZERO_FLOAT = re.compile(r'\b0\.0[fF]\b')


def _target_fields(asm):
    rows = instructions(asm)
    incoming = {hit[1] or hit[2] for row in rows[:24] if (hit := _INCOMING.fullmatch(row))}
    if len(incoming) != 1:
        return set()
    base = incoming.pop()
    writes = {}
    offsets = set()
    for index, row in enumerate(rows):
        use = _REGISTER_USE.match(row)
        if use and use[1] not in _READS and not _BRANCH.match(row):
            writes.setdefault(use[2], []).append(row)
        transfer = _MTC.fullmatch(row)
        if not transfer:
            continue
        known = writes.get(transfer[1], [])
        if len(known) != 2 or not all(_ZERO.fullmatch(move) for move in known):
            continue
        for i in range(index+1, min(index+7, len(rows))):
            addition = _ADD.fullmatch(rows[i])
            if not addition or transfer[2] not in (addition[2], addition[3]):
                continue
            for following in rows[i+1:i+7]:
                store = _STORE.fullmatch(following)
                if store and store[1] == addition[1] and store[3] == base:
                    offsets.add(int(store[2], 0))
                    break
    return offsets


def _compact(text):
    return re.sub(r'[()\s]', '', text)


def _field_sites(part, paths, offset):
    reset, update = [], []
    for statement, trail in paths:
        if statement.kind != 'simple':
            continue
        line = part.clean[statement.start:statement.end]
        left, equals, right = line.partition('=')
        field = _FIELD.fullmatch(_compact(left))
        if not equals or not field or int(field[1], 0) != offset:
            continue
        literals = list(_ZERO_FLOAT.finditer(right))
        if len(literals) != 1:
            continue
        position = statement.start + len(left) + 1
        site = (statement, trail, (position + literals[0].start(), position + literals[0].end()))
        if _compact(right).lower() == '0.0f;':
            reset.append(site)
        elif re.fullmatch(rf'{_F32}?{re.escape(_compact(left))}\+0\.0[fF];', _compact(right)):
            update.append(site)
    return (reset[0], update[0]) if len(reset) == len(update) == 1 else None


def variants(source, name, asm):
    if not asm or not re.search(r'\bmtc1\s+\$s[0-7]\b', asm):
        return []
    part = view(source, name)
    if not part or re.search(r'\barg0\s*=(?!=)|\bgoto\s*\*|&&\s*\w+\s*;', part.body):
        return []
    if not re.search(rf'\b{re.escape(name)}\s*\(\s*[^,;{{}}()]*\barg0\s*(?:,|\))', part.clean[:part.opening]):
        return []
    offsets = _target_fields(asm)
    if not offsets:
        return []
    body_end = close(part.clean, part.opening, '{', '}')
    if not body_end:
        return []
    try:
        paths = list(_paths(parse(part.clean, part.opening+1, body_end-1)))
    except ValueError:
        return []
    for offset in sorted(offsets):
        sites = _field_sites(part, paths, offset)
        if not sites:
            continue
        (reset, reset_path, reset_zero), (update, update_path, update_zero) = sites
        owner = reset_path[-2][2] if len(reset_path) >= 2 else None
        if owner is None or not any(block['block'] and block['stmts'] is reset_path[-1][0] for block in _children(owner)):
            continue
        parent, update_index, _ = update_path[-1]
        switch_index = next((idx for block, idx, owner in reset_path
                             if block is parent and owner is not None and owner.kind == 'switch'), None)
        if switch_index is None or switch_index >= update_index:
            continue
        anchor = next((stmt for stmt in reversed(parent[max(0, switch_index-20):switch_index])
                       if stmt.kind == 'simple' and _STACK_ZERO.fullmatch(
                           _compact(part.clean[stmt.start:stmt.end]))), None)
        if not anchor or any(stmt.kind == 'case' and anchor.start < stmt.start < update.start for stmt in parent):
            continue
        labels = {stmt.parts['name'] for stmt, _ in paths if stmt.kind == 'label'
                  and anchor.start < stmt.start <= update.start}
        if any(stmt.kind == 'goto' and stmt.parts['target'] in labels
               and not anchor.start < stmt.start < update.start for stmt, _ in paths):
            continue
        carrier = 'repair_saved_zero'
        while re.search(rf'\b{carrier}\b', part.clean):
            carrier += '_'
        edits = [
            (part.opening+1, part.opening+1, f'\n    union {{ unsigned int bits; float number; }} {carrier};'),
            (anchor.start, anchor.start, f'{carrier}.bits = 0;\n{_indent_of(source, anchor.start)}'),
            (reset.start, reset.start, f'{carrier}.bits = 0;\n{_indent_of(source, reset.start)}'),
            (*reset_zero, f'{carrier}.number'),
            (*update_zero, f'{carrier}.number'),
        ]
        return [(FAMILY, edit(source, edits))]
    return []


STACK_WORD = 'stack_vector_zero_word'
_STACK_STORE = re.compile(rf'sw (\$zero|\$fp|\$s[0-7]), ({_NUMBER})\(\$sp\)')
_STACK_ADDR = re.compile(rf'addiu (\$\w+), \$sp, ({_NUMBER})')
_DELAY_CALL = re.compile(rf'jal ({IDENT})')
_RECORD = re.compile(rf'\bstruct\s*\{{(?P<body>[^{{}}]*)\}}\s*(?P<name>{IDENT})\s*;')
_RESET = re.compile(
    rf'(?m)^[ \t]*(?P<lhs>(?P<path>(?P<record>{IDENT})\.(?P<slot>{IDENT}))\.(?P<field>{IDENT}))'
    rf'\s*=\s*(?P<value>0\.0[fF]|{IDENT}\s*\.\s*{IDENT})\s*;\s*'
    rf'(?:if\s*\(\s*)?(?P<call>{IDENT})\(\s*&\s*(?P=path)\.(?P<first>{IDENT})\s*[,)]'
)


def _stack_word_sites(rows):
    aligned = [(target, candidate) for _, target, candidate in rows if target]
    sites = set()
    for i in range(2, len(aligned)):
        target, candidate = map(_STACK_STORE.fullmatch, aligned[i])
        if (not target or not candidate or target[1] != '$zero' or candidate[1] == '$zero'
                or int(target[2], 0) != int(candidate[2], 0)):
            continue
        call, actual = aligned[i - 1]
        match = _DELAY_CALL.fullmatch(call)
        if not match or call != actual:
            continue
        setup, actual = aligned[i - 2]
        moved = re.fullmatch(r'move \$a0, (\$\w+)', setup)
        if setup != actual or not moved:
            continue
        for op, actual in reversed(aligned[max(0, i - 22):i - 2]):
            address = _STACK_ADDR.fullmatch(op)
            if address and address[1] == moved[1] and actual == op:
                offset = int(target[2], 0) - int(address[2], 0)
                if offset in (0, 4, 8):
                    sites.add((match[1], offset // 4))
                break
            if re.match(rf'\w+ {re.escape(moved[1])}(?:,|$)', op):
                break
    return sites


def _stack_vector_layout(part, context, reset):
    records = [m for m in _RECORD.finditer(part.body) if m['name'] == reset['record']]
    if len(records) != 1:
        return None
    record = records[0]
    members = list(re.finditer(rf'\b(?P<type>{IDENT})\s+{reset["slot"]}\s*;', record['body']))
    if len(members) != 1:
        return None
    member = members[0]
    triple = rf'(?:(?:{_F32})\s+{IDENT}\s*;\s*){{3}}'
    records = re.findall(rf'\btypedef\s+struct\s*{{\s*({triple})}}\s*{member["type"]}\s*;', context)
    if len(records) != 1:
        return None
    components = re.findall(rf'{_F32}\s+({IDENT})\s*;', records[0])
    if (components[0] != reset['first'] or len(set(components)) != 3 or reset['field'] not in components):
        return None
    start = part.opening + 1 + record.start('body') + member.start('type')
    end = part.opening + 1 + record.start('body') + member.end('type')
    return start, end, member['type'], components.index(reset['field'])


def stack_word_variants(source, name, rows, *, header='', max_bytes=65536):
    """Use a word view only for a proven positive-zero vector component."""
    sites = _stack_word_sites(rows)
    visible = _visible(source, name, header) if sites else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\s+(?!float\s+f32\b)[^;{}]+\bf32\s*;', context):
        return []
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    choices = []
    for reset in _RESET.finditer(part.clean, part.opening + 1, part.end):
        layout = _stack_vector_layout(part, context, reset)
        if (layout and (reset['call'], layout[3]) in sites
                and not macros & (set(re.findall(IDENT, reset[0])) | {layout[2], 'f32', 'u32', 'value', 'words'})):
            choices.append((reset, layout))
    if len(choices) != 1:
        return []
    reset, (start, end, record_type, component) = choices[0]
    try:
        flow = Flow(part, ())
    except (ValueError, RecursionError):
        return []
    parents = [[] for _ in flow.nodes]
    for index, node in enumerate(flow.nodes):
        for successor in node.successors:
            parents[successor].append(index)
    unions = {m['name']: m for m in _ZERO_UNION.finditer(part.clean, part.opening + 1, part.end)}
    signature = part.clean[:part.opening].rsplit('(', 1)[-1]
    pointers = set(re.findall(rf'(?:void|char)\s*\*\s*({IDENT})', signature)) - macros
    position = next((i for i, node in enumerate(flow.nodes) if node.start <= reset.start('lhs') < node.end), None)
    if position is None or not _known_zero(flow, parents, position, reset['value'], unions, pointers):
        return []
    edits = [
        (start, end, f'union {{ {record_type} value; unsigned int words[3]; }}'),
        (reset.start('lhs'), reset.end('value'), f'{reset["path"]}.words[{component}] = 0'),
    ]
    reference = re.compile(rf'\b{re.escape(reset["record"])}\s*\.\s*{re.escape(reset["slot"])}\b')
    edits.extend((use.end(), use.end(), '.value')
                 for use in reference.finditer(part.clean, end, part.end) if use.start() != reset.start('lhs'))
    candidate = edit(source, edits)
    return [(STACK_WORD, candidate)] if len(candidate.encode()) <= max_bytes else []


DISTINCT_TAIL = 'distinct_zero_store_tail'
_BRANCH_TO = re.compile(
    rf'(?P<prefix>(?:j\s+|bc1[ft]\s+|b(?:eq|ne)z\s+\$\w+,\s+))'
    rf'(?:(?:(?P<symbol>{IDENT})\+)?0x|\.L)(?P<offset>[0-9a-fA-F]+)'
)
_ZERO_SLOT = re.compile(rf'sw \$zero, ({_NUMBER})\(\$\w+\)')
_LABEL_ZERO = re.compile(
    rf'(?m)^[ \t]*(?P<label>{IDENT}):\s*(?P<clear>\*(?P<field>[^;={{}}\n]+)\s*=\s*0\.0[fF]\s*;)'
)


def _merged_zero_offsets(rows, name):
    target = [left for _, left, _ in rows if left]
    actual = [right for _, _, right in rows if right]
    if len(target) != len(actual):
        return set()
    edges = defaultdict(set)
    for _, left, right in rows:
        desired, existing = map(_BRANCH_TO.fullmatch, (left, right))
        if (not desired or not existing or desired['prefix'] != existing['prefix']
                or desired['symbol'] != existing['symbol']
                or (desired['symbol'] and desired['symbol'] != name)):
            continue
        new, old = int(desired['offset'], 16), int(existing['offset'], 16)
        if old < new and new % 4 == old % 4 == 0:
            edges[new // 4, old // 4].add(desired['prefix'])
    offsets = set()
    for (new, old), prefixes in edges.items():
        if (new >= len(target) - 1 or not any(p.startswith('j ') for p in prefixes)
                or not any(p.startswith('bc1') for p in prefixes)):
            continue
        block = target[new:new + 2]
        if block != target[old:old + 2] or block != actual[new:new + 2] or block != actual[old:old + 2]:
            continue
        store = _ZERO_SLOT.fullmatch(block[1])
        if block[0].startswith('j ') and store:
            offset = int(store[1], 0)
            if 0 < offset <= 0x7fff and offset % 4 == 0:
                offsets.add(offset)
    return offsets


def distinct_tail_variants(source, name, rows, *, header='', max_bytes=65536):
    """Try a word view for the labeled positive-zero store shared by the target edges."""
    offsets = _merged_zero_offsets(rows, name)
    visible = _visible(source, name, header) if offsets else None
    if not visible:
        return []
    part, context = visible
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    typedefs = re.findall(r'\btypedef\s+([^;{}]+?)\s+f32\s*;', context)
    if any(alias.strip() != 'float' for alias in typedefs):
        return []
    prefix = part.clean[:part.opening]
    choices = []
    for site in _LABEL_ZERO.finditer(part.clean, part.opening + 1, part.end):
        field = _field('*' + site['field'], prefix)
        if not field or field[1] not in offsets or {field[0], 'f32', site['label']} & macros:
            continue
        jumps = re.findall(rf'\bgoto\s+{site["label"]}\s*;', part.body)
        if len(jumps) < 2:
            continue
        earlier = part.clean[part.opening + 1:site.start()]
        same_slot = re.compile(r'(?m)^[ \t]*(\*[^;={}\n]+)\s*=\s*0\.0[fF]\s*;')
        if any(_field(match[1], prefix) == field for match in same_slot.finditer(earlier)):
            choices.append((site, field))
    if len(choices) != 1:
        return []
    site, (base, offset) = choices[0]
    record = fresh(context, '', 'RepairZeroRecord')
    data = fresh(context, '', 'repair_zero_field')
    bits = fresh(context, '', 'repair_zero_bits')
    padding = fresh(context, '', 'repair_zero_padding')
    number = fresh(context, '', 'repair_zero_number')
    decl = (f'\n    typedef struct {{ unsigned char {padding}[0x{offset:x}]; '
            f'union {{ float {number}; unsigned int {bits}; }} {data}; }} {record};')
    insertion = part.opening + 1
    result = edit(source, [
        (insertion, insertion, decl),
        (*site.span('clear'), f'(({record} *) {base})->{data}.{bits} = 0;'),
    ])
    return [(DISTINCT_TAIL, result)] if len(result.encode()) <= max_bytes else []
