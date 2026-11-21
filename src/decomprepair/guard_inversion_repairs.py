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


def _toggle_target(asm):
    if 'beql' not in asm or 'lbu' not in asm or 'sb' not in asm:
        return None
    from .integer_repair_support import NUMBER, integer
    from .measured_stack_drafts import _lines

    text = '\n'.join(' '.join(line.split()) for line in _lines(asm))
    pattern = re.compile(
        rf'(?m)^lbu (?P<value>\$\w+), (?P<offset>{NUMBER})?\((?P<base>\$\w+)\)\n'
        rf'andi (?P<result>\$\w+), (?P=value), (?P<bit>{NUMBER})\n'
        r'beql (?P=result), \$zero, (?P<merge>\.L\w+)\n'
        rf'ori (?P=result), (?P=value), (?P<set>{NUMBER})\n'
        rf'andi (?P=result), (?P=value), (?P<clear>{NUMBER})\n(?P=merge):\n'
        r'sb (?P=result), (?(offset)(?P=offset))\((?P=base)\)$',
    )
    evidence = []
    for hit in pattern.finditer(text):
        bit, set_bit, clear = (integer(hit[key]) for key in ('bit', 'set', 'clear'))
        if (0 < bit < 256 and not bit & (bit - 1) and bit == set_bit and bit ^ clear == 255
                and len({hit[key] for key in ('base', 'value', 'result')}) == 3):
            evidence.append((integer(hit['offset'] or '0'), bit, clear))
    return evidence[0] if len(evidence) == 1 else None


def byte_toggle_applies(asm):
    return _toggle_target(asm) is not None


def rewrite_byte_toggle(source, name, asm, header=''):
    """Orient the bit update so the set path uses the target's likely delay slot."""
    if 'M2C_FIELD' not in source or not (evidence := _toggle_target(asm)):
        return None
    from .integer_repair_support import IDENT, NUMBER, edit, integer, view

    part = view(source, name)
    if not part:
        return None
    field = rf'M2C_FIELD\((?P<base>{IDENT}), u8 \*, (?P<offset>{NUMBER})\)'
    pattern = re.compile(
        rf'(?P<value>{IDENT})\s*=\s*{field};\s*'
        rf'if\s*\((?P<condition>!\(\s*(?P=value)\s*&\s*(?P<bit>{NUMBER})\s*\))\)\s*{{\s*'
        rf'(?P<set>(?P<result>{IDENT})\s*=\s*(?P=value)\s*\|\s*(?P<set_bit>{NUMBER});)\s*}}\s*else\s*{{\s*'
        rf'(?P<clear>(?P=result)\s*=\s*(?P=value)\s*&\s*(?P<mask>{NUMBER});)\s*}}\s*'
        r'M2C_FIELD\((?P=base), u8 \*, (?P=offset)\)\s*=\s*(?P=result);',
    )
    matches = []
    for hit in pattern.finditer(part.clean, part.opening + 1, part.end):
        if (tuple(integer(hit[key]) for key in ('offset', 'bit', 'mask')) != evidence
                or integer(hit['set_bit']) != evidence[1]
                or len({hit[key] for key in ('base', 'value', 'result')}) != 3):
            continue
        if any(not re.search(rf'\bu8\s+{hit[key]}\s*;', part.body) for key in ('value', 'result')):
            continue
        matches.append(hit)
    if len(matches) != 1:
        return None
    hit = matches[0]
    return edit(source, [(*hit.span('condition'), f"{hit['value']} & {hit['bit']}"),
                         (*hit.span('set'), source[slice(*hit.span('clear'))]),
                         (*hit.span('clear'), source[slice(*hit.span('set'))])])
