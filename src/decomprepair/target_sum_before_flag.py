"""Stage a pair of target-observed loads before a zero flag store.

A MIPS handler's draft stored a zero flag before reading two words whose sum
was stored in the same record. The target loads both words, stores the flag,
then adds and stores their sum. Staging the sum before the flag changed one
KMC GCC 2.7.2 score from 1910 to 1700. This can change behavior if the flag
aliases a source word, so it is a target-evidenced draft correction.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'target_sum_before_flag'
FAMILIES = (FAMILY,)
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'


def _witness(asm, first_offset, flag_offset, sum_offset):
    lines = [re.sub(r'\s+', ' ', re.sub(r'/\*.*?\*/', '', row).strip()) for row in (asm or '').splitlines()]
    for i, row in enumerate(lines):
        flag = re.fullmatch(r'(?i:sb) \$zero,\s*(' + NUM + r')\((\$\w+)\)', row)
        if not flag or int(flag[1], 0) != flag_offset:
            continue
        before, after = lines[max(0, i - 4):i], lines[i + 1:i + 4]
        loads = [m for item in before if (m := re.fullmatch(r'(?i:lw) (\$\w+),\s*(' + NUM + r')\(\$\w+\)', item))]
        if len(loads) < 2 or not any(int(m[2], 0) == first_offset for m in loads) or not any(int(m[2], 0) == 0 for m in loads):
            continue
        for j, item in enumerate(after):
            add = re.fullmatch(r'(?i:addu) (\$\w+),\s*(\$\w+),\s*(\$\w+)', item)
            if not add or not {add[2], add[3]} <= {m[1] for m in loads}:
                continue
            if any(re.fullmatch(r'(?i:sw) ' + re.escape(add[1]) + r',\s*' + re.escape(hex(sum_offset)) + r'\(' + re.escape(flag[2]) + r'\)', x, re.I) for x in after[j + 1:]):
                return True
    return False


def variants(source, name, asm):
    part = view(source, name)
    if not part:
        return []
    pattern = re.compile(
        r'\{\s*void\s*\*\s*(?P<alias>' + IDENT + r')\s*;\s*\{\s*\{\s*(?P=alias)\s*=\s*(?P<record>' + IDENT + r')\s*;\s*\}\s*\}\s*'
        r'M2C_FIELD\s*\(\s*(?P=alias)\s*,\s*u8\s*\*\s*,\s*(?P<flag>' + NUM + r')\s*\)\s*=\s*0[Uu]?\s*;\s*\}\s*'
        r'\{\s*\{\s*M2C_FIELD\s*\(\s*(?P=record)\s*,\s*s32\s*\*\s*,\s*(?P<dest>' + NUM + r')\s*\)\s*=\s*\(s32\)\s*\(\s*'
        r'(?P<expr>M2C_FIELD\s*\(\s*' + IDENT + r'\s*,\s*s32\s*\*\s*,\s*(?P<first>' + NUM + r')\s*\)\s*\+\s*'
        r'M2C_FIELD\s*\(\s*M2C_FIELD\s*\(\s*' + IDENT + r'\s*,\s*void\s*\*\s*\*\s*,\s*(?:0|0x0)\s*\)\s*,\s*s32\s*\*\s*,\s*(?:0|0x0)\s*\))\s*\)\s*;\s*\}\s*\}')
    result = []
    if re.search(r'\btime\b', part.clean[part.opening:part.end]):
        return []
    for hit in pattern.finditer(part.clean, part.opening + 1, part.end):
        if not _witness(asm, int(hit['first'], 0), int(hit['flag'], 0), int(hit['dest'], 0)):
            continue
        expr = source[hit.start('expr'):hit.end('expr')]
        text = (f'{{ s32 time = {expr}; M2C_FIELD({hit["record"]}, u8 *, {hit["flag"]}) = 0U; '
                f'M2C_FIELD({hit["record"]}, s32 *, {hit["dest"]}) = time; }}')
        result.append((FAMILY, edit(source, [(hit.start(), hit.end(), text)])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',), 'order': 40}
