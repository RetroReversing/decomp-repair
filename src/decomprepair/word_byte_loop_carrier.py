"""Stage a narrow parameter in a word local while retaining a narrow loop test."""
import re

from .csource import _code_only, find

IDENT = r'[A-Za-z_]\w*'
BYTE = r'(?:u8|unsigned\s+char)'


def variants(source, name, arch, asm):
    span = find(source, name)
    if not span or arch != 'mips':
        return []
    asm = re.sub(r'/\*[^\n]*?\*/', '', asm)
    copy = re.search(r'\b(?:move|addu|or)\s+(\$\w+),\s*\$a1(?:,\s*\$zero)?\s*$', asm, re.M)
    if not copy:
        return []
    mask = re.search(rf'\bandi\s+(\$\w+),\s*{re.escape(copy[1])},\s*(?:0xff|255)\b', asm, re.I)
    compare = re.search(r'\blbu\s+(\$\w+),[^\n]+\n\s*beq\s+\1,\s*(\$\w+)', asm)
    if not mask or not compare or not re.search(
            rf'\b(?:move|addu|or)\s+{re.escape(compare[2])},\s*{re.escape(mask[1])}(?:,\s*\$zero)?\s*$',
            asm[mask.end():compare.start()], re.M):
        return []
    clean = _code_only(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    signature = clean[span[0]:opening]
    arguments = signature[signature.find('(')+1:signature.rfind(')')].split(',')
    if len(arguments) < 2 or not (arg := re.fullmatch(rf'\s*{BYTE}\s+({IDENT})\s*', arguments[1])):
        return []
    argument = arg[1]
    carrier = re.compile(rf'\b(?P<type>{BYTE})\s+(?P<local>{IDENT})\s*;(?=[^{{}}]*\bif\b)').search(clean, opening, span[1])
    if not carrier:
        return []
    local = carrier['local']
    if len(re.findall(rf'\b{local}\b', clean[opening:span[1]])) != 4:
        return []
    assign = re.compile(rf'\b{local}\s*=(?!=)\s*(?P<rhs>{argument})\s*;')
    assignments = list(assign.finditer(clean, carrier.end(), span[1]))
    if len(assignments) != 1:
        return []
    assignment = assignments[0]
    rest = clean[assignment.end():span[1]]
    cmp = re.search(rf'\bdo\s*{{\s*if\s*\(\s*{IDENT}\s*\[[^\]\n]+\]\s*==\s*(?P<rhs>{local})\b', rest)
    if not cmp or not re.search(rf'\b{local}\s*==\s*(?:0x[\da-fA-F]+|\d+)\b', rest[:cmp.start()]):
        return []
    before_test = rest[:cmp.start()]
    if re.search(rf'\b{argument}\s*(?:=(?!=)|[-+*/%&|^]=|[<>]{{2}}=|\+\+|--)|(?:&|\+\+|--)\s*{argument}\b', before_test):
        return []
    a, b = carrier.span('type')
    c, d = assignment.span('rhs')
    e, f = (assignment.end()+offset for offset in cmp.span('rhs'))
    return [('word_byte_loop_carrier', source[:a]+'s32'+source[b:c]+
             f'(u8){argument}'+source[d:e]+f'(u8){argument}'+source[f:])]
