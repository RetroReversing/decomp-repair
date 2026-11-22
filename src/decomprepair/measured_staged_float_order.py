"""Try paired orders for independent float captures and stores on the same base."""

import re
from itertools import permutations

from .call_lifetime_repairs import block_path
from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .operand_lifetime_repairs import _escaped
from .pattern_repairs import close

FAMILY = 'measured_staged_float_order'
_FLOAT = r'(?:f32|float)'
_ADDRESS = rf'\((?P<field_type>{_FLOAT})\s*\*\)\s*\(\(\(char\s*\*\)\s*(?P<base>{IDENT})\)\s*\+\s*(?P<offset>0x[\da-fA-F]+)\)'
_HELPER = re.compile(
    rf'\b(?:inline\s+static|static\s+inline)\s+(?P<type>{_FLOAT})\s+(?P<name>{IDENT})\s*'
    rf'\(\s*(?P=type)\s*\*\s*(?P<field>{IDENT})\s*,\s*(?P=type)\s+(?P<delta>{IDENT})\s*\)\s*'
    r'\{\s*return\s+\*\s*(?P=field)\s*\+\s*(?P=delta)\s*;\s*\}'
)
_CAPTURE = re.compile(
    rf'(?m)^[ \t]*(?P<local>{IDENT})\s*=\s*(?P<helper>{IDENT})\s*\((?P<address>{_ADDRESS}),'
    rf'\s*(?P<delta>{IDENT}(?:\.{IDENT})?)\s*\)\s*;[ \t]*\n'
)
_DIRECT = re.compile(
    rf'(?m)^[ \t]*(?P<local>{IDENT})\s*=\s*\((?P<type>{_FLOAT})\)\s*'
    rf'\(\(\*(?P<address>{_ADDRESS})\)\s*\+\s*(?P<delta>{IDENT}(?:\.{IDENT})?)\)\s*;[ \t]*\n'
)
_STORE = re.compile(rf'(?m)^[ \t]*\*\({_ADDRESS}\)\s*=\s*(?P<local>{IDENT})\s*;[ \t]*\n')
_READ = re.compile(rf'(?m)^[ \t]*(?P<local>{IDENT})\s*=\s*\*(?P<address>{_ADDRESS})\s*;[ \t]*\n')
_DECL = re.compile(rf'(?m)^[ \t]*(?:(?:extern|register)\s+)?{_FLOAT}\s+({IDENT})\s*;')
_ASM_STORE = re.compile(r'swc1 \$f\d+, (0x[\da-f]+)\((\$\w+)\)')
_ASM_LOAD = re.compile(r'lwc1 \$f\d+, (0x[\da-f]+)\((\$\w+)\)')
_GLOBAL_LOAD = re.compile(rf'lwc1 \$f\d+, %lo\(({IDENT})\)\(\$\w+\)')
_EXTERN_FLOAT = re.compile(rf'(?m)^[ \t]*extern\s+(?P<type>{_FLOAT})\s+(?P<name>{IDENT})\s*;')
_WORD_UNION = re.compile(
    rf'(?m)^[ \t]*union\s*\{{\s*(?:s32|u32|int|unsigned\s+int)\s+{IDENT}\s*;'
    rf'\s*(?P<type>{_FLOAT})\s+(?P<member>{IDENT})\s*;\s*}}\s*(?P<name>{IDENT})\s*;'
)


def _swapped_global_loads(rows):
    for index, (kind, target, candidate) in enumerate(rows):
        if kind == ' ':
            continue
        field, global_load = _ASM_LOAD.fullmatch(target), _GLOBAL_LOAD.fullmatch(candidate)
        if not field or not global_load:
            continue
        for _, later_target, later_candidate in rows[index + 1:index + 9]:
            later_global = _GLOBAL_LOAD.fullmatch(later_target)
            later_field = _ASM_LOAD.fullmatch(later_candidate)
            if later_global and later_field and later_global[1] == global_load[1] and later_field.groups() == field.groups():
                yield global_load[1], int(field[1], 16), field[2], index


def _direct_capture(source, hit, kind):
    indent = source[hit.start():hit.start('local')]
    address = source[hit.start('address'):hit.end('address')]
    direct = f"{indent}{hit['local']} = ({kind}) ((*{address}) + {hit['delta']});\n"
    return hit.start(), hit.end(), direct


def _store_edit(source, stores, order):
    reordered = ''.join(source[stores[i].start():stores[i].end()] for i in order)
    return stores[0].start(), stores[-1].end(), reordered


