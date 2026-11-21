"""Try the target's ordering for a guarded cluster of global resets."""
import re

from .csource import _blank, find

FAMILY = 'scoped_global_reset'
ID = r'[A-Za-z_]\w*'
SHAPE = re.compile(
    rf'\bif\s*\(\s*{ID}\s*!=\s*0\s*\)\s*{{\s*'
    rf'(?P<first>(?P<a>{ID})\s*=\s*0\s*;)\s*(?P<b>{ID})\s*=\s*0\s*;\s*(?P<c>{ID})\s*=\s*0\s*;\s*'
    rf'{{\s*s32\s+(?P<local1>{ID})\s*=\s*(?P<load1>{ID})\s*;\s*s32\s+(?P<local2>{ID})\s*=\s*(?P<load2>{ID})\s*;\s*'
    rf'{ID}\s*=\s*(?P=local1)\s*;\s*{ID}\s*=\s*(?P=local2)\s*;\s*}}\s*'
    rf'(?P<flag>{ID})\s*=\s*0\s*;\s*{ID}\s*=\s*0\s*;\s*if\s*\(\s*(?P<count>{ID})\s*>\s*0\s*\)'
)
MEMORY = re.compile(rf'\b(sb|lw|sw)\s+(\$\w+),\s*%lo\(({ID})\)\(\$\w+\)')


def variants(source, name, arch, asm):
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    memory = [m.groups() for m in MEMORY.finditer(re.sub(r'/\*[^\n]*?\*/', '', asm))]
    for hit in SHAPE.finditer(clean, *span):
        first, second, third, flag, count = (hit[k] for k in ('a', 'b', 'c', 'flag', 'count'))
        if len({first, second, third, flag, count}) != 5:
            continue
        declarations = {}
        for symbol, kind in ((first, 's8|u8'), (second, 's8|u8'), (third, 's8|u8'), (flag, 's32'), (count, 's32')):
            match = re.search(rf'\bextern\s+(?P<type>{kind})\s+{symbol}\s*;', clean[:span[0]])
            if match:
                declarations[symbol] = match.start('type')
        if len(declarations) != 5:
            continue
        # A renamed symbol can still have its old address name in target assembly.
        if not any(
            seq[0] == ('sb', '$zero', first) and seq[1] == ('sb', '$zero', second)
            and seq[2][:2] == ('sb', '$zero') and seq[3][::2] == ('lw', hit['load1'])
            and seq[4][::2] == ('lw', hit['load2']) and seq[5][0] == seq[6][0] == 'sw'
            and seq[7][0] == 'lw' and seq[8] == ('sw', '$zero', flag)
            for seq in (memory[i:i+9] for i in range(len(memory)-8))
        ):
            continue
        a, b = hit.span('first')
        scoped = source[:a]+'do { '+source[a:b]+' } while (0);'+source[b:]
        combined = scoped
        for at in sorted((declarations[k] for k in (third, flag, count)), reverse=True):
            combined = combined[:at]+'volatile '+combined[at:]
        return [(FAMILY, combined), (FAMILY, scoped)]
    return []
