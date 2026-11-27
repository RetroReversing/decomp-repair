"""Initialize an unescaped local record's read-derived field before two zero fields.

A KMC MIPS call setup stored two zero configuration fields before loading a
third from memory. Initializing the read-derived field first changed one score
from 2030 to 1910. The three fields are distinct and the record has not
escaped before these stores, so the memory read cannot observe their order.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'local_record_read_first'
FAMILIES = (FAMILY,)


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto)\b', part.clean[part.opening:part.end]):
        return []
    # Only the app's direct field-access macro: no call or user-defined effect.
    if not re.search(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s+\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)', source):
        return []
    if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s8|u8|s16|u16|s32|u32)\s*;|(?m:^\s*#\s*(?:define|undef)\s+(?:s8|u8|s16|u16|s32|u32)\b)', source + '\n' + header):
        return []
    pattern = re.compile(
        r'(?P<a>(?P<obj>' + IDENT + r')\.(?P<f1>' + IDENT + r')\s*=\s*0\s*;)\s*'
        r'(?P<b>(?P=obj)\.(?P<f2>' + IDENT + r')\s*=\s*0\s*;)\s*'
        r'(?P<c>(?P=obj)\.(?P<f3>' + IDENT + r')\s*=\s*(?P<rhs>[^;{}]+);)')
    result = []
    for hit in pattern.finditer(part.clean, part.opening + 1, part.end):
        obj = hit['obj']
        if len({hit['f1'], hit['f2'], hit['f3']}) != 3:
            continue
        decl = re.search(r'\bstruct\s*\{(?P<fields>[^{}]+)\}\s*' + re.escape(obj) + r'\s*;', part.clean[part.opening:hit.start()])
        if not decl or re.search(r'\bstatic\s*$', part.clean[part.opening:part.opening + decl.start()]):
            continue
        fields = {}
        for field in decl['fields'].split(';'):
            if not field.strip():
                continue
            m = re.fullmatch(r'\s*(s16|u16|s32|u32|s8|u8)\s+(' + IDENT + r')\s*', field)
            if not m:
                break
            fields[m[2]] = m[1]
        else:
            if not {hit['f1'], hit['f2'], hit['f3']} <= set(fields):
                continue
            rhs = hit['rhs']
            if (not re.search(r'\bM2C_FIELD\s*\(', rhs) or re.search(r'\b' + re.escape(obj) + r'\b|\+\+|--|(?<![=!<>])=(?!=)', rhs)
                    or re.search(r'\b(?!M2C_FIELD\b)' + IDENT + r'\s*\(', re.sub(r'\(\s*(?:s8|u8|s16|u16|s32|u32)\s*\)', '', rhs))):
                continue
            before = part.clean[part.opening:hit.start()]
            if re.search(r'&\s*' + re.escape(obj) + r'\b', before):
                continue
            # Preserve the relative order of both zero stores and their spacing.
            first = source[hit.start('a'):hit.start('c')]
            last = source[hit.start('c'):hit.end('c')]
            whitespace = re.match(r'\s*', source[hit.end('b'):hit.start('c')]).group()
            result.append((FAMILY, edit(source, [(hit.start(), hit.end(), last + whitespace + first.rstrip())])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 40}
