"""An early-return guard as the `if` around the function's work that it was.

m2c writes a function whose work sits inside `if (flag == 0) { ...; return 1; } return 0;` as a guard and a tail:

    var_v0 = 0;
    if (D_8010086A) return var_v0;
    var_v0 = 1;
    D_800E09B8 = arg1;
    ...
    return var_v0;

gcc 2.7.2 lays the two out differently (where `li $v0, 1` goes): an N64 function was 98% as the guard, and also as
direct returns, and exact with the guard inverted around the rest, `if (!(D_8010086A)) { ...; return var_v0; }
return var_v0;`. Only for a guard at the function's own level whose arm is a lone `return`, with the function's last
statement a `return`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'guard_inversion'
FAMILIES = (FAMILY,)

GUARD = re.compile(r'(?m)^(?P<indent>[ \t]+)if\s*\(')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    final = re.search(r'(?m)^[ \t]*return\b[^;]*;[ \t]*\n[ \t]*\}\s*$', clean[opening:end])
    if not final:
        return []
    final_at = opening + final.start()
    result = []
    for guard in GUARD.finditer(clean, opening + 1, final_at):
        # the function's own level: no unclosed brace between the body's start and here
        depth = clean[opening + 1:guard.start()].count('{') - clean[opening + 1:guard.start()].count('}')
        if depth != 0:
            continue
        cond_open = guard.end() - 1
        cond_close = close(clean, cond_open)
        if not cond_close:
            continue
        arm = re.match(r'\s*(?:\{\s*)?return\b(?P<value>[^;]*);(?:\s*\})?[ \t]*\n', clean[cond_close:final_at])
        if not arm or (clean[cond_close:cond_close + arm.end()].count('{')
                       != clean[cond_close:cond_close + arm.end()].count('}')):
            continue
        rest_start = cond_close + arm.end()
        rest = source[rest_start:final_at]
        if not rest.strip() or re.search(r'^\s*[A-Za-z_]\w*:', clean[rest_start:final_at], re.M):
            continue
        condition = source[cond_open + 1:cond_close - 1].strip()
        inverse = negate(condition) or f'!({condition})'
        indent = guard['indent']
        last_line_end = clean.index('\n', final_at) + 1
        moved = source[rest_start:last_line_end]
        body = ''.join(('    ' + line if line.strip() else line) for line in moved.splitlines(keepends=True))
        value = source[cond_close + arm.start('value'):cond_close + arm.end('value')]
        text = (source[:guard.start()] + f'{indent}if ({inverse}) {{\n' + body + f'{indent}}}\n'
                + f'{indent}return{value};\n' + source[last_line_end:])
        result.append((FAMILY, text))
        if len(result) >= 2:
            break
    return result
