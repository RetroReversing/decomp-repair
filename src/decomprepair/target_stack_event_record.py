"""Recover a target-proved stack event record from separately named draft fields.

In one KMC GCC 2.7.2 function, three posts all passed `&sp20` while separate draft locals represented the event's
pointer, value and byte. The target writes a halfword at stack offset 0x20, words at +4 and +8, and a byte at +12,
then passes the record address. Grouping those locals as a 16-byte record improved the judge from 10,803 to 10,162.
This repairs an incomplete draft's object layout; it is not equivalent when the separate locals had different
addresses. The target's stack stores and repeated address arguments provide the evidence.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'target_stack_event_record'
FAMILIES = (FAMILY,)
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'


def target_bases(asm):
    lines = [re.sub(r'\s+', ' ', re.sub(r'/\*.*?\*/', '', line).strip()) for line in (asm or '').splitlines()]
    values = []
    for line in lines:
        hit = re.fullmatch(r'addiu \$a1,\s*\$sp,\s*(' + _NUM + r')', line)
        if hit:
            values.append(int(hit[1], 0))
    found = []
    for base in sorted(set(values)):
        if values.count(base) < 2 or base < 16 or base > 128 or base % 4:
            continue
        stores = set()
        for line in lines:
            hit = re.fullmatch(r'(sh|sw|sb) \$\w+,\s*(' + _NUM + r')\(\$sp\)', line)
            if hit:
                stores.add((hit[1], int(hit[2], 0)))
        if all(item in stores for item in (('sh', base), ('sw', base + 4), ('sw', base + 8), ('sb', base + 12))):
            found.append(base)
    return found


def variants(source, name, asm, header=''):
    part = view(source, name)
    macros = source + '\n' + (header or '')
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s16|s32|u8)\s*;|(?m:^\s*#\s*(?:define|undef)\s+(?:s16|s32|u8)\b)', macros):
        return []
    out = []
    for base in target_bases(asm):
        names = [f'sp{value:X}' for value in (base, base + 4, base + 8, base + 12)]
        declarations = []
        for i, local in enumerate(names):
            kind = ('s32', r'void\s*\*', 's32', 'u8')[i]
            pattern = re.compile(r'(?mi)^[ \t]*' + kind + r'\s*' + re.escape(local) + r'\s*;[ \t]*\n')
            matches = list(pattern.finditer(part.clean, part.opening + 1, part.end))
            if len(matches) != 1 or re.search(r'(?mi)^\s*#\s*(?:define|undef)\s+[^\n]*\b' + re.escape(local) + r'\b', macros):
                break
            declarations.append(matches[0])
        if len(declarations) != 4:
            continue
        base_name, pointer, value, channel = [decl.group(0).strip().rstrip(';').split()[-1].lstrip('*') for decl in declarations]
        if any(len(re.findall(r'(?m)(?:^|[;{}])\s*[A-Za-z_]\w*(?:[ \t]+[A-Za-z_]\w*)?[ \t]+\**\s*'
                              + re.escape(local) + r'\s*(?=[;=,\[])', part.body)) != 1
               or re.search(r'(?:\.|->)\s*' + re.escape(local) + r'\b', part.body)
               for local in (base_name, pointer, value, channel)):
            continue
        field_names = (pointer, value, channel)
        body = (r'(?:(?:\s*(?:' + '|'.join(map(re.escape, field_names)) + r')\s*=\s*[^;{}]+;){2,3})')
        pattern = re.compile(r'(?m)^[ \t]*' + re.escape(base_name) + r'\s*=\s*' + _NUM + r'\s*;'
                             + body + r'\s*[A-Za-z_]\w*\s*\([^;{}]*&\s*' + re.escape(base_name) + r'\b[^;{}]*\)\s*;')
        matches = list(pattern.finditer(part.clean, part.opening + 1, part.end))
        if len(matches) < 2:
            continue
        # Every field must occur only in a declaration or a witnessed posting sequence.
        safe = True
        for index, local in enumerate(field_names):
            refs = re.compile(r'\b' + re.escape(local) + r'\b').finditer(part.clean, part.opening, part.end)
            if any(not (declarations[index + 1].start() <= ref.start() < declarations[index + 1].end()
                        or any(hit.start() <= ref.start() < hit.end() for hit in matches)) for ref in refs):
                safe = False
                break
        addresses = list(re.finditer(r'&\s*' + re.escape(base_name) + r'\b', part.clean[part.opening:part.end]))
        if not safe or len(addresses) != len(matches):
            continue
        fresh = 'repair_stack_event'
        while re.search(r'\b' + fresh + r'\b', macros):
            fresh += '_'
        changes = [(decl.start(), decl.end(), '') for decl in declarations[1:]]
        changes.append((part.opening + 1, part.opening + 1,
                        f'\n    struct {{ s16 type; s16 pad; void *ptr; s32 value; u8 chan; u8 tail[3]; }} {fresh};'))
        for hit in matches:
            text = source[hit.start():hit.end()]
            for old, field in ((base_name, 'type'), (pointer, 'ptr'), (value, 'value'), (channel, 'chan')):
                text = re.sub(r'\b' + re.escape(old) + r'\b', fresh + '.' + field, text)
            changes.append((hit.start(), hit.end(), text))
        out.append((FAMILY, edit(source, changes)))
    return out[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
