"""Pair a measured pointer spill rewrite with nearby C scheduling scopes."""

import re

from .csource import _blank, find

FAMILY = 'measured_kmc_stack_pointer_scope'
_IMM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
_ADDRESS = re.compile(rf'addiu (\$\w+), \$sp, ({_IMM})')
_STORE = re.compile(rf'sw (\$\w+), ({_IMM})\(\$sp\)')
_DECL = re.compile(r'(\w+)(?:\s+(volatile))?\s*(\*)?\s*(volatile\s+)?\s*(\w+)(?:\[(\d+)\])?;')
_WIDTHS = dict(s8=1, u8=1, s16=2, u16=2, s32=4, u32=4, f32=4, float=4, int=4)


def _slot(rows):
    changed = [i for i, (kind, _, _) in enumerate(rows) if kind != ' ']
    if len(changed) != 2 or changed[1] != changed[0] + 1:
        return None
    i, j = changed
    target, candidate = (_ADDRESS.fullmatch(rows[i][side]) for side in (1, 2))
    store, old_store = (_STORE.fullmatch(rows[j][side]) for side in (1, 2))
    if not all((target, candidate, store, old_store)):
        return None
    if (target[1] != store[1] or candidate[1] != old_store[1] or target[1] == candidate[1]
            or target[2] != candidate[2] or store[2] != old_store[2]):
        return None
    accesses = [op for _, op, _ in rows[j + 1:] if op.endswith(f', {store[2]}($sp)')]
    if len(accesses) < 2 or any(not op.startswith('lw ') for op in accesses):
        return None
    return int(target[2], 0), int(store[2], 0), len(accesses)


def _layout(members):
    offset = 0
    fields = {}
    for line in members.splitlines():
        if not line.strip():
            continue
        field = _DECL.fullmatch(line.strip())
        if not field:
            return None
        width = 4 if field[3] else _WIDTHS.get(field[1])
        if not width:
            return None
        offset = (offset + width - 1) // width * width
        fields[field[5]] = (offset, field[1] if not (field[3] or field[6]) else None)
        offset += width * int(field[6] or 1)
    return fields, (offset + 3) // 4 * 4


def variants(source, name, rows):
    """Offer the complete pair so a worse intermediate never needs promotion."""
    slot, span = _slot(rows), find(source, name)
    if not slot or not span:
        return []
    address, spill, reloads = slot
    body = source[span[0]:span[1]]
    clean = _blank(body)
    choices = []
    groups = re.finditer(r'(?ms)^    struct \{\n([^{}]+)^    \} (\w+);', clean)
    for group in groups:
        layout = _layout(group[1])
        if not layout:
            continue
        fields, size = layout
        obj = group[2]
        assignments = re.finditer(rf'(?m)^( +)(\w+) = &{obj}\.(\w+);$', clean[group.end():])
        for assignment in assignments:
            indent, pointer, field = assignment.groups()
            if field not in fields:
                continue
            field_offset, field_type = fields[field]
            gap = spill - (address - field_offset + size)
            decl = re.search(rf'(?m)^    (\w+) \*{pointer};\n', clean[group.end():])
            if not decl or decl[1] != field_type or gap < 0 or gap > 16 or gap % 4:
                continue
            start, end = (group.end() + p for p in assignment.span())
            decl_start, decl_end = (group.end() + p for p in decl.span())
            occurrences = re.findall(rf'\b{pointer}\b', clean)
            if len(occurrences) not in (reloads + 2, reloads + 3):
                continue
            if re.search(rf'\b{pointer}\b', clean[decl_end:start]):
                continue
            tail = body[end:]
            duplicate = re.compile(rf'(?m)^( +)(\w+\([^;\n]*), {pointer}, {pointer}\);$')
            if (len(occurrences) != reloads + 2 + len(duplicate.findall(tail))
                    or re.search(rf'(?:&\s*{pointer}\b|\b{pointer}\s*=)', _blank(tail))):
                continue
            member = 'spillPointer'
            local = 'spillArgument'
            padding = 'spillPadding'
            if any(re.search(rf'\b{word}\b', clean) for word in (member, local, padding)):
                continue
            access = f'{obj}.{member}'
            tail = duplicate.sub(lambda m, ctype=decl[1], local=local, access=access:
                                 f'{m[1]}{{ {ctype} *{local} = {access}; {m[2]}, {local}, {local}); }}', tail)
            tail = re.sub(rf'\b{pointer}\b', access, tail)
            # A pointer reloaded from this record and overwritten before its next use is a short-lived carrier.
            for carrier in re.finditer(rf'(?m)^{indent}void \*(\w+) = {obj}\.\w+;', clean[:start]):
                var = carrier[1]
                if re.search(rf'&\s*{var}\b', clean):
                    continue
                next_use = re.search(rf'\b{var}\b', _blank(tail))
                if not next_use:
                    continue
                line_start = tail.rfind('\n', 0, next_use.start()) + 1
                if not re.match(rf'{indent}{var}\s*=\s*{obj}\.\w+;', tail[line_start:]):
                    continue
                prefix = body[:decl_start] + body[decl_end:start]
                member_at = group.end(1)
                pad = f'        unsigned int {padding}[{gap // 4}];\n' if gap else ''
                prefix = (prefix[:member_at] + pad + f'        {decl[1]} * volatile {member};\n'
                          + prefix[member_at:])
                staged = f'{indent}{var} = &{obj}.{field}; {access} = {var};'
                lines = prefix.splitlines(keepends=True)
                # Closing a scope after a nearby call changes scheduling and allocation together.
                for stop in range(len(lines) - 1, max(-1, len(lines) - 36), -1):
                    if not re.fullmatch(rf'{indent}\w+\([^;{{}}]*\);\n', lines[stop]):
                        continue
                    for count in (5, 4, 6, 3, 7, 8, 2):
                        first = stop + 1 - count
                        if first < 0:
                            continue
                        block = lines[first:stop + 1]
                        if not all(re.fullmatch(rf'{indent}\S[^;{{}}]*;\n', line) for line in block):
                            continue
                        if any(re.match(rf'{indent}(?:\w+\s+\*?\w+\s*=|goto |return |break\b|continue\b)',
                                        line) for line in block):
                            continue
                        scoped = (''.join(lines[:first]) + indent + 'do {\n'
                                  + ''.join('    ' + line for line in block)
                                  + indent + '} while (0);\n' + ''.join(lines[stop + 1:]))
                        choices.append((FAMILY, source[:span[0]] + scoped + staged + tail + source[span[1]:]))
                        if len(choices) == 32:
                            return choices
    return choices
