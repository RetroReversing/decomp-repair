"""Recover a full byte comparison from a measured, single MIPS mask mismatch."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'last_byte_mask'
_REG = r'\$\w+'
_MASK = re.compile(rf'andi ({_REG}), ({_REG}), (0x[0-9a-f]+)')
_GUARD = re.compile(
    rf'\bif\s*\(\s*\(\s*(?P<load>\*\s*\(\s*(?:u8|unsigned\s+char)\s*\*\s*\)'
    rf'\s*\(\s*\(\s*(?:u8|unsigned\s+char)\s*\*\s*\)\s*&\s*{IDENT}\s*\+\s*'
    rf'\(\s*{IDENT}\s*\*\s*(?:0x[0-9a-fA-F]+|[0-9]+)\s*\)\s*\))'
    rf'\s*&\s*0[xX]7[fF][uU]?\s*\)\s*(?P<operator>==|!=)\s*(?P<constant>[0-9]+)\s*\)\s*{{'
)


def residual(rows):
    """Return the matched load, constant, mask and branch only for a single differing instruction."""
    if any(len(row) != 3 for row in rows):
        return ()
    positions = [i for i, (mark, left, right) in enumerate(rows) if mark != ' ' or left != right]
    if len(positions) != 1:
        return ()
    i = positions[0]
    if i < 2 or i + 1 >= len(rows):
        return ()
    mask = _MASK.fullmatch(rows[i][1])
    other = _MASK.fullmatch(rows[i][2])
    if not mask or not other or mask.groups()[:2] != other.groups()[:2]:
        return ()
    if int(mask[3], 16) != 255 or int(other[3], 16) != 127:
        return ()
    dest, source = mask.groups()[:2]
    left, right = (row[1] for row in rows[i-2:i])
    load, immediate = (left, right) if left.startswith('lbu ') else (right, left)
    if not load.startswith(f'lbu {source}, '):
        return ()
    value = re.fullmatch(rf'addiu ({_REG}), \$zero, (\d+|0x[0-9a-f]+)', immediate)
    branch = re.fullmatch(rf'(beq|bne) ({_REG}), ({_REG}), .+', rows[i+1][1])
    if not value or not branch or {branch[2], branch[3]} != {dest, value[1]} or dest == value[1]:
        return ()
    constant = int(value[2], 16 if value[2].startswith('0x') else 10)
    return tuple(tuple(row) for row in rows[i-2:i+2]) if constant < 128 else ()


def variants(source, name, rows, header=''):
    window = residual(rows)
    part = view(source, name) if window else None
    if not part:
        return []
    immediate = next(row[1] for row in window[:2] if row[1].startswith('addiu '))
    literal = immediate.rsplit(' ', 1)[1]
    constant = int(literal, 16 if literal.startswith('0x') else 10)
    matches = [hit for hit in _GUARD.finditer(part.clean, part.opening, part.end)
               if int(hit['constant']) == constant]
    if len(matches) != 1:
        return []
    hit = matches[0]
    text = source[hit.start():hit.end()]
    if re.search(r'/[*/]|\\', text):
        return []
    load = source[slice(*hit.span('load'))]
    pred = f'{hit["operator"]} {constant}'
    begin = source.rfind('\n', 0, hit.start()) + 1
    indent = source[begin:hit.start()]
    if indent.strip():
        return []
    local = 'repair_byte_flag'
    if re.search(rf'\b{local}\b', source + '\n' + header):
        return []
    # Keep declarations at the start of the function for C89 compilers. The
    # judge rejects inline assembly, even an empty register barrier.
    expressions = [f'({load} & 0xffU)', f'(unsigned char)({load})']
    result = [(FAMILY, edit(source, [(*hit.span(), f'if ({expression} {pred}) {{')]))
              for expression in expressions]
    for kind in ('unsigned int', 'volatile unsigned int'):
        replacement = f'{local} = {load};\n{indent}if (({local} & 0xffU) {pred}) {{'
        declaration = f'\n    {kind} {local};'
        result.append((FAMILY, edit(source, [(part.opening + 1, part.opening + 1, declaration),
                                              (*hit.span(), replacement)])))
    return result



def legacy_candidate(source, name, assembly):
    """Recover a narrowly scoped retry lead for old passes without stored rows."""
    instructions = [re.sub(r'\s+', ' ', line.split('*/', 1)[1].strip()).lower()
                    for line in assembly.splitlines() if line.lstrip().startswith('/*') and '*/' in line]
    for index in range(2, len(instructions) - 1):
        if not instructions[index].endswith(', 0xff'):
            continue
        rows = [(' ', text, text) for text in instructions[index-2:index+2]]
        mask = instructions[index]
        rows[2] = ('i', mask, mask[:-4] + '0x7f')
        if variants(source, name, rows):
            return True
    return False
