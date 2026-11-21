"""Recover an unsigned packed-word store with the target's shift order."""
import re

from .csource import _blank, find

FAMILY = 'packed_word_scheduling'
IDENT = r'[A-Za-z_]\w*'
PACK = re.compile(
    rf'(?P<lhs>{IDENT}(?:\s*(?:->|\.)\s*{IDENT})+)\s*=\s*'
    rf'\(\s*\(\s*\(\s*(?P<mask>0x[fF][fF]000000[uU]?)\s*\|\s*'
    rf'(?P<low>\(\s*(?P<value>{IDENT})\s*<<\s*8\s*\))\s*\)\s*\|\s*'
    rf'(?P<high>\(\s*(?P=value)\s*<<\s*16\s*\))\s*\)\s*\|\s*(?P=value)\s*\)\s*;'
)
SHIFTS = re.compile(r'\bsll\s+\$\w+,\s*(\$\w+),\s*(?:16|0[xX]10)\s*\n'
                    r'[^\S\n]*sll\s+\$\w+,\s*\1,\s*(?:8|0[xX]0?8)\b')


def variants(source, name, arch, asm, header=''):
    """Measure the reordered shifts inside one statement-scoped block."""
    if arch != 'mips' or not SHIFTS.search(re.sub(r'/\*[^\n]*?\*/', '', asm)):
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    result = []
    for hit in PACK.finditer(clean, *span):
        value = hit['value']
        decl = rf'\b(?:u32|unsigned(?:\s+int)?)\s+{value}\s*='
        prefix = clean[span[0]:hit.start()]
        # Require the local immediately before the store, with no volatile qualifier.
        if not re.search(rf'[;{{}}]\s*{decl}[^;{{}}]+;\s*$', prefix):
            continue
        if re.search(rf'^\s*#\s*define\s+{value}\b', source+'\n'+header, re.M):
            continue
        store = (source[hit.start():hit.start('low')] + source[slice(*hit.span('high'))]
                 + source[hit.end('low'):hit.start('high')] + source[slice(*hit.span('low'))]
                 + source[hit.end('high'):hit.end()])
        result.append((FAMILY, source[:hit.start()]+'do { '+store+' } while (0);'+source[hit.end():]))
        if len(result) == 2:
            break
    return result
