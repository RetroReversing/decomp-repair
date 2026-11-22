"""Sink a guarded counter increment and forward a measured incoming argument."""

import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit, locals_for, view
from .mips import normalized_integer_lines
from .passthrough_argument_repairs import _missing_caller_argument
from .pattern_repairs import close

FAMILIES = ('guarded_counter_increment', 'forwarded_guard_counter')


def variants(source, name, header, rows, asm):
    part = view(source, name)
    context = source + '\n' + header
    if (not part or re.search(r'\b(?:volatile|asm|__asm__|goto|setjmp|longjmp)\b', part.clean)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bu16\s*;', header)):
        return []
    target = [a for _, a, _ in rows if a]
    prior = [b for _, _, b in rows if b]
    target = list(normalized_integer_lines(target))
    prior = list(normalized_integer_lines(prior))
    if not any(re.fullmatch(r'beqz \$v0, \d+', target[i])
               and target[i + 1] == 'addiu $a1, $a1, 1' for i in range(len(target) - 1)):
        return []
    callees = [m[1] for i in range(len(target) - 1)
               if (m := re.fullmatch(rf'jal ({IDENT})', target[i]))
               and target[i + 1] == 'addiu $a1, $a1, -1']
    if len(callees) != 1 or 'addiu $a0, $a0, -1' not in prior:
        return []
    decls = {d['name']: d['type'] for d in locals_for(part)}
    pattern = re.compile(rf'\b(?P<next>{IDENT})\s*=\s*(?P<current>{IDENT})\s*\+\s*1\s*;\s*if\s*\(')
    matches = list(pattern.finditer(part.clean, part.opening + 1, part.end))
    if len(matches) != 1:
        return []
    hit = matches[0]
    next_, current = hit['next'], hit['current']
    if next_ == current or decls.get(next_) != 'u16' or decls.get(current) != 'u16':
        return []
    prefix = part.clean[part.opening + 1:hit.start()].rstrip()
    cond_end = close(part.clean, hit.end() - 1)
    if not cond_end or (prefix and prefix[-1] not in ';{}'):
        return []
    arm = re.match(r'\s*{', part.clean[cond_end:])
    opening = cond_end + arm.end() - 1 if arm else -1
    end = close(part.clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    condition = part.clean[hit.end():cond_end - 1]
    if (re.search(r'\+\+|--|(?<![=!<>])=(?!=)', condition)
            or re.search(rf'\b{re.escape(next_)}\b', condition)
            or re.search(rf'\b{re.escape(next_)}\b', part.clean[end:part.end])
            or not re.search(rf'\b{re.escape(next_)}\b', part.clean[opening + 1:end - 1])
            or any(re.search(rf'&\s*{re.escape(n)}\b', part.body) for n in (next_, current))
            or re.search(r'/[*/]|#', source[hit.start():opening + 1])):
        return []
    calls = set(re.findall(rf'\b({IDENT})\s*\(', condition)) - {'M2C_FIELD'}
    if calls:
        return []
    macros = re.findall(r'(?m)^\s*#\s*define[^\n]*', context)
    if any(re.search(rf'\b{re.escape(n)}\b', line) for n in (next_, current) for line in macros):
        return []
    definitions = re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b[^\n]*', context)
    if definitions and (len(definitions) != 1 or not re.fullmatch(
            r'\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
            r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)\s*', definitions[0])):
        return []
    assign_end = part.clean.find(';', hit.start(), hit.end()) + 1
    statement = source[hit.start():assign_end]
    moved = edit(source, [(hit.start(), assign_end, ''), (opening + 1, opening + 1, '\n        ' + statement)])
    result = [(FAMILIES[0], moved)]
    # The target proves the untouched entry register reaches this call. The
    # existing helper also checks the generated callee prototype and call site.
    span = find(source, name)
    outside = part.clean[:span[0]] + part.clean[span[1]:] if span else part.clean
    if not re.search(rf'\b{re.escape(name)}\s*\(', _blank(header) + outside):
        combined = _missing_caller_argument(moved, name, header, asm, callees[0])
        if combined:
            result.append((FAMILIES[1], combined))
    return result
