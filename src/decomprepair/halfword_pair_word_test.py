"""A halfword compared with zero, read as the word the target reads.

Two adjacent halfword fields that a function clears together (`*(s16 *)(p + 0x178) = 0; *(u16 *)(p + 0x17A) = 0;`)
are tested together as one word in the game: `if (*(s32 *)(p + 0x178) == 0)`, one `lw` where the saved best's
`(s32) *(s16 *)(p + 0x178) == 0` is an `lh` that tests half of it. The rows say it plainly (`lw $v0, 0x178($s2)` in
the target, `lh` here, the branch offsets a word apart after it) and nothing else differs (1345 -> 1135 in one
557-instruction function, KMC GCC 2.7.2).

A proposal takes a read `*((s16 *) EXPR)` (or `u16`, `short`, `unsigned short`) that is compared with zero
(`== 0`, `!= 0`, an optional `(s32)` cast on the read) and writes the read as `s32`, when the target assembly has an
`lw` at an offset that appears in EXPR as a literal. The read and the compare are the only things that change; every
proposal is judged. MIPS only."""
import re

from .csource import find
from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'halfword_pair_word_test'
FAMILIES = (FAMILY,)

_READ = re.compile(r'\*\s*(\(\s*\(\s*((?:unsigned\s+short|short|u16|s16))\s*\*\s*\))')
_NUMBER = re.compile(r'\b(0[xX][0-9a-fA-F]+|\d+)\b')
LIMIT = 6


def _word_offsets(asm):
    return {int(m[1], 16) for m in re.finditer(r'\blw\s+\$\w+,\s*(?:-?)(0x[0-9a-fA-F]+)\(\$\w+\)', asm or '')}


def variants(source, name, arch='mips', asm=''):
    """Proposals: a halfword read that is only compared with zero, read as a word."""
    if arch != 'mips' or not find(source, name):
        return []
    part = view(source, name)
    offsets = _word_offsets(asm)
    if not part or not offsets:
        return []
    out = []
    for read in _READ.finditer(part.clean, part.opening, part.end):
        stop = close(part.clean, read.start(1))  # just past the bracket that wraps `(T *) EXPR`
        if not stop:
            continue
        operand = part.clean[read.end():stop - 1]
        if not {int(m[1], 0) for m in _NUMBER.finditer(operand)} & offsets:
            continue
        if not re.match(r'\s*\)*\s*(?:==|!=)\s*0\b(?!\s*[.\w])', part.clean[stop:part.end]):
            continue
        out.append((FAMILY, edit(source, [(read.start(2), read.end(2), 's32')])))
        if len(out) >= LIMIT:
            break
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'arch', 'asm'), 'order': 70}  # the registry: no caller wiring (registry.py)
