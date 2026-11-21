"""Measure a loop cursor setup in its own statement scope."""
import re

from .csource import _blank, find

FAMILY = 'scoped_cursor_entry'
ID = r'[A-Za-z_]\w*'
CURSOR = re.compile(
    rf'\b(?P<cursor>{ID})\s*=\s*\(\s*{ID}\s*\*\s*\*\s*\)\s*'
    rf'\(\s*{ID}\s*\+\s*(?P<offset>0[xX][\da-fA-F]+|[1-9]\d*)\s*\)\s*;'
    rf'(?=\s*(?P<label>{ID})\s*:\s*{ID}\s*=\s*\(\s*{ID}\s*\*\s*\)\s*'
    rf'\(\s*\*\s*(?P=cursor)\s*\)\s*;)'
)


def variants(source, name, arch, asm):
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    assembly = re.sub(r'/\*[^\n]*?\*/', '', asm)
    for hit in CURSOR.finditer(clean, *span):
        if not clean[span[0]:hit.start()].rstrip().endswith((';', '{', '}')):
            continue
        if not re.search(rf'\bgoto\s+{hit["label"]}\s*;', clean[hit.end():span[1]]):
            continue
        offset = int(hit['offset'], 0)
        evidence = (rf'\baddiu\s+(\$s[0-7]),\s*\$s[0-7],\s*(?:{offset}|0[xX]0*{offset:x})\s*\n'
                    rf'(?:\s*\.\w+:\s*\n)?\s*lw\s+\$\w+,\s*(?:0[xX]0|0)?\(\1\)')
        if re.search(evidence, assembly, re.I):
            a, b = hit.span()
            return [(FAMILY, source[:a]+'do { '+source[a:b]+' } while (0);'+source[b:])]
    return []
