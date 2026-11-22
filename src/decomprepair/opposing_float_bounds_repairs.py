"""Stage opposite float distances when the target computes both before a bound check."""

import re

from .goto_structure_repairs import _indent_of, _paths, parse
from .integer_repair_support import IDENT, INTEGER, edit, view
from .mips_returns import instructions
from .pattern_repairs import close

FAMILY = 'opposing_float_bounds'
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|0|[1-9]\d*)'
_F32 = r'(?:f32|float)'
_FPR = r'\$f[astv]?\d+'
_FIELD = re.compile(rf'\*{_F32}\*char\*({IDENT})\+({_NUMBER})')
_LOAD = re.compile(rf'lwc1\s+({_FPR}),\s*({_NUMBER})\((\$\w+)\)')
_SUB = re.compile(rf'sub\.s\s+({_FPR}),\s*({_FPR}),\s*({_FPR})')
_COMPARE = re.compile(rf'c\.le\.s\s+({_FPR}),\s*({_FPR})')
_BOUND = re.compile(r'\s*<=\s*(\d+\.\d+[fF])\s*\)\s*$')
_START = re.compile(r'\s*!\s*\(\s*\(')
_ASSIGN = re.compile(rf'\s*({IDENT})\s*=(?!=)')


def _bound(part, stmt):
    if stmt.kind != 'if':
        return None
    start, stop = stmt.parts['cond']
    begin = _START.match(part.clean[start:stop])
    if not begin:
        return None
    opening = start + begin.end() - 1
    end = close(part.clean, opening)
    limit = _BOUND.fullmatch(part.clean[end:stop]) if end else None
    if not limit:
        return None
    expression = part.clean[opening+1:end-1]
    operands = re.sub(r'[()\s]', '', expression).split('-')
    if len(operands) != 2:
        return None
    for field_at in (0, 1):
        field = _FIELD.fullmatch(operands[field_at])
        center = operands[1-field_at]
        if field and re.fullmatch(IDENT, center):
            return (center, field[1], int(field[2], 0), limit[1], field_at, opening, end)
    return None


def _subtraction(rows, index, field, operand):
    for at in range(index+1, min(index+9, len(rows))):
        if (load := _LOAD.fullmatch(rows[at])) and load[1] == field:
            break
        difference = _SUB.fullmatch(rows[at])
        if difference and difference[2+operand] == field:
            return at, difference[1], difference[3-operand]
    return None


def _target_order(rows, left, right):
    by_offset = {bound[2]: bound for bound in (left, right)}
    for index, row in enumerate(rows):
        first = _LOAD.fullmatch(row)
        if not first or int(first[2], 0) not in by_offset:
            continue
        a = by_offset[int(first[2], 0)]
        b = right if a is left else left
        delta_a = _subtraction(rows, index, first[1], a[4])
        if not delta_a:
            continue
        for at in range(delta_a[0]+1, min(index+11, len(rows))):
            second = _LOAD.fullmatch(rows[at])
            if not second or second[3] != first[3] or int(second[2], 0) != b[2]:
                continue
            delta_b = _subtraction(rows, at, second[1], b[4])
            if not delta_b or delta_b[1] == delta_a[1] or delta_b[2] != delta_a[2]:
                continue
            comparisons = [match[1] for later in rows[delta_b[0]+1:delta_b[0]+35]
                           if (match := _COMPARE.fullmatch(later))]
            if all(delta[1] in comparisons for delta in (delta_a, delta_b)):
                return (a, b)
    return None


def _assignment(part, stmt):
    match = _ASSIGN.match(part.clean[stmt.start:stmt.end]) if stmt.kind == 'simple' else None
    return match[1] if match else None


def variants(source, name, asm):
    part = view(source, name) if asm and 'lwc1' in asm and 'sub.s' in asm else None
    if not part:
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    try:
        paths = list(_paths(parse(part.clean, part.opening+1, end-1)))
    except ValueError:
        return []
    bounds = [(stmt, trail, value) for stmt, trail in paths if (value := _bound(part, stmt))]
    rows = instructions(asm)
    locals_ = set(re.findall(rf'(?m)^[ \t]*(?:{INTEGER}|{_F32})\s+({IDENT})\s*;', part.body))
    for i, (first, left_path, left) in enumerate(bounds):
        parent, index, _ = left_path[-1]
        for second, right_path, right in bounds[i+1:]:
            if (right_path[-1][0] is not parent or left[:2] != right[:2]
                    or left[2] == right[2] or left[3] != right[3] or left[4] == right[4]):
                continue
            center, base = left[:2]
            declaration = re.findall(rf'(?m)^[ \t]*({_F32})\s+{center}\s*;', part.body)
            if len(declaration) != 1:
                continue
            anchor = next((stmt for stmt in reversed(parent[:index]) if _assignment(part, stmt) == center), None)
            if not anchor:
                continue
            between = part.clean[anchor.end:second.start]
            if any(call != 'if' for call in re.findall(rf'\b({IDENT})\s*\(', between)):
                continue
            safe_assignees = locals_ - {center, base}
            if any(stmt.kind in {'label', 'case'} or stmt.kind == 'simple'
                   and _assignment(part, stmt) not in safe_assignees
                   for stmt, _ in paths if anchor.end <= stmt.start < second.start):
                continue
            ordered = _target_order(rows, left, right)
            if not ordered:
                continue
            names = ['repair_upper_delta', 'repair_lower_delta']
            for n, candidate in enumerate(names):
                while re.search(rf'\b{candidate}\b', part.clean):
                    candidate += '_'
                names[n] = candidate
            indentation = _indent_of(source, anchor.start)
            declarations = '\n' + ''.join(f'    {declaration[0]} {label};\n' for label in names)
            initialization = ''.join(f'\n{indentation}{names[bound[4]]} = {source[bound[5]:bound[6]]};'
                                     for bound in ordered)
            changes = [(part.opening+1, part.opening+1, declarations),
                       (anchor.end, anchor.end, initialization),
                       *((bound[5], bound[6], names[bound[4]]) for bound in ordered)]
            return [(FAMILY, edit(source, changes))]
    return []
