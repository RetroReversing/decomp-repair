"""Inline a shared goto store into both of its increment arms.

A MIPS KMC O1 function retained separate increment loads but merged their
stores. Inlining both stores let the compiler recreate that shape, reducing
the linked diagnostic from 110 to 30; inlining just one arm did not help.
"""
import re

from . import integer_abi
from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'goto_increment_store_inline'


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = _blank(source + '\n' + header)
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:asm|__asm__|setjmp|longjmp|__LINE__|__COUNTER__|__builtin_\w*|class|namespace|template|operator)\b|::', context):
        return []
    part = view(source, name)
    if not part or integer_abi.scalar('s32', context, 'mips') != (32, True):
        return []
    body = part.body
    pairs = brace_pairs(part.clean, part.opening, part.end)
    if pairs is None:
        return []
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', context))
    if macros.intersection(re.findall(IDENT, body)) or re.search(rf'&&\s*{IDENT}\b|\b(?:volatile|_Atomic)\b', body):
        return []
    store = re.compile(rf'\b(?P<label>{IDENT})\s*:(?!:)\s*\*\s*(?P<ptr>{IDENT})\s*=\s*(?P<value>{IDENT})\s*;\s*(?P<next>{IDENT})\s*:(?!:)')
    out = []
    for dest in store.finditer(body):
        label, ptr, value, next_label = (dest[x] for x in ('label', 'ptr', 'value', 'next'))
        if len({label, ptr, value, next_label}) != 4:
            continue
        if any(len(re.findall(rf'\b{re.escape(n)}\s*:(?!:)', body)) != 1 for n in (label, next_label)):
            continue
        # The names must denote the same locals at the arms and at the store.
        valid_locals = True
        for var, star in ((ptr, r'\*'), (value, '')):
            decls = list(re.finditer(rf'(?m)^[ \t]*s32\s*{star}\s*(?P<name>{re.escape(var)})\s*;', body))
            if len(decls) != 1:
                valid_locals = False
                break
            position = part.opening + 1 + decls[0].start('name')
            shadow = rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*){re.escape(var)}\s*(?=[;=,\[])'
            typeof_shadow = rf'\b(?:__typeof__|typeof)\s*\([^;{{}}]*\)\s*\**\s*{re.escape(var)}\s*(?=[;=,\[])'
            if (any(part.opening < a < position < b for a, b in pairs.items())
                    or len(re.findall(shadow, body)) != 1 or re.search(typeof_shadow, body)
                    or re.search(rf'(?<!&)\&(?!&)\s*\(*\s*{re.escape(var)}\b', body)):
                valid_locals = False
                break
        multi = rf'\b{IDENT}\s+[^;{{}}()]*,\s*\**\s*(?:{re.escape(ptr)}|{re.escape(value)})\s*(?:[;=,\[])'
        if not valid_locals or re.search(multi, body):
            continue
        # Offer the combined form only when two distinct increment arms jump
        # to this store, not arbitrary gotos whose branch context may differ.
        jump = re.compile(rf'\b(?P<jump>goto\s+{re.escape(label)}\s*;)')
        arms = []
        for hit in jump.finditer(body):
            before = body[max(0, hit.start() - 300):hit.start()]
            if re.search(rf'\b{re.escape(value)}\s*(?:\+=\s*1|=\s*{IDENT})\s*;\s*$', before):
                arms.append(hit)
        if len(arms) != 2:
            continue
        replacement = f'{{ *{ptr} = {value}; goto {next_label}; }}'
        offset = part.opening + 1
        out.append((FAMILY, edit(source, [(offset + h.start('jump'), offset + h.end('jump'), replacement) for h in arms])))
        return out
    return out


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
