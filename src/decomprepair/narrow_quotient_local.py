"""A 16-bit mask on a quotient stored in a word local: the local is a halfword and the operands are signed.

m2c writes `lum = ((r + (g + b)) / 3) & 0xFFFF;` into a word local. The original had `u16 lum = (r + (g + b)) / 3;`.
In KMC GCC 2.7.2 the two differ in more than the mask: a signed division by three is `mult` by 0x55555556, `mfhi` and a
correction `sra x, 31; subu`, and storing the quotient in an `unsigned short` drops the correction (hypothesis, not
confirmed in the compiler source: the narrowing converts the division's result before the expansion and cse then sees
the high part alone), where the masked word form keeps it. With an unsigned operand in the sum (`unsigned int b`) the
division is an unsigned `multu` by 0xaaaaaaab and a shift instead, so the operands have to be signed too.

On an 842-instruction N64 lit-actor drawer (KMC GCC 2.7.2, scoring 2) the average of three colour bytes went from
`lui 0xaaaa; multu; srl` (4792 over the function) to `lui 0x5555; mult; mfhi; andi 0xffff` with a `u16` local and signed
operands (4183), the target's sequence. The halfword alone changed nothing (4792): the operand's signedness is the other
half, so the combined child is offered first.

`narrow_quotient_local` offers, for `X = ((EXPR) / K) & 0xFFFF;` with X a word local and K a constant, the function
with X a `u16` and the mask dropped, and the same with every `unsigned`/`u32` local named in EXPR made `s32`.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'narrow_quotient_local'
FAMILIES = (FAMILY,)
LIMIT = 4
WORD = r'(?:s32|int|u32|unsigned(?:\s+int)?)'
UNSIGNED = r'(?:u32|unsigned(?:\s+int)?)'
QUOTIENT = re.compile(rf'(?<![\w.>])(?P<x>{IDENT})\s*=\s*\(\s*(?P<e>\(.*?\)|{IDENT})\s*/\s*(?P<k>\d+)\s*\)\s*&\s*0[xX]0*[fF]{{4}}\s*;')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    result = []
    for hit in QUOTIENT.finditer(clean, part.opening, part.end):
        local = hit['x']
        declaration = re.search(rf'(?m)^([ \t]*){WORD}[ \t]+{re.escape(local)}[ \t]*;', clean[part.opening:part.end])
        if not declaration or len(re.findall(rf'(?<![\w.>]){re.escape(local)}\s*=(?!=)', clean[part.opening:part.end])) != 1:
            continue
        a, b = part.opening + declaration.start(), part.opening + declaration.end()
        narrow = [(a, b, f'{declaration[1]}u16 {local};'),
                  (hit.start(), hit.end(), f'{local} = ({source[hit.start("e"):hit.end("e")]} / {hit["k"]});')]
        operands = []
        for ident in dict.fromkeys(re.findall(IDENT, hit['e'])):
            unsigned = re.search(rf'(?m)^([ \t]*){UNSIGNED}[ \t]+{re.escape(ident)}[ \t]*;', clean[part.opening:part.end])
            if unsigned:
                operands.append((part.opening + unsigned.start(), part.opening + unsigned.end(), f'{unsigned[1]}s32 {ident};'))
        if operands:
            result.append((FAMILY, edit(source, narrow + operands)))
        result.append((FAMILY, edit(source, narrow)))
    return result[:LIMIT]
