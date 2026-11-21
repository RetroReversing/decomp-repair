"""Change a source literal when a near-exact MIPS diff identifies its operand."""

import re

from .integer_repair_support import IDENT, calls, edit, integer, split_args, view
from .target_constant_repairs import LITERAL

REG = r'\$\w+'
NUMBER = r'(?:0x[\da-fA-F]+|\d+)'
IMM = re.compile(rf'(addiu|ori|andi)\s+({REG}),\s*({REG}),\s*({NUMBER})')
JAL = re.compile(rf'jal\s+({IDENT})')
BRANCH = re.compile(rf'b(?:eq|ne)z?l?\s+({REG}),\s*')
MEMORY = re.compile(rf'(lb|lbu|lh|lhu|lw|sb|sh|sw)\s+({REG}),\s*(-?{NUMBER})?\(({REG})\)')
WIDTH = {'lb': 1, 'lh': 2, 'lw': 4, 'lbu': 1, 'lhu': 2, 'sb': 1, 'sh': 2, 'sw': 4}
TYPES = {1: r's8|u8|char|signed\s+char|unsigned\s+char',
         2: r's16|u16|short|unsigned\s+short', 4: r's32|u32|int|unsigned\s+int'}


def literal_change(hit, start, old, new):
    if not hit or integer(hit[1]) != old:
        return None
    value = f'0x{new:X}' if hit[1].lower().startswith('0x') else str(new)
    return start+hit.start(), start+hit.end(), value+hit[2]


def direct_call(rows, index, register):
    # A write in a jal delay slot belongs to that call. Else look forward in
    # the same short setup sequence, stopping at transfers or another write.
    if index:
        marker, target, candidate = rows[index-1]
        if marker == ' ' and target == candidate and (jump := JAL.fullmatch(target)):
            return jump[1]
    for marker, target, candidate in rows[index+1:index+5]:
        if marker == ' ' and target == candidate and (jump := JAL.fullmatch(target)):
            return jump[1]
        if any(not text or re.match(r'^[bj]', text)
               or re.match(rf'\S+\s+{re.escape(register)}(?:,|$)', text) for text in (target,candidate)):
            break
    return None


def call_arguments(part, rows, changes):
    bound = {}
    for index, left, right in changes:
        want, have = IMM.fullmatch(left), IMM.fullmatch(right)
        if (not want or not have or want.groups()[:3] != have.groups()[:3]
                or want[1] not in ('addiu','ori') or want[3] != '$zero'
                or not re.fullmatch(r'\$a[0-3]', want[2])):
            return []
        callee = direct_call(rows,index,want[2])
        if callee is None:
            return []
        bound.setdefault(callee,[]).append((int(want[2][-1]), integer(have[4]), integer(want[4])))
    if len(bound) != 1:
        return []
    callee, arguments = next(iter(bound.items()))
    sites = list(calls(part,callee))
    if len(sites) != 1 or len({index for index,_,_ in arguments}) != len(arguments):
        return []
    start,end = sites[0]
    args = split_args(part.clean[start:end])
    edits = []
    for index,old,new in arguments:
        if index >= len(args) or not 0 <= new <= 32767:
            return []
        a,b = args[index]
        arg = part.clean[start+a:start+b]
        hit = LITERAL.fullmatch(arg.strip())
        patch = literal_change(hit, start+a+len(arg)-len(arg.lstrip()), old, new)
        if not patch:
            return []
        edits.append(patch)
    return edits


def branch_mask(part, rows, index, left, right):
    want, have = IMM.fullmatch(left), IMM.fullmatch(right)
    if (not want or not have or want[1] != 'andi' or want.groups()[:3] != have.groups()[:3]
            or index+1 >= len(rows)):
        return []
    marker,target,candidate = rows[index+1]
    branch = BRANCH.match(target)
    if marker != ' ' or target != candidate or not branch or branch[1] != want[2]:
        return []
    mask = re.compile(rf'\(\s*{IDENT}\s*&\s*({LITERAL.pattern})\s*\)')
    edits = []
    for match in mask.finditer(part.clean,part.opening+1,part.end):
        patch = literal_change(LITERAL.fullmatch(match[1]),match.start(1),integer(have[4]),integer(want[4]))
        if patch:
            edits.append(patch)
    return edits if len(edits) == 1 else []


