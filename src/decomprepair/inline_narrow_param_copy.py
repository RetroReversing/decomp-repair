"""Inline an unchanged word parameter copied to a narrow unsigned local.

A KMC O1 state handler copied a parameter to a halfword local on both paths
before using it once. Casting the unchanged parameter at the use improved a
linked diagnostic from 3605 to 3530. The cast retains the local's type and
conversion; the exact judge decides each child.
"""
import re

from . import integer_abi
from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'inline_narrow_param_copy'
LIMIT = 8


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = source + '\n' + header
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b', context):
        return []
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end]
    if (re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', body)
            or re.search(r'\b(?:asm|__asm__|volatile|_Atomic|setjmp|longjmp)\b', body)):
        return []
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', context))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    if macros.intersection(re.findall(IDENT, body)) or name in macros:
        return []
    if re.search(rf'\b(?!(?:return|else|case|goto)\b){IDENT}(?:\s+|\s*\*+\s*){IDENT}\s*\([^;{{}}]*\)\s*\{{', body):
        return []
    pairs = brace_pairs(clean, part.opening, part.end)
    signatures = list(re.finditer(rf'\b{re.escape(name)}\s*\(', clean[:part.opening]))
    if pairs is None or not signatures:
        return []
    signature = signatures[-1].start()
    params = re.findall(rf'\b(s32|int)\s+({IDENT})(?=\s*[,)]\s*)', clean[signature:part.opening])
    result = []
    for kind, param in params:
        if integer_abi.scalar(kind, _blank(context), 'mips') != (32, True):
            continue
        if re.search(rf'(?<![\w.>]){re.escape(param)}\s*\)*\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))|(?:\+\+|--)\s*\(*\s*\b{re.escape(param)}\b|(?<!&)\&(?!&)\s*\(*\s*{re.escape(param)}\b', body):
            continue
        for decl in re.finditer(rf'(?m)^[ \t]*(?P<type>u8|u16)\s+(?P<local>{IDENT})\s*;[ \t]*$', body):
            narrow, local = decl['type'], decl['local']
            if local == param or narrow in macros or integer_abi.scalar(narrow, _blank(context), 'mips') not in ((8, False), (16, False)):
                continue
            decl_at = part.opening + 1 + decl.start('local')
            if any(part.opening < a < decl_at < b for a, b in pairs.items()):
                continue
            shadow = (rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}'
                      rf'\s*(?:\*\s*|\s+)(?P<name>{re.escape(local)}|{re.escape(param)})\s*(?:[;=,\[)]|$)')
            shadows = list(re.finditer(shadow, clean[signature:part.end]))
            multi = rf'\b{IDENT}\s+[^;{{}}()]*,\s*\**\s*(?:{re.escape(local)}|{re.escape(param)})\s*(?:[;=,\[])'
            if (len(shadows) != 2 or not any(signature + m.start('name') == decl_at for m in shadows)
                    or re.search(multi, clean[part.opening:part.end])):
                continue
            if re.search(rf'(?<!&)\&(?!&)\s*\(*\s*{re.escape(local)}\b', body):
                continue
            assignment = re.compile(rf'(?m)^[ \t]*(?P<stmt>{re.escape(local)}\s*=\s*{re.escape(param)}\s*;)')
            assigned = list(assignment.finditer(body))
            writes = list(re.finditer(rf'(?<![\w.>]){re.escape(local)}\s*\)*\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))|(?:\+\+|--)\s*\(*\s*\b{re.escape(local)}\b', body))
            if not assigned or len(assigned) != len(writes):
                continue
            inside = [(m.start('stmt'), m.end('stmt')) for m in assigned]
            decl_pos = decl.start('local')
            reads = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', body)
                     if m.start() != decl_pos and not any(a <= m.start() < b for a, b in inside)]
            if not reads:
                continue
            edits = [(part.opening + 1 + m.start('stmt'), part.opening + 1 + m.end('stmt'), '(void) 0;') for m in assigned]
            edits += [(part.opening + 1 + m.start(), part.opening + 1 + m.end(), f'(({narrow}) {param})') for m in reads]
            result.append((FAMILY, edit(source, edits)))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
