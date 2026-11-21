"""Stage an unsigned rate quotient before the target resets a global."""
import re

from .csource import _blank, find

FAMILY = 'unsigned_rate_division_scope'
ID = r'[A-Za-z_]\w*'
RESET = re.compile(
    rf'(?:\bif\s*\(\s*(?P<count>{ID})\s*!=\s*0\s*\)\s*{{\s*)'
    rf'(?P<reset>(?P<global>{ID})\s*=\s*0\s*;)\s*(?P<out>{ID})\s*=\s*(?P<expr>[^;{{}}]+);'
)


def variants(source, name, arch, asm, header=''):
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    assembly = re.sub(r'/\*[^\n]*?\*/', '', asm)
    if not re.search(r'\b0x10624dd3\b', assembly, re.I) or not re.search(r'\b0xaaaaaaab\b', assembly, re.I):
        return []
    used = set(re.findall(ID, clean+'\n'+header))
    for hit in RESET.finditer(clean, *span):
        # Match the actual grouping as well as the operators. An unparenthesized
        # shift would bind differently from the division that follows it.
        shape = re.sub(r'\s+', '', hit['expr'])
        expr = re.fullmatch(
            rf'\(\(\(\(\(\(\*(?P<pointer>{ID})\)\*{hit["count"]}\)/1000\)>>6\)/3\)\*(?:0x[cC]0|192)\)'
            rf'\+(?:0x[cC]0|192)', shape)
        if not expr or hit['global'] == hit['out']:
            continue
        store = re.escape(hit['global'])
        if not re.search(rf'\bmultu\b[^\n]*\n(?:[^\n]*\n){{0,4}}?\s*sw\s+\$zero,\s*%lo\({store}\)[^\n]*\n'
                         r'\s*mfhi\s+(\$\w+)\s*\n\s*srl\s+\$\w+,\s*\1,\s*(?:7|0x7)\b', assembly):
            continue
        quotient = '__repair_rate_quotient'
        while quotient in used:
            quotient += '_'
        a, b = hit.start('reset'), hit.end()
        indent = re.match(r'[^\S\n]*', source[source.rfind('\n', 0, a)+1:]).group()
        c, d = hit.span('reset')
        replacement = (f'u32 {quotient};\n{indent}{quotient} = ((*{expr["pointer"]}) * {hit["count"]}) / 1000U;\n'
                       +indent+source[c:d]+f'\n{indent}{hit["out"]} = ({quotient} / 192U) * 0xC0U + 0xC0U;')
        return [(FAMILY, source[:a]+replacement+source[b:])]
    return []
