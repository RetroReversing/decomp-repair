"""Recover paired 64-bit zero assignments in a measured KMC initializer."""

import re

from .integer_repair_support import IDENT, edit, view

GLOBAL_PAIR = re.compile(
    rf'lui \$at, %hi\((?P<first>{IDENT})\)\nsw \$a0, %lo\((?P=first)\)\(\$at\)\n'
    rf'lui \$at, %hi\((?P<second>{IDENT})\)\nsw \$a1, %lo\((?P=second)\)\(\$at\)'
)
OBJECT_PAIR = re.compile(r'sw \$a0, (?P<offset>0x[0-9a-fA-F]+|[0-9]+)\(\$v0\)\n'
                         r'sw \$a1, (?P<next>0x[0-9a-fA-F]+|[0-9]+)\(\$v0\)')


def variants(source, name, header, rows, *, resolve=None):
    if resolve is None:
        return []
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    pair = GLOBAL_PAIR.search(target)
    if (not pair or 'move $a0, $zero\nmove $a1, $zero' not in target
            or 'move $a0, $zero\nmove $a1, $zero' in candidate):
        return []
    first, second = resolve(pair['first']), resolve(pair['second'])
    if first is None or first % 8 or second != first + 4:
        return []
    offsets = [int(m['offset'], 0) for m in OBJECT_PAIR.finditer(target)
               if int(m['next'], 0) == int(m['offset'], 0) + 4 and int(m['offset'], 0) % 8 == 0]
    if len(offsets) != 2 or len(set(offsets)) != 2:
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    global_stores = re.compile(
        rf'M2C_FIELD\(\s*&\s*(?P<base>{IDENT})\s*,\s*s32\s*\*\s*,\s*'
        rf'(?P<offset>0x[0-9a-fA-F]+|[0-9]+)\s*\)\s*=\s*0\s*;\s*'
        rf'M2C_FIELD\(\s*&\s*(?P=base)\s*,\s*s32\s*\*\s*,\s*'
        rf'(?P<next>0x[0-9a-fA-F]+|[0-9]+)\s*\)\s*=\s*0\s*;'
    )
    globals_ = [m for m in global_stores.finditer(part.body)
                if resolve(m['base']) is not None and resolve(m['base']) + int(m['offset'], 0) == first
                and int(m['next'], 0) == int(m['offset'], 0) + 4]
    if len(globals_) != 1:
        return []
    g = globals_[0]
    store = re.compile(
        rf'\(\(\s*(?P<type>__repair_record_{IDENT})\s*\*\s*\)\s*(?P<ptr>{IDENT})\s*\)\s*'
        rf'->\s*field_(?P<offset>[0-9A-Fa-f]+)\s*=\s*0\s*;\s*'
        rf'\(\(\s*(?P=type)\s*\*\s*\)\s*(?P=ptr)\s*\)\s*'
        rf'->\s*field_(?P<next>[0-9A-Fa-f]+)\s*=\s*0\s*;'
    )
    matches = [m for m in store.finditer(part.body) if int(m['offset'], 16) in offsets
               and int(m['next'], 16) == int(m['offset'], 16) + 4]
    if len(matches) != 2 or len({m['ptr'] for m in matches}) != 1 or len({m['type'] for m in matches}) != 1:
        return []
    record, ptr = matches[0]['type'], matches[0]['ptr']
    load = (f'lui $v0, %hi({ptr})\nlw $v0, %lo({ptr})($v0)')
    if load not in target or load not in candidate:
        return []
    if not re.search(rf'\bextern\s+void\s*\*\s*{re.escape(ptr)}\s*;', part.clean[:part.opening]):
        return []
    definition = re.search(rf'\btypedef\s+struct\s*{{(?P<fields>[^{{}}]+)}}\s*{re.escape(record)}\s*;',
                           part.clean[:part.opening])
    if not definition:
        return []
    fields = re.findall(r'\s*(?:void\s*\*|int\s+)\s*(field_[0-9A-Fa-f]+)\s*;', definition['fields'])
    if not fields or len(re.findall(r';', definition['fields'])) != len(fields):
        return []
    if any(int(field[6:], 16) != 4 * i for i, field in enumerate(fields)):
        return []
    if any(int(m['next'], 16) // 4 >= len(fields) for m in matches):
        return []
    spans = [g, *matches]
    if any('/*' in source[part.opening + 1 + m.start():part.opening + 1 + m.end()]
           or '//' in source[part.opening + 1 + m.start():part.opening + 1 + m.end()] for m in spans):
        return []
    edits = [(part.opening + 1 + g.start(), part.opening + 1 + g.end(),
              f'M2C_FIELD(&{g["base"]}, u64 *, {g["offset"]}) = 0;')]
    edits += [(part.opening + 1 + m.start(), part.opening + 1 + m.end(),
               f'M2C_FIELD({ptr}, u64 *, 0x{m["offset"]}) = 0;') for m in matches]
    return [('measured_zero_record_pairs', edit(source, edits))]
