"""Keep a byte-table address live across a call while preserving both reads."""
import re

from .csource import _blank, find

FAMILY = 'scoped_byte_read_call'
ID = r'[A-Za-z_]\w*'
PATTERN = re.compile(
    rf'\bif\s*\(\s*(?P<first>(?P<table>{ID})\s*\[\s*0\s*\])\s*!=\s*0\s*\)\s*{{\s*'
    rf'(?P<call>{ID}\s*\([^;{{}}]*\)\s*;)\s*'
    rf'if\s*\(\s*(?P<second>(?P=table)\s*\[\s*0\s*\])\s*(?:>=|==|>)\s*\d+[Uu]?\s*\)'
)


def variants(source, name, arch, asm, header=''):
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    assembly = re.sub(r'/\*[^\n]*?\*/', '', asm)
    opening = clean.find('{', *span)
    used = set(re.findall(ID, clean+'\n'+header))
    for hit in PATTERN.finditer(clean, opening, span[1]):
        if not clean[opening:hit.start()].rstrip().endswith((';', '{', '}')):
            continue  # A preceding unbraced control statement would only guard the capture.
        table = hit['table']
        if not re.search(rf'\bextern\s+u8\s+{table}\s*\[\s*\]\s*;', clean[:span[0]]+'\n'+header):
            continue
        if re.search(rf'(?m)^\s*#\s*define\s+{table}\b', source+'\n'+header):
            continue
        evidence = (rf'\blui\s+(\$s[0-7]),\s*%hi\({table}\)\s*\n'
                    rf'\s*addiu\s+\1,\s*\1,\s*%lo\({table}\)\s*\n'
                    rf'\s*lbu\s+\$\w+,\s*(?:0x0|0)?\(\1\)[^\n]*\n'
                    rf'(?:[^\n]*\n){{0,4}}?\s*jal\s+{ID}[^\n]*\n'
                    rf'(?:[^\n]*\n){{0,3}}?\s*lbu\s+\$\w+,\s*(?:0x0|0)?\(\1\)')
        if not re.search(evidence, assembly):
            continue
        pointer = '__repair_byte_table'
        while pointer in used:
            pointer += '_'
        a, b = hit.span('first')
        c, d = hit.span('call')
        e, f = hit.span('second')
        indent = re.match(r'[^\S\n]*', source[source.rfind('\n', 0, hit.start())+1:]).group()
        tail = (source[hit.start():a] + pointer+'[0]' + source[b:c] + 'do { ' + source[c:d]
                + ' } while (0);' + source[d:e] + pointer+'[0]' + source[f:])
        return [(FAMILY, source[:opening+1] + '\n    u8 *'+pointer+';' + source[opening+1:hit.start()]
                 + f'do {{ {pointer} = {table}; }} while (0);\n{indent}' + tail)]
    return []