def _target_store_order(rows, index, base, stores):
    positions = {int(hit['offset'], 16): i for i, hit in enumerate(stores)}
    order = []
    for _, target, _ in rows[index:index + 40]:
        if match := _ASM_STORE.fullmatch(target):
            offset = int(match[1], 16)
            if match[2] == base and offset in positions:
                order.append(positions[offset])
                if len(order) == len(stores):
                    break
    if len(set(order)) == len(stores):
        return order
    return []


def _inline_global_candidates(source, captures, stores, rows, helpers, externs, unions, mismatched, macros):
    if len(stores) < 4 or not mismatched.intersection(int(hit['offset'], 16) for hit in stores[:4]):
        return []
    result = []
    by_field = {(hit['delta'], int(hit['offset'], 16)): hit for hit in captures}
    by_local = {hit['local']: hit for hit in captures}
    for delta, offset, base, index in _swapped_global_loads(rows):
        hit = by_field.get((delta, offset))
        if (hit is None or delta in macros or externs.get(delta) != hit['field_type']
                or helpers[hit['helper']] != hit['field_type']):
            continue
        inline = _direct_capture(source, hit, externs[delta])
        result.append((FAMILY, edit(source, [inline])))
        # Keep every capture ahead of the stores. Try bringing the first
        # store after the reordered group forward to fill a transfer delay.
        for prefix in permutations(range(3)):
            order = (3, *prefix, *range(4, len(stores)))
            result.append((FAMILY, edit(source, [inline, _store_edit(source, stores, order)])))
        order = _target_store_order(rows, index, base, stores)
        if not order:
            continue
        terminal = by_local[stores[order[-1]]['local']]
        delta = terminal['delta']
        if (unions.get(delta) != terminal['field_type'] or helpers[terminal['helper']] != terminal['field_type']
                or macros.intersection(delta.split('.'))):
            continue
        terminal_inline = _direct_capture(source, terminal, unions[delta])
        # Leave the terminal store in place. Its word-backed input uses a
        # floating-register transfer, so try the target order and one swap
        # among its earlier stores to give the scheduler room for that transfer.
        orders = [order]
        for first in range(len(order) - 2):
            for second in range(first + 1, len(order) - 1):
                changed = order.copy()
                changed[first], changed[second] = changed[second], changed[first]
                orders.append(changed)
        result.extend((FAMILY, edit(source, [inline, terminal_inline, _store_edit(source, stores, choice)]))
                      for choice in orders)
    return result


def _staged_block(part, start, helpers, *, direct=False):
    captures, stores = [], []
    pos = start
    while len(captures) <= 8:
        hit = _CAPTURE.match(part.clean, pos, part.end)
        if not hit and direct:
            hit = _DIRECT.match(part.clean, pos, part.end)
        if not hit:
            break
        captures.append(hit)
        pos = hit.end()
    while (hit := _STORE.match(part.clean, pos, part.end)) and len(stores) <= 8:
        stores.append(hit)
        pos = hit.end()
    if not 3 <= len(captures) == len(stores) <= 8:
        return None
    if any(('helper' in hit.groupdict() and hit['helper'] not in helpers)
           or ('type' in hit.groupdict() and hit['type'] != hit['field_type'])
           for hit in captures):
        return None
    captured = {(hit['local'], hit['base'], int(hit['offset'], 16)) for hit in captures}
    stored = {(hit['local'], hit['base'], int(hit['offset'], 16)) for hit in stores}
    if (captured != stored or len({base for _, base, _ in captured}) != 1
            or len({local for local, _, _ in captured}) != len(captures)
            or len({offset for _, _, offset in captured}) != len(captures)
            or any(offset % 4 for _, _, offset in captured)):
        return None
    return captures, stores


def _crossed_stack_loads(rows):
    for index, (kind, target, candidate) in enumerate(rows):
        if kind == ' ':
            continue
        field, spill = _ASM_LOAD.fullmatch(target), _ASM_LOAD.fullmatch(candidate)
        if not field or not spill or spill[2] != '$sp' or field[2] == '$sp':
            continue
        for _, a, b in rows[index + 1:index + 9]:
            if (later_spill := _ASM_LOAD.fullmatch(a)) and (later_field := _ASM_LOAD.fullmatch(b)):
                if later_spill.groups() == spill.groups() and later_field.groups() == field.groups():
                    yield int(field[1], 16)
                    break


