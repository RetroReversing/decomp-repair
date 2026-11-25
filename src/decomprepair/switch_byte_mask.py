"""A switch on a byte read into a wider local, with and without the `& 0xFF` the game's source wrote.

A KMC GCC 2.7.2 N64 text routine (`-G0 -mips3 -mgp32 -mfp32 -O2`) read each character with `ch = *p;` (`p` a `u8 *`,
`ch` an `s32`) and switched on it. The draft said `switch (ch)`; the target is the `andi` of a switch on `ch & 0xFF`
(m2c writes that mask too, as `var_v1 = var_s0 & 0xFF; switch (var_v1)`, and an agent tidying the draft drops it as
redundant). The mask changes nothing about the value (the byte is already 0..255) but it keeps the compiler from
using the loaded register as the switch index and reusing it across the loop: 1595 -> 0 with `switch (ch & 0xFF)`.

For a `switch (x)` where `x` is a local of a wider integer type that the function only ever sets from an unsigned
byte (`x = *p;` or `x = p[i];` for `p` a `u8`/`unsigned char` pointer or array, `x = e & 0xFF;`, `x = (u8) e;`), this
offers `switch (x & 0xFF)`; for a `switch (x & 0xFF)` of the same kind of local, `switch (x)`. The value is the same
either way, so each is only a code-shape hypothesis for the judge.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'switch_byte_mask'
FAMILIES = (FAMILY,)
_WIDE = r'(?:s32|u32|int|unsigned(?:\s+int)?|long|s16|u16|short)'
_BYTE_POINTER = r'(?:u8|unsigned\s+char|M2C_UNK8)'


def _byte_sources(text):
    """Names of the byte pointers and arrays the function (or the file) declares."""
    return set(re.findall(rf'\b{_BYTE_POINTER}\s*\*\s*({IDENT})', text)) | set(re.findall(rf'\b{_BYTE_POINTER}\s+({IDENT})\s*\[', text))


def _byte_valued(variable, body, sources):
    name = re.escape(variable)
    if re.search(rf'(?<![\w.>]){name}\s*(?:[+\-*/%&|^]|<<|>>)=|(?:\+\+|--)\s*{name}\b|\b{name}\s*(?:\+\+|--)', body):
        return False
    assigned = re.findall(rf'(?<![\w.>])\s*{name}\s*=(?!=)\s*([^;]*);', body)
    if not assigned:
        return False
    for value in assigned:
        value = value.strip()
        if re.fullmatch(rf'\*\s*({IDENT})', value) and re.fullmatch(rf'\*\s*({IDENT})', value)[1] in sources:
            continue
        index = re.fullmatch(rf'({IDENT})\s*\[[^\[\];]+\]', value)
        if index and index[1] in sources:
            continue
        if re.fullmatch(r'\(?[^;]*\)?\s*&\s*0[xX][fF][fF]', value) or re.fullmatch(rf'\(\s*{_BYTE_POINTER}\s*\)\s*[^;]+', value):
            continue
        return False
    return True


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\bvolatile\b', part.clean[part.opening:part.end]):
        return []
    head = source[:part.opening]
    signature = head[head.rfind('(', 0, part.opening):part.opening] if '(' in head else ''
    body = part.clean[part.opening:part.end]
    sources = _byte_sources(header + '\n' + signature + '\n' + body)
    wide = set(re.findall(rf'(?m)^[ \t]*{_WIDE}\s+({IDENT})\s*;', body))
    found = []
    for hit in re.finditer(rf'\bswitch\s*\(\s*(?P<var>{IDENT})\s*(?P<mask>&\s*0[xX][fF][fF])?\s*\)', body):
        variable = hit['var']
        if variable not in wide or not _byte_valued(variable, body, sources):
            continue
        start = part.opening + hit.start()
        end = part.opening + hit.end()
        text = f'switch ({variable})' if hit['mask'] else f'switch ({variable} & 0xFF)'
        found.append((FAMILY, edit(source, [(start, end, text)])))
    return found[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
