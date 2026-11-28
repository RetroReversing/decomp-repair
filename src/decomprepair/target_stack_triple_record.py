"""Recover three stack locals passed as one target-proved small record.

One KMC MIPS O2 audio dispatcher stored halfwords at +0 and +2 and a byte at
+4, then passed the base address to its voice initializer. Grouping the three
separately guessed locals as a record made the call's object layout faithful
and improved the linked judge from 15661 to 15571. The target stores and
address argument are required: independent locals are not generally a record.
"""
import re

from .arm_block_support import brace_pairs
from .integer_repair_support import edit, view

FAMILY = 'target_stack_triple_record'


def variants(source, name, asm, header=''):
    part = view(source, name)
    context = source + '\n' + header
    if (not part or re.search(r'\b(?:__LINE__|__COUNTER__)\b', context)
            or re.search(r'\bvolatile\b', part.body)
            or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+(?:s16|s8|u8|first|second|third)\b', context)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s16|s8|u8)\s*;', context)):
        return []
    lines = [' '.join(re.sub(r'/\*.*?\*/', '', line).split()) for line in (asm or '').splitlines()]
    stores = set()
    bases = []
    for line in lines:
        store = re.fullmatch(r'(sh|sb) \$\w+,\s*(0[xX][0-9a-fA-F]+|\d+)\(\$sp\)', line)
        if store:
            stores.add((store[1], int(store[2], 0)))
        address = re.fullmatch(r'addiu \$a1,\s*\$sp,\s*(0[xX][0-9a-fA-F]+|\d+)', line)
        if address:
            bases.append(int(address[1], 0))
    result = []
    for base in dict.fromkeys(bases):
        has_call = any(re.fullmatch(r'addiu \$a1,\s*\$sp,\s*(0[xX][0-9a-fA-F]+|\d+)', line)
                       and int(re.fullmatch(r'addiu \$a1,\s*\$sp,\s*(0[xX][0-9a-fA-F]+|\d+)', line)[1], 0) == base
                       and any(re.match(r'jal\s+\w+', nearby) for nearby in lines[max(0, at - 2):at] + lines[at + 1:at + 3])
                       for at, line in enumerate(lines))
        if not has_call:
            continue
        if base < 16 or base > 128 or base % 4 or not all(x in stores for x in (('sh', base), ('sh', base + 2), ('sb', base + 4))):
            continue
        names = ['sp' + format(base + off, 'X') for off in (0, 2, 4)]
        if any(re.search(r'(?m)^\s*#\s*(?:define|undef)\s+' + re.escape(n) + r'\b', context) for n in names):
            continue
        declarations = []
        for local, kind in zip(names, ('s16', 's16', 's8')):
            matches = list(re.finditer(r'(?m)^[ \t]*' + kind + r'\s+' + re.escape(local) + r'\s*;[^\n]*\n', source[part.opening:part.end]))
            if len(matches) != 1:
                break
            declarations.append((part.opening + matches[0].start(), part.opening + matches[0].end()))
        if len(declarations) != 3:
            continue
        pairs = brace_pairs(part.clean, part.opening, part.end)
        if not pairs:
            continue
        scopes = [max((a for a, b in pairs.items() if a < start < b), default=-1) for start, _ in declarations]
        if len(set(scopes)) != 1 or scopes[0] < 0:
            continue
        scope_start, scope_end = scopes[0], pairs[scopes[0]]
        if any(not scope_start < part.opening + ref.start() < scope_end
               for local in names for ref in re.finditer(r'\b' + re.escape(local) + r'\b', part.clean[part.opening:part.end])):
            continue
        addresses = list(re.finditer(r'&\s*' + re.escape(names[0]) + r'\b', part.body))
        if len(addresses) != 1 or any(re.search(r'&\s*' + re.escape(n) + r'\b', part.body) for n in names[1:]):
            continue
        # All references must be writes or the witnessed base address; no independent local reads.
        safe = True
        for local, (a, b) in zip(names, declarations):
            for ref in re.finditer(r'\b' + re.escape(local) + r'\b', part.clean[part.opening:part.end]):
                start = part.opening + ref.start()
                if a <= start < b or (local == names[0] and re.search(r'&\s*$', part.clean[part.opening:start])):
                    continue
                if not re.match(r'\s*=(?!=)', part.clean[start + len(local):part.end]):
                    safe = False
                    break
            if not safe:
                break
        if not safe:
            continue
        # A signed byte may become unsigned only when all of its writes are zero.
        third_writes = re.findall(r'\b' + re.escape(names[2]) + r'\s*=\s*([^;,)]+)', part.body)
        if not third_writes or any(value.strip() != '0' for value in third_writes):
            continue
        fresh = '__repair_triple'
        if re.search(r'\b' + fresh + r'\b', context):
            continue
        changes = [(a, b, '') for a, b in declarations[1:]]
        changes.append((declarations[0][0], declarations[0][1], '    struct { s16 first; s16 second; u8 third; } ' + fresh + ';\n'))
        for local, field in zip(names, ('first', 'second', 'third')):
            for ref in re.finditer(r'\b' + re.escape(local) + r'\b', part.clean[part.opening:part.end]):
                start = part.opening + ref.start()
                if not any(a <= start < b for a, b in declarations):
                    changes.append((start, start + len(local), fresh + '.' + field))
        result.append((FAMILY, edit(source, changes)))
    return result[:4]


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