def _plain_scalar(part, name, kind, at):
    pattern = re.compile(rf'(?m)^[ \t]*(?:register\s+)?{kind}\s+{name}\s*;')
    declarations = list(pattern.finditer(part.clean, part.opening + 1, at))
    if (len(declarations) != 1 or len(re.findall(rf'\b{_FLOAT}\s+{name}\b', part.body)) != 1
            or _escaped(part.body, name)):
        return False
    declaration = declarations[0].start()
    scope = block_path(part, declaration)
    return (part.clean[part.opening:declaration].rstrip()[-1:] in ('{', '}', ';')
            and block_path(part, at)[:len(scope)] == scope)


def _stack_member(part, hit):
    owner, member = hit['delta'].split('.')
    if len(re.findall(rf'\}}\s*{owner}\b', part.body)) != 1:
        return False
    for decl in re.compile(r'(?m)^[ \t]*struct\s*\{').finditer(part.clean, part.opening + 1, hit.start()):
        end = close(part.clean, decl.end() - 1, '{', '}')
        scope = block_path(part, decl.start())
        if (end and re.match(rf'\s*{owner}\s*;', part.clean[end:hit.start()])
                and block_path(part, hit.start())[:len(scope)] == scope):
            return bool(re.search(rf'(?m)^[ \t]*volatile\s+{hit["field_type"]}\s+{member}\s*;',
                                  part.clean[decl.end():end]))
    return False


def _split_staged_capture(source, part, first, helpers, macros, swapped):
    block = _staged_block(part, first.start(), helpers, direct=True)
    if block is None:
        return []
    captures, _ = block
    names = {hit['local'] for hit in captures}
    inputs = {name for hit in captures for name in hit['delta'].split('.')}
    base = first['base']
    if (not any('type' in hit.groupdict() for hit in captures) or names & inputs or macros & inputs
            or _escaped(part.body, base) or re.search(rf'\b{base}\s*=(?!=)', part.body)
            or any(not _plain_scalar(part, hit['local'], hit['field_type'], hit.start()) for hit in captures)
            or any('helper' in hit.groupdict() and helpers[hit['helper']] != hit['field_type'] for hit in captures)):
        return []
    options = []
    for i, (field, stack) in enumerate(zip(captures, captures[1:])):
        # Only a stack-backed member crosses the preceding scalar capture.
        if (int(field['offset'], 16) not in swapped or '.' in field['delta'] or '.' not in stack['delta']
                or not _plain_scalar(part, field['delta'], field['field_type'], field.start())
                or not _stack_member(part, stack)):
            continue
        order = captures[:i] + [stack, field] + captures[i + 2:]
        lines = []
        for hit in order:
            pad = source[hit.start():hit.start('local')]
            address = source[slice(*hit.span('address'))]
            local = hit['local']
            lines.append(f"{pad}{local} = *{address};\n{pad}{local} = ({hit['field_type']}) ({local} + {hit['delta']});\n")
        variant = edit(source, [(captures[0].start(), captures[-1].end(), ''.join(lines))])
        if len(variant.encode()) <= 65536:
            options.append((FAMILY, variant))
    return options


def split_field_updates(part, macros):
    """Read fully staged field additions followed by their disjoint stores."""
    for first in _READ.finditer(part.clean, part.opening + 1, part.end):
        pos = first.start()
        reads, additions, stores = [], [], []
        while len(reads) < 8 and (read := _READ.match(part.clean, pos, part.end)):
            addition = re.compile(rf'(?m)^[ \t]*{read["local"]}\s*=\s*\({read["field_type"]}\)\s*\(\s*'
                                  rf'{read["local"]}\s*\+\s*(?P<delta>{IDENT}(?:\.{IDENT})?)\s*\)\s*;[ \t]*\n')
            found = addition.match(part.clean, read.end(), part.end)
            if not found:
                break
            reads.append(read)
            additions.append(found)
            pos = found.end()
        while len(stores) < 8 and (store := _STORE.match(part.clean, pos, part.end)):
            stores.append(store)
            pos = store.end()
        if not 4 <= len(reads) == len(stores) <= 8 or _STORE.match(part.clean, pos, part.end):
            continue
        offsets = {int(hit['offset'], 16) for hit in stores}
        read_fields, store_fields = [
            {(hit['base'], int(hit['offset'], 16), hit['local'], hit['field_type']) for hit in group}
            for group in (reads, stores)
        ]
        if (len(offsets) != len(stores) or any(offset % 4 for offset in offsets) or read_fields != store_fields
                or len({hit['base'] for hit in stores}) != 1
                or macros & ({first['base']} | {hit['local'] for hit in reads})
                or any(not _plain_scalar(part, hit['local'], hit['field_type'], hit.start()) for hit in reads)):
            continue
        yield reads, additions, stores


