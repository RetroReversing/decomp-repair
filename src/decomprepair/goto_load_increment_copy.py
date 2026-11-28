"""Compute a shared increment through its destination across a pointer copy.

A MIPS KMC O1 state handler held a loaded increment in a private temporary,
then copied its pointer and value into a shared goto store. Loading into the
shared value, copying the pointer and then incrementing reduced its linked
diagnostic from 175 to 170. Staging the load in the existing temporary before
the pointer copy reduced it to 150. The allocation reason is a hypothesis.
"""
import re

from . import integer_abi
from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'goto_load_increment_copy'
LIMIT = 6


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = _blank(source + '\n' + header)
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:volatile|_Atomic|asm|__asm__|setjmp|longjmp|__LINE__|__COUNTER__|__builtin_\w*|class|namespace|template|operator)\b|::', context):
        return []
    part = view(source, name)
    if not part or integer_abi.scalar('s32', context, 'mips') != (32, True):
        return []
    clean, body = part.clean, part.body
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', context))
    if macros.intersection(re.findall(IDENT, body)) or re.search(rf'&&\s*{IDENT}\b', body):
        return []
    pairs = brace_pairs(clean, part.opening, part.end)
    if pairs is None:
        return []
    pattern = re.compile(
        rf'(?m)^[ \t]*(?P<statement>(?P<tmp>{IDENT})\s*=\s*\*\s*(?P<src>{IDENT})\s*\+\s*1\s*;'
        rf'\s*\n[ \t]*(?P<ptr>{IDENT})\s*=\s*(?P=src)\s*;'
        rf'\s*\n[ \t]*(?P<value>{IDENT})\s*=\s*(?P=tmp)\s*;'
        rf'\s*\n[ \t]*goto\s+(?P<label>{IDENT})\s*;)')
    out = []
    for hit in pattern.finditer(clean, part.opening + 1, part.end):
        tmp, src, ptr, value, label = (hit[x] for x in ('tmp', 'src', 'ptr', 'value', 'label'))
        if len({tmp, src, ptr, value, label}) != 5 or clean[part.opening + 1:hit.start('statement')].rstrip()[-1:] not in ('', ';', '{', '}'):
            continue
        declarations = {}
        for var, star in ((tmp, ''), (value, ''), (src, r'\*'), (ptr, r'\*')):
            decls = list(re.finditer(rf'(?m)^[ \t]*s32\s*{star}\s*(?P<name>{re.escape(var)})\s*;[ \t]*(?:\n|$)', clean[part.opening + 1:part.end]))
            if len(decls) != 1:
                break
            decl = decls[0]
            position = part.opening + 1 + decl.start('name')
            if any(part.opening < a < position < b for a, b in pairs.items()):
                break
            # Declaring or taking the address again could make the earlier write observable.
            shadow = rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){re.escape(var)}\s*(?=[;=,\[])'
            typeof_shadow = rf'\b(?:__typeof__|typeof)\s*\([^;{{}}]*\)\s*\**\s*{re.escape(var)}\s*(?=[;=,\[])'
            if (len(re.findall(shadow, body)) != 1 or re.search(typeof_shadow, body)
                    or re.search(rf'(?<!&)\&(?!&)\s*\(*\s*{re.escape(var)}\b', body)):
                break
            declarations[var] = decl
        else:
            if len(list(re.finditer(rf'\b{re.escape(tmp)}\b', body))) != 3:
                continue
            if len(re.findall(rf'\b{re.escape(label)}\s*:(?!:)', body)) != 1:
                continue
            if not re.search(rf'\b{re.escape(label)}\s*:(?!:)\s*\*\s*{re.escape(ptr)}\s*=\s*{re.escape(value)}\s*;', body):
                continue
            indent = re.match(r'[ \t]*', source[hit.start():hit.start('statement')])[0]
            replacement = (f'{value} = *{src};\n{indent}{ptr} = {src};\n{indent}'
                           f'{value} += 1;\n{indent}goto {label};')
            decl = declarations[tmp]
            offset = part.opening + 1
            out.append((FAMILY, edit(source, [(offset + decl.start(), offset + decl.end(), ''),
                                               (hit.start('statement'), hit.end('statement'), replacement)])))
            staged = (f'{tmp} = *{src};\n{indent}{ptr} = {src};\n{indent}'
                      f'{value} = {tmp};\n{indent}{value} += 1;\n{indent}goto {label};')
            out.append((FAMILY, edit(source, [(hit.start('statement'), hit.end('statement'), staged)])))
            if len(out) >= LIMIT:
                break
    return out


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
