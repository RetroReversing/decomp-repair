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

With two copies (`start = arg1; size = arg2;`, a block-cache lookup of 364 instructions) each drop alone scored the same
or worse (30 and 60 from 30) and both together were exact (0): the second scheduler places the prologue's saves with
the copies' moves, and both parameters' own moves had to come first. A child drops every droppable copy at once.
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
        match = re.fullmatch(rf'\s*({TYPE})((?:\s*\*)*)\s*\b({IDENT})\s*', text)
        if match:
            found[match[3]] = _norm(match[1]) + ' ' * bool(match[2]) + match[2].replace(' ', '').strip()
    return found


def _assigned(body, local, copy):
    """True when the local is written anywhere but its copy (`=`, `op=`, `++`, `--`)."""
    for hit in re.finditer(rf'(?<![\w.>])(?<!->){local}\b', body):
        if copy.start() <= hit.start() < copy.end():
            continue
        after, before = body[hit.end():hit.end() + 3], body[max(0, hit.start() - 2):hit.start()]
        if re.match(r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\s*(?:\+\+|--)', after) or before in ('++', '--'):
            return True
    return False


def _singles(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    # a backward `goto` could run the copy again after the parameter changed: then only a local nothing else writes
    jumps = re.search(r'\bgoto\b', part.body) is not None
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
        if re.search(rf'&\s*{local}\b', body) or (jumps and _assigned(body, local, copy)):
            continue
        declaration = None
        for decl in re.finditer(rf'\b({TYPE})\s+([^;(){{}}=\[\]]*?)\s*;', body):
            names = [n.strip() for n in decl[2].split(',')]
            stars = re.fullmatch(rf'((?:\*\s*)*){re.escape(local)}', names[0]) if len(names) == 1 else None
            kind = _norm(decl[1]) + (' ' + stars[1].replace(' ', '') if stars and stars[1] else '')
            if (local in names and _norm(decl[1]) == parameters[param] or stars and kind == parameters[param]) \
                    and decl.end() <= copy.start():
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
        rest = [n for n in names if n != local and re.sub(r'[\s*]', '', n) != local]
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


def variants(source, name, header=''):
    result = _singles(source, name)
    if len(result) > 1:
        # each drop alone changes the entry block's order only part of the way; the match needed them all
        text = source
        for _ in range(len(result)):
            offered = _singles(text, name)
            if not offered:
                break
            text = offered[0][1]
        if all(text != item[1] for item in result):
            result.insert(0, (FAMILY, text))
    return result