def _split_store_order(source, part, mismatched, macros):
    """Keep split reads and adds in place while reordering disjoint stores."""
    for _, _, stores in split_field_updates(part, macros):
        if not mismatched.intersection(int(hit['offset'], 16) for hit in stores):
            continue
        options = []
        for moved in range(1, len(stores) - 1):
            order = list(range(len(stores)))
            order[0], order[moved] = order[moved], order[0]
            options.append((FAMILY, edit(source, [_store_edit(source, stores, order)])))
        return options
    return []


def variants(source, name, rows, header=''):
    rows = list(rows)
    mismatched = set()
    for kind, target, candidate in rows:
        if kind == ' ':
            continue
        a, b = _ASM_STORE.fullmatch(target), _ASM_STORE.fullmatch(candidate)
        if a and b and a[2] == b[2] and a[1] != b[1]:
            mismatched.update((int(a[1], 16), int(b[1], 16)))
    part = view(source, name) if mismatched else None
    if not part:
        return []
    helpers = {match['name']: match['type'] for match in _HELPER.finditer(part.clean, 0, part.opening)}
    combined = _blank(header) + '\n' + part.clean
    declarations = [match[1] for match in _DECL.finditer(combined)]
    externs = {hit['name']: hit['type'] for hit in _EXTERN_FLOAT.finditer(combined)
               if len(re.findall(rf'\b{_FLOAT}\s+{re.escape(hit["name"])}\b', combined)) == 1}
    unions = {f"{hit['name']}.{hit['member']}": hit['type']
              for hit in _WORD_UNION.finditer(part.clean, part.opening, part.end)}
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})', combined))
    if (macros & {'f32', 'float', 'char'} or re.search(r'(?m)^\s*#\s*pragma\s+STDC\s+FENV_ACCESS\s+ON', combined)
            or any(' '.join(alias.split()) != 'float'
                   for alias in re.findall(r'\btypedef\s+([^;{}]+?)\s+f32\s*;', combined))):
        return []
    signature = part.clean[part.clean.rfind('}', 0, part.opening) + 1:part.opening]
    crossed_stack = set(_crossed_stack_loads(rows))
    for first in _CAPTURE.finditer(part.clean, part.opening, part.end):
        if not re.search(rf'[(,]\s*(?:void|char|{_FLOAT})\s*\*\s*{first["base"]}\s*[,)]', signature):
            continue
        block = _staged_block(part, first.start(), helpers)
        if block is None:
            if crossed_stack and not macros & (helpers.keys() | {first['base']}):
                choices = _split_staged_capture(source, part, first, helpers, macros, crossed_stack)
                if choices:
                    return choices
            continue
        captures, stores = block
        capture_prefix, store_prefix = captures[:3], stores[:3]
        local_names = {m['local'] for m in captures}
        deltas = {m['delta'] for m in capture_prefix}
        if (any(declarations.count(var) != 1 for var in local_names)
                or macros & (local_names | helpers.keys() | {first['base']})):
            continue
        result = []
        if externs and not any(re.search(rf'&\s*\(*\s*{re.escape(local)}\b', part.body) for local in local_names):
            result = _inline_global_candidates(source, captures, stores, rows, helpers, externs, unions, mismatched, macros)
        if (not mismatched.intersection(int(m['offset'], 16) for m in store_prefix)
                or any(declarations.count(var) != 1 for var in deltas)
                or local_names & deltas or macros & deltas):
            if result:
                return result
            continue
        # Only the first three captures and stores are permuted. Their fields
        # are disjoint and their deltas are ordinary scalars, so no load crosses
        # a store and none of the captures reads a result of another capture.
        for capture_order in ((0, 1, 2), (0, 2, 1)):
            for store_order in permutations(range(3)):
                if (capture_order, store_order) == ((0, 1, 2), (0, 1, 2)):
                    continue
                changes = [
                    (group[0].start(), group[-1].end(),
                     ''.join(source[group[i].start():group[i].end()] for i in order))
                    for group, order in ((capture_prefix, capture_order), (store_prefix, store_order))
                ]
                result.append((FAMILY, edit(source, changes)))
        return result
    return _split_store_order(source, part, mismatched, macros)
