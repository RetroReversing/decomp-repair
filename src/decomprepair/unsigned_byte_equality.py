"""Offer an unsigned byte interpretation for equality to a small constant.

A MIPS GCC 2.7.2 state handler's byte comparison used lbu in the target but
lb in the draft. Casting the byte to unsigned char preserved equality to 2
and improved an O1 diagnostic from 7050 to 6850. Each child changes one read.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'unsigned_byte_equality'
LIMIT = 12


def variants(source, name, header='', flags=None):
    if any(flag.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for flag in flags or ()):
        return []
    context = source + '\n' + header
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b', context):
        return []
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end]
    if re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', body):
        return []
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', context))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    pattern = (rf'\bif\s*\(\s*(?P<read>\*\s*\(\s*(?P<table>{IDENT})\s*\+\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)\s*\+\s*'
               rf'(?P<index>{IDENT})\s*\))\s*(?P<op>==|!=)\s*(?P<value>0[xX][0-9a-fA-F]+|[0-9]+)\s*\)')
    result = []
    for m in re.finditer(pattern, body):
        table, index = m['table'], m['index']
        if int(m['value'], 16 if m['value'].lower().startswith('0x') else 10) > 127 or {table, index, name, 'if', 'unsigned', 'char'} & macros:
            continue
        if not re.search(rf'\bextern\s+(?:signed\s+)?char\s+{re.escape(table)}\s*\[\s*\]\s*;', _blank(context)):
            continue
        signature = clean.rfind(name, 0, part.opening)
        shadow = rf'\b(?:{IDENT}\s+)+\**\s*{re.escape(table)}\s*(?:[;=,\[)]|$)'
        if signature < 0 or re.search(shadow, clean[signature:part.end]):
            continue
        if re.search(rf'\b{re.escape(table)}\b', directives):
            continue
        start = part.opening + 1 + m.start('read')
        result.append((FAMILY, edit(source, [(start, start, '(unsigned char) ')])))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
