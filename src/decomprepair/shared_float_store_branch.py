"""Recover a shared store for positive and negative float threshold branches.

A KMC GCC 2.7.2 function duplicated a byte-zero store in the two arms of a float threshold test. Directing the
positive arm to the other store improved the O2 judge score from 47,535 to 47,035 and an O1 diagnostic from 2,610
to 2,530. This is a single observation, not a match. The comparisons remain in their original order, including for
NaN, and only the known side-effect-free field macro and matching target branch-likely store are accepted.
"""
import re

from .csource import find
from .integer_repair_support import view
from .shared_float_equality_ladder import _MACRO

FAMILY = 'shared_float_store_branch'
FAMILIES = (FAMILY,)
_FIELD = r'M2C_FIELD\(\s*[A-Za-z_]\w*\s*,\s*f32\s*\*\s*,\s*(?:0[xX][0-9A-Fa-f]+|\d+)\s*\)'
_STORE = r'M2C_FIELD\(\s*[A-Za-z_]\w*\s*,\s*u8\s*\*\s*,\s*(?:0[xX][0-9A-Fa-f]+|\d+)\s*\)\s*=\s*0[Uu]?\s*;'
_PATTERN = re.compile(
    rf'if\s*\(\s*(?P<field>{_FIELD})\s*>\s*0\.0[fF]\s*\)\s*\{{\s*'
    rf'(?P<inner>if\s*\(\s*!\s*\(\s*(?P=field)\s*<\s*(?P<threshold>\d+\.\d*[fF])\s*\)\s*\)\s*'
    rf'\{{\s*\}}\s*else\s*\{{\s*(?P<store>{_STORE})\s*\}})\s*\}}\s*'
    rf'else\s+if\s*\(\s*-\s*(?P=field)\s*<\s*(?P=threshold)\s*\)\s*\{{\s*(?P=store)\s*\}}'
)


def variants(source, name, asm, header=''):
    if not re.search(r'\bbc1tl\b[^\n]*\n[^\n]*\bsb\s+\$zero\s*,', asm or ''):
        return []
    part, span = view(source, name), find(source, name)
    macros = source + '\n' + (header or '')
    if not part or not span or not _MACRO.search(macros) or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return []
    out = []
    for hit in _PATTERN.finditer(part.clean, part.opening + 1, part.end):
        if re.search(r'/[*/]|#', source[hit.start():hit.end()]):
            continue
        label = 'decomp_float_store'
        while re.search(rf'\b{label}\b', part.clean[span[0]:part.end]):
            label += '_'
        inner = f"if ({hit['field']} < {hit['threshold']}) goto {label};"
        store_at = hit.end('store')
        second = part.clean.find(hit['store'], store_at, hit.end())
        if second < 0:
            continue
        text = (source[:hit.start('inner')] + inner + source[hit.end('inner'):second]
                + label + ': ' + source[second:])
        out.append((FAMILY, text))
    return out[:8]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
