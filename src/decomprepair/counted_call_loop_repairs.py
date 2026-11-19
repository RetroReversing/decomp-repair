"""m2c's counted search loop around a call, written as the `for` loop it came from.

A loop that tries a call with each of a few values and returns on the first that succeeds comes back from m2c with
the counter stepped first and a masked copy of it for the call, the copy typed to the call's (guessed) parameter:

    var_s0 = 0;
    var_a0 = 0 & 0xFFFF;
loop_2:
    var_s0 += 1;
    if (f(var_a0, arg0) == 0) {
        var_a0 = var_s0 & 0xFFFF;
        if ((u32) (var_s0 & 0xFFFF) >= 4U) {
            return 0;
        }
        goto loop_2;
    }
    return 1;

With the copy declared `u8` the call's argument was masked to a byte where the game passed the halfword: an N64
function was 80.4% so, and exact as `for (i = 0; i < 4; i++) { if (f(i, arg0) != 0) return 1; } return 0;` with the
counter a `u16` (the mask's width) and the callee's `u8` parameter, m2c's guess, a `u16`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'counted_call_loop'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
SHAPE = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<i>' + IDENT + r') = 0;[ \t]*\n'
    r'[ \t]*(?P<arg>' + IDENT + r') = 0 & 0x(?P<mask>FFFF|FF);[ \t]*\n'
    r'[ \t]*(?P<loop>' + IDENT + r'):[ \t]*\n'
    r'[ \t]*(?P=i) \+= 1;[ \t]*\n'
    r'[ \t]*if \((?P<call>[^\n]*?) == 0\) \{[ \t]*\n'
    r'[ \t]*(?P=arg) = (?P=i) & 0x(?P=mask);[ \t]*\n'
    r'[ \t]*if \(\(u32\) \((?P=i) & 0x(?P=mask)\) >= (?P<limit>0x[0-9A-Fa-f]+|\d+)U?\) \{[ \t]*\n'
    r'[ \t]*return (?P<left>[^;\n]+);[ \t]*\n[ \t]*\}[ \t]*\n'
    r'[ \t]*goto (?P=loop);[ \t]*\n'
    r'[ \t]*\}[ \t]*\n'
    r'[ \t]*return (?P<found>[^;\n]+);[ \t]*\n')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for hit in SHAPE.finditer(clean, opening, end):
        i, arg = hit['i'], hit['arg']
        body = clean[opening:end]
        # the counter and its copy are used nowhere else, and only this loop jumps to the label
        rest = body[:hit.start() - opening] + body[hit.end() - opening:]
        declarations = r'(?m)^[ \t]*(?![ \t])(?!(?:return|goto|break|continue)\b)[\w ]+?[\s*]+\w+\s*;[ \t]*$'
        if re.search(r'\b(?:' + i + '|' + arg + r')\b', re.sub(declarations, '', rest)):
            continue
        if len(re.findall(r'\bgoto\s+' + hit['loop'] + r'\s*;', body)) != 1:
            continue
        call = source[hit.start('call'):hit.end('call')]
        if len(re.findall(r'\b' + arg + r'\b', call)) != 1 or re.search(r'\b' + i + r'\b', call):
            continue
        call = re.sub(r'\b' + arg + r'\b', i, call)
        indent, inner = hit['indent'], hit['indent'] + '    '
        kind = 'u16' if hit['mask'] == 'FFFF' else 'u8'
        loop = (f'{indent}for ({i} = 0; {i} < {hit["limit"]}; {i}++) {{\n'
                f'{inner}if ({call} != 0) {{\n'
                f'{inner}    return {hit["found"].strip()};\n'
                f'{inner}}}\n'
                f'{indent}}}\n'
                f'{indent}return {hit["left"].strip()};\n')
        text = source[:hit.start()] + loop + source[hit.end():]
        # the counter takes the mask's width; the copy goes
        text = re.sub(r'(?m)^([ \t]*)[\w ]+?\s+' + i + r'\s*;', lambda m, k=kind, c=i: f'{m[1]}{k} {c};', text, count=1)
        text = re.sub(r'(?m)^[ \t]*[\w ]+?\s+' + arg + r'\s*;[ \t]*\n', '', text, count=1)
        result.append((FAMILY, _widen_prototype(text, call, i, kind)))
    return result[:2]


def _widen_prototype(text, call, counter, kind):
    """The callee's prototype takes the counter at the mask's width where m2c guessed a narrower type (the byte mask
    came from that guess)."""
    from . import m2cfix
    callee = re.match(r'\s*(' + IDENT + r')\s*\(', call)
    if not callee:
        return text
    args = m2cfix._split_top_level(call[call.index('(') + 1:call.rindex(')')])
    position = next((k for k, a in enumerate(args) if a.strip() == counter), None)
    proto = re.search(r'(?m)^([^\n;{}]*\b' + callee[1] + r'\s*\()([^()]*)(\)\s*;)', text)
    if position is None or not proto:
        return text
    params = m2cfix._split_top_level(proto[2])
    if position >= len(params) or params[position].strip() not in ('u8', 's8', 'char', 'unsigned char'):
        return text
    params[position] = kind if kind != 'u8' else params[position].strip()
    return text[:proto.start(2)] + ', '.join(p.strip() for p in params) + text[proto.end(2):]
