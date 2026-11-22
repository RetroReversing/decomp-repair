"""Join a free-list return and a fallback walk around one saved result."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, locals_for, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_list_selection'


def variants(source, name, header, rows):
    part = view(source, name)
    context = source + '\n' + header
    if (not part or re.search(r'\b(?:volatile|goto|asm|__asm__|setjmp|longjmp)\b', part.clean)
            or re.search(r'\b(?:static|extern|_Thread_local)\b', part.body)
            or re.search(rf'\b(?:void|s32|u32|int|char)\s+\**\s*{IDENT}\s*\([^;{{}}]*\)\s*\{{', part.body)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bs32\s*;', header)):
        return []
    lines = [normalized_integer_lines((a, b)) for _, a, b in rows]
    # A target-only callee-saved flag survives the calls; the draft returns a
    # literal and uses a caller-saved flag only on the later path.
    prior = {b for _, b in lines if b}
    saved = [m[1] for a, _ in lines if a not in prior and (m := re.fullmatch(r'sw (\$s[0-7]), \d+\(\$sp\)', a))]
    if len(saved) != 1 or not any(a == f'move {saved[0]}, $zero' and b == 'move $a3, $zero' for a, b in lines):
        return []
    if not any(a == f'move $v0, {saved[0]}' and b == 'move $v0, $zero' for a, b in lines):
        return []
    start_pattern = re.compile(
        rf'(?P<first>{IDENT})\s*=\s*M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*void\s*\*\*\s*,\s*{NUMBER}\s*\)\s*;\s*'
        rf'(?P<flag>{IDENT})\s*=\s*0\s*;\s*if\s*\(')
    starts = []
    for candidate in start_pattern.finditer(part.clean, part.opening + 1, part.end):
        finish = close(part.clean, candidate.end() - 1)
        brace = re.match(r'\s*{', part.clean[finish:]) if finish else None
        arm_start = finish + brace.end() - 1 if brace else -1
        arm_end = close(part.clean, arm_start, '{', '}') if arm_start >= 0 else None
        if arm_end and re.search(r'\breturn\s+0\s*;\s*$', part.clean[arm_start + 1:arm_end - 1]):
            starts.append(candidate)
    if len(starts) != 1:
        return []
    start = starts[0]
    cond_end = close(part.clean, start.end() - 1)
    arm = re.match(r'\s*{', part.clean[cond_end:]) if cond_end else None
    opening = cond_end + arm.end() - 1 if arm else -1
    end = close(part.clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    first, flag, base = (start[k] for k in ('first', 'flag', 'base'))
    arm_body = part.clean[opening + 1:end - 1]
    early = re.search(r'\breturn\s+0\s*;\s*$', arm_body)
    if (not early or re.search(r'\b(?:return|break|continue)\b|[{}]', arm_body[:early.start()])
            or re.search(rf'\b{re.escape(flag)}\b', part.clean[start.end():end])):
        return []
    fallback = re.match(
        rf'\s*(?P<cursor>{IDENT})\s*=\s*M2C_FIELD\(\s*{re.escape(base)}\s*,\s*void\s*\*\*\s*,\s*{NUMBER}\s*\)\s*;\s*'
        rf'(?P<result>{IDENT})\s*=\s*0\s*;\s*if\s*\(\s*(?P=cursor)\s*!=\s*NULL\s*\)\s*{{\s*do\s*{{', part.clean[end:])
    if not fallback:
        return []
    cursor, result = fallback['cursor'], fallback['result']
    if len({first, flag, cursor, result, base}) != 5:
        return []
    do_open = end + fallback.end() - 1
    do_end = close(part.clean, do_open, '{', '}')
    tail = re.match(rf'\s*while\s*\(\s*{re.escape(cursor)}\s*!=\s*NULL\s*\)\s*;\s*}}\s*'
                    rf'(?P<return>return\s+{re.escape(result)}\s*;)', part.clean[do_end:]) if do_end else None
    if not tail:
        return []
    loop = part.clean[do_open + 1:do_end - 1]
    copy = re.search(rf'\b{re.escape(result)}\s*=\s*{re.escape(flag)}\s*;\s*$', loop)
    if (not copy or re.search(r'\b(?:return|break|continue|case|default)\b', loop)
            or len(re.findall(rf'\b{re.escape(result)}\b', part.body)) != 4
            or re.search(rf'\b{re.escape(first)}\b', part.clean[end:part.end])
            or any(re.search(rf'&\s*{re.escape(n)}\b', part.body) for n in (first, flag, cursor, result))):
        return []
    decls = {d['name']: d['type'] for d in locals_for(part)}
    if (decls.get(flag) != 's32' or decls.get(result) != 's32'
            or any(len(re.findall(rf'\bvoid\s*\*\s*{re.escape(n)}\s*;', part.body)) != 1 for n in (first, cursor))
            or any(re.search(rf'\bconst\s+void\s*\*\s*{re.escape(n)}\b', part.body)
                   for n in (first, cursor))):
        return []
    macros = re.findall(r'(?m)^\s*#\s*define[^\n]*', context)
    if any(re.search(rf'\b{re.escape(n)}\b', line) for n in (first, flag, cursor, result, base) for line in macros):
        return []
    definitions = re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b[^\n]*', context)
    if (len(definitions) != 1 or not re.fullmatch(
            r'\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
            r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)\s*', definitions[0])
            or re.search(r'/[*/]|#', source[opening + 1:end - 1] + source[end:do_end + tail.end()])):
        return []
    earlier = part.clean[part.opening + 1:start.start()].rstrip()
    if earlier and earlier[-1] not in ';{}':
        return []
    first_return = opening + 1 + early.start()
    loop_copy_start = do_open + 1 + copy.start()
    loop_copy_end = do_open + 1 + copy.end()
    fallback_end = do_end + tail.end()
    section = source[end:fallback_end]
    replacements = [(fallback.start('result'), fallback.end('result'), flag),
                    (loop_copy_start - end, loop_copy_end - end, ''),
                    (do_end + tail.start('return') - end, do_end + tail.end('return') - end, f'return {flag};')]
    # Remove the fallback's redundant zero initialization; the flag was initialized before the first branch.
    result_start = end + fallback.start('result')
    result_end = part.clean.find(';', result_start) + 1
    replacements[0] = (result_start - end, result_end - end, '')
    for a, b, text in sorted(replacements, reverse=True):
        section = section[:a] + text + section[b:]
    section = re.sub(rf'\b{re.escape(cursor)}\b', first, section)
    # The source's one trailing return is outside the new else, after its loop.
    return_at = section.rfind(f'return {flag};')
    if return_at < 0:
        return []
    section = ' else {' + section[:return_at] + '}\n    ' + section[return_at:]
    return [(FAMILY, edit(source, [(first_return, opening + 1 + early.end(), ''), (end, fallback_end, section)]))]
