"""The last scalar members of a hand-built frame struct, written as the plain locals gcc spilled to those slots.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) projectile update of 2,503 instructions. Its saved source
keeps every stack slot in one `struct { ... } local;`, the last four members (`sp174`, `sp17C`, `sp184`, `sp18C`, 8
bytes apart) scalars whose address is never taken. The target reaches those four slots only through the reload
register (`sw $t0, 0x174($sp)` / `lw $t0, 0x174($sp)`): they were register locals that global.c gave no register,
and reload's spill slots are 8 bytes apart here. As struct members their loads and stores went through ordinary
pseudos. Written as plain locals after the struct, with the padding before them 8 bytes shorter so the spill slots
start where the members were, the function went 6151 -> 5435 (`frame_struct_unwrap`'s full unwrap: 28188).

frame_tail_spill_unwrap
    For `struct { ... } NAME;` in a function, the trailing run of scalar members (no array, no `struct`) that the body
    never reads as `&NAME.member` (padding arrays named `pad...` between them are dropped) is taken out of the struct
    and declared after it; `NAME.member` becomes `member`. Children: the last one to four such members, each with the
    padding before them unchanged and 4 and 8 bytes shorter. Hypothesis from the match, not from the compiler source:
    spilled pseudos get slots after the frame's locals, in the order reload spills them. The exact judge decides.
"""
import re

FAMILY = 'frame_tail_spill_unwrap'
FAMILIES = (FAMILY,)
LIMIT = 12
REACH = 4

_ID = r'[A-Za-z_]\w*'
_STRUCT = re.compile(rf'(?m)^(?P<indent>[ \t]*)struct \{{[ \t]*\n(?P<body>(?:[^{{}}]*\n)*?)(?P=indent)\}} (?P<name>{_ID});[ \t]*\n')
_MEMBER = re.compile(rf'^(?P<indent>[ \t]*)(?P<type>(?:unsigned |signed )?{_ID}(?:\s*\*+)?)\s*(?P<field>{_ID})'
                     rf'(?P<array>\s*\[\s*(?P<count>\d+)\s*\])?\s*;[ \t]*$')


def _members(body):
    out = []
    for line in body.rstrip('\n').split('\n'):
        found = _MEMBER.match(line)
        if not found or found.group('type').startswith('struct') or found.group('type') == 'union':
            return None
        out.append((line, found))
    return out


def _children(source):
    result = []
    for frame in _STRUCT.finditer(source):
        members = _members(frame.group('body'))
        if not members:
            continue
        name = frame.group('name')
        rest = source[frame.end():]
        tail, k = [], len(members) - 1
        while k >= 0 and len(tail) < REACH:
            line, found = members[k]
            field = found.group('field')
            if found.group('array'):
                if not field.startswith('pad'):
                    break
                k -= 1
                continue
            if re.search(rf'&\s*\(?\s*{re.escape(name)}\.{re.escape(field)}\b', rest):
                break
            tail.append(k)
            k -= 1
        for count in range(1, len(tail) + 1):
            first = tail[count - 1]
            keep = members[:first]
            moved = [members[i] for i in range(first, len(members)) if not members[i][1].group('array')]
            last = keep[-1][1] if keep else None
            pad_at = len(keep) - 1 if last and last.group('array') and last.group('field').startswith('pad') else -1
            if any(re.search(rf'(?<![.\w]){re.escape(found.group("field"))}\b', source[:frame.start()] + rest)
                   for _, found in moved):
                continue
            for shrink in (0, 4, 8):
                lines = [line for line, _ in keep]
                if shrink:
                    if pad_at < 0:
                        continue
                    pad = keep[pad_at][1]
                    size = int(pad.group('count')) - shrink
                    if size <= 0:
                        continue
                    lines[pad_at] = f'{pad.group("indent")}{pad.group("type")} {pad.group("field")}[{size}];'
                indent = frame.group('indent')
                declared = ''.join(f'{indent}{found.group("type").rstrip()} {found.group("field")};\n'
                                   if not found.group('type').endswith('*') else
                                   f'{indent}{found.group("type").rstrip()}{found.group("field")};\n'
                                   for _, found in moved)
                head = (f'{indent}struct {{\n' + ''.join(line + '\n' for line in lines)
                        + f'{indent}}} {name};\n' + declared)
                body = rest
                for _, found in moved:
                    body = re.sub(rf'\b{re.escape(name)}\.{re.escape(found.group("field"))}\b', found.group('field'), body)
                result.append((FAMILY, source[:frame.start()] + head + body))
        break
    return result[:LIMIT]


def variants(source, name):
    return _children(source)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
