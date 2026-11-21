"""m2c's local copy of a parameter, written back as the parameter the game modified in place.

m2c gives every register it sees reassigned its own variable, so a flags parameter the game masked in place comes back as

    void f(s32 arg0, void *arg1, s32 arg2, s32 arg3) {
        s32 var_s4;
        var_s4 = arg2;
        if (arg3 == 0) { var_s4 &= 0xFFFCFFFF; }
        g(arg1, 2, var_s4 | 0x1000, arg0);

The copy is a second pseudo register beside the parameter's own, ahead of it in gcc 2.7.2's scheduling of the entry
block: an N64 function with a breadth-first walk (four calls, three loops, three spilled values) stood at 300 with the
copy and was exact once `arg2` was masked directly, because the extra copy of `$a2` changed where the first scheduler
put the stores of `$a3` and of the zero start index, and with them whether reload re-read `arg3` from its slot.

Offered when the first statement that touches the local is `var = param;`, the parameter is not mentioned anywhere
else, the two have the same type, and the local is never addressed. The local's declaration goes and every use becomes
the parameter.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'parameter_copy_drop'
FAMILIES = (FAMILY,)
TYPE = r'(?:(?:unsigned|signed|const)\s+)*[A-Za-z_]\w*'


def _norm(text):
    return re.sub(r'\s+', ' ', text).strip()


def _parameters(part):
    signature = re.search(r'\(([^()]*)\)\s*$', part.clean[:part.opening])
    if not signature:
        return {}
    found = {}
    for text in signature[1].split(','):
        match = re.fullmatch(rf'\s*({TYPE})\s+({IDENT})\s*', text)
        if match:
            found[match[2]] = _norm(match[1])
    return found


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    parameters = _parameters(part)
    if not parameters:
        return []
    body, base = part.body, part.opening + 1
    result = []
    for copy in re.finditer(rf'(?:(?<=[;{{}}])|^)\s*({IDENT})\s*=\s*({IDENT})\s*;', body):
        local, param = copy[1], copy[2]
        if param not in parameters or local in parameters or local == param:
            continue
        if re.search(rf'(?<![\w.>])(?<!->){param}\b', body[:copy.start()] + body[copy.end():]):
            continue
        if re.search(rf'&\s*{local}\b', body):
            continue
        declaration = None
        for decl in re.finditer(rf'\b({TYPE})\s+([^;(){{}}=\[\]]*?)\s*;', body):
            names = [n.strip() for n in decl[2].split(',')]
            if local in names and _norm(decl[1]) == parameters[param] and decl.end() <= copy.start():
                declaration = decl
        if not declaration:
            continue
        if body[:copy.start()].count('{') != body[:copy.start()].count('}'):
            continue
        # the first mention of the local is its declaration, then this assignment
        before = [m for m in re.finditer(rf'(?<![\w.>])(?<!->){local}\b', body[:copy.start()])
                  if not declaration.start() <= m.start() < declaration.end()]
        if before:
            continue
        names = [n.strip() for n in declaration[2].split(',')]
        rest = [n for n in names if n != local]
        edits = [(base + copy.start(), base + copy.end(), '')]
        edits.append((base + declaration.start(), base + declaration.end(),
                      f'{declaration[1]} {", ".join(rest)};' if rest else ''))
        for use in re.finditer(rf'(?<![\w.>])(?<!->){local}\b', body):
            inside = declaration.start() <= use.start() < declaration.end()
            if inside or copy.start() <= use.start() < copy.end():
                continue
            edits.append((base + use.start(), base + use.end(), param))
        result.append((FAMILY, edit(source, edits)))
    return result[:3]