def byte_offset(part, left, right):
    want,have = MEMORY.fullmatch(left),MEMORY.fullmatch(right)
    if (not want or not have or (want[1],want[2],want[4]) != (have[1],have[2],have[4])
            or want[4] in ('$sp','$fp','$s8','$gp')
            or any((match[3] or '').startswith('-') for match in (want,have))):
        return []
    old,new = (integer(match[3] or '0') for match in (have,want))
    if not 0 <= old <= 32767 or not 0 <= new <= 32767:
        return []
    typ = TYPES[WIDTH[want[1]]]
    reads = want[1].startswith('l')
    edits = []
    for start,end in calls(part,'M2C_FIELD'):
        args = split_args(part.clean[start:end])
        if len(args) != 3:
            continue
        x,y = args[1]
        if not re.fullmatch(rf'\s*(?:{typ})\s*\*\s*',part.clean[start+x:start+y]):
            continue
        store = bool(re.match(r'\s*=(?!=)',part.clean[end+1:]))
        if reads == store:
            continue
        x,y = args[2]
        arg = part.clean[start+x:start+y]
        patch = literal_change(LITERAL.fullmatch(arg.strip()),start+x+len(arg)-len(arg.lstrip()),old,new)
        if patch:
            edits.append(patch)
    if reads:
        ptr = re.compile(rf'\*\s*\(\s*(?:{typ})\s*\*\s*\)\s*\(\s*'
                         rf'\(\s*(?:{TYPES[1]})\s*\*\s*\)\s*{IDENT}\s*\+\s*({LITERAL.pattern})\s*\)(?!\s*=(?!=))')
        for match in ptr.finditer(part.clean,part.opening+1,part.end):
            patch = literal_change(LITERAL.fullmatch(match[1]),match.start(1),old,new)
            if patch:
                edits.append(patch)
    return edits if len(edits) == 1 else []


def unsigned_byte_store(part, rows, changes):
    """Use an unsigned byte access when the target materializes the same high-bit byte."""
    immediates = [(i, a, b) for i, a, b in changes if rows[i][0] == 'i']
    if len(immediates) != 1 or any(rows[i][0] not in ('i', 'r') for i, _, _ in changes):
        return None
    index, left, right = immediates[0]
    want = re.fullmatch(rf'addiu ({REG}), \$zero, ({NUMBER})', left)
    have = re.fullmatch(rf'addiu ({REG}), \$zero, -({NUMBER})', right)
    if not want or not have or want[1] != have[1]:
        return None
    value = integer(want[2])
    if not 128 <= value <= 255 or integer(have[2]) != 256 - value:
        return None

    tail = rows[index+1:index+4]
    if len(tail) < 2:
        return None
    high = re.fullmatch(rf'lui ({REG}), %hi\(({IDENT})\)', tail[0][1])
    if not high or high[1] == want[1]:
        return None
    base, symbol = high.groups()
    expected = f'sb {want[1]}, %lo({symbol})({base})'
    store = 2 if tail[1][1] == 'jr $ra' else 1
    if len(tail) <= store or tail[store][1] != expected or any(
        kind != ' ' or a != b for kind, a, b in tail[:store+1]
    ):
        return None

    declaration = rf'(?m)^\s*extern\s+(?:s8|signed\s+char)\s+{symbol}\s*;'
    if not re.search(declaration, part.clean[:part.opening]):
        return None
    assignment = re.compile(rf'(?m)^[ \t]*(?P<name>{symbol})\s*=\s*(?P<value>{NUMBER})\s*;')
    sites = list(assignment.finditer(part.clean, part.opening+1, part.end))
    if (len(sites) != 1 or integer(sites[0]['value']) != value
            or len(re.findall(rf'\b{symbol}\b', part.body)) != 1):
        return None
    return edit(part.source, [(*sites[0].span('name'), f'*(unsigned char *)&{symbol}')])


def variants(source, name, rows):
    changes = [(index, left, right) for index,(marker,left,right) in enumerate(rows) if marker != ' ']
    if (not 1 <= len(changes) <= 2 or not any(rows[i][0] == 'i' for i, _, _ in changes)
            or not (part := view(source,name)) or re.search(r'\b(?:volatile|asm|__asm__)\b',part.body)):
        return []
    if candidate := unsigned_byte_store(part, rows, changes):
        return [('measured_unsigned_byte_store', candidate)]
    if any(rows[i][0] != 'i' or left == right for i,left,right in changes):
        return []
    if patches := call_arguments(part,rows,changes):
        return [('measured_call_literal',edit(source,patches))]
    if len(changes) == 1:
        index,left,right = changes[0]
        if patches := branch_mask(part,rows,index,left,right):
            return [('measured_branch_mask',edit(source,patches))]
        if patches := byte_offset(part,left,right):
            return [('measured_byte_offset',edit(source,patches))]
    return []
