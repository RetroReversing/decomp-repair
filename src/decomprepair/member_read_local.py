"""A stack record's member read through its name many times in one `if`, read from a local copy instead.

m2c keeps a callee's out-parameters in one stack record (`struct { s32 a[4]; void *sp44; } scratch;`, each member's
address passed to the call). A pointer member the code tests and then reads fields through (`if (scratch.sp44 != NULL
&& scratch.sp44->x == 0xB) { ... scratch.sp44->y ... }`) is reloaded from the stack slot at every read; the original
had the pointer in a register (a local assigned from the out-parameter): `lw $a0,0x44($sp)` once, then `0x60($a0)`.
In a 970-instruction N64 state-machine handler (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) the copy was 3390 -> 3120
with the other edits fixed (the loads and stores through the pointer had its register, `$a0`, where ours reloaded
`0x44($sp)`).

`variants` takes a member of a struct local that is read three or more times inside one `if (...) { ... }` statement
and never written or address-taken there, declares `<member>_copy` with the member's type, assigns it from the member
just before the `if`, and reads it in the statement. One child per such member and statement, at most 4. A candidate
rewrite: the exact judge decides.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, block_end, lines

FAMILY = 'member_read_local'
FAMILIES = (FAMILY,)
LIMIT = 4
MINIMUM = 3


def _members(source, clean, part):
    """{(record, member): type} for the struct locals (`struct [tag] { ... } name;`) declared in the body."""
    found = {}
    for record in re.finditer(r'\b(?:struct|union)\b[^{};]*\{(?P<body>[^{}]*)\}\s*(?P<name>[A-Za-z_]\w*)\s*;',
                              clean[part.opening:part.end]):
        for piece in record['body'].split(';'):
            member = re.fullmatch(r'\s*(?P<type>[A-Za-z_][\w\s\*]*?)\s*(?P<name>[A-Za-z_]\w*)\s*', piece)
            if member:
                kind = re.sub(r'\s*\*', ' *', ' '.join(member['type'].split())).replace('* *', '**')
                found[(record['name'], member['name'])] = kind
    return found


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    members = _members(source, part.clean, part)
    out = []
    declarations = []
    for index, line in enumerate(body):
        text = line.stripped
        if not re.match(r'if\s*\(', text):
            continue
        nxt = index + 1
        closing = block_end(body, nxt) if nxt < len(body) and body[nxt].stripped == '{' else None
        if closing is None:
            continue
        span = '\n'.join(item.text for item in body[index:closing + 1])
        for (record, member), kind in members.items():
            access = rf'(?<![\w.>&]){re.escape(record)}\.{re.escape(member)}\b(?!\s*(?:\[|\.))'
            reads = re.findall(access, span)
            if len(reads) < MINIMUM or re.search(rf'&\s*{re.escape(record)}\.{re.escape(member)}\b', span) \
                    or re.search(rf'{access}\s*(?:[-+*/&|^]|<<|>>)?=(?!=)', span):
                continue
            copy = f'{member}_copy'
            if re.search(rf'\b{copy}\b', part.clean):
                continue
            at, end = body[index].start, body[closing].end
            text_in = re.sub(access, copy, source[at:end])
            indent = body[index].indent
            child = apply(source, [(at, end, f'{indent}{copy} = {record}.{member};\n{text_in}')])
            child = _declare(child, name, f'{kind}{copy};' if kind.endswith('*') else f'{kind} {copy};')
            out.append(child)
    return [(FAMILY, child) for child in dict.fromkeys(out)][:LIMIT]


def _declare(source, name, declaration):
    part = view(source, name)
    first = re.search(r'\n', source[part.opening:])
    indent = re.match(r'[ \t]*', source[part.opening + first.end():])[0] or '    '
    at = part.opening + first.end()
    return source[:at] + f'{indent}{declaration}\n' + source[at:]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
