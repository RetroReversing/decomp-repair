"""A narrow unsigned global compared as a signed count, copied into an int local first so the test stays signed.

`if (((s32) count) > 0)` with `u8 count` compiles to `beqz`: combine knows a zero-extended byte is never negative and
turns the signed test into `!= 0`. The target of a voice-table loop tested `blez` on the same `lbu` result. The value
read into an `s32` local first (`n = count; if (n > 0)`) is a register combine has no reason to narrow, and the test
comes out signed. Measured on a 719-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`):
`beqz` -> `blez`, 1020 -> 830 with its other rows unchanged. Only for a global declared `u8` / `u16` / `unsigned char`
/ `unsigned short` in the source or the header, tested as `((s32) NAME) > 0` (also `>= 1`). A candidate rewrite; the
exact judge decides.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, lines, with_local

FAMILY = 'narrow_count_copy'
FAMILIES = (FAMILY,)
_NARROW = re.compile(r'\bextern\s+(?:u8|u16|unsigned\s+char|unsigned\s+short)\s+(?P<n>[A-Za-z_]\w*)\s*;')


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    narrow = {m['n'] for m in _NARROW.finditer(source + '\n' + header)}
    if not narrow:
        return []
    body = lines(part, source)
    out = []
    for i, line in enumerate(body):
        hit = re.fullmatch(r'if \(\(\(s32\) (?P<n>[A-Za-z_]\w*)\) (?:> 0|>= 1)\)', line.stripped)
        if not hit or hit['n'] not in narrow:
            continue
        local = hit['n'] + '_count'
        if re.search(rf'\b{local}\b', part.clean):
            continue
        declaration = with_local(source, part, f's32 {local};')
        if not declaration:
            continue
        copy = f'{line.indent}{local} = {hit["n"]};\n'
        test = line.source.replace(f'((s32) {hit["n"]})', local)
        out.append((FAMILY, apply(source, [declaration, (line.start, line.start, copy), (line.start, line.start + len(line.source), test)])))
    return out
