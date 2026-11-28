"""Inline immutable parameter masks also assigned in comma expressions.

A KMC O1 state handler kept a masked argument copy on several paths, including
one comma expression. Inlining it improved a linked diagnostic from 5270 to
5200. Each assignment expression keeps its value; only the unescaped local
copy is removed. The exact judge decides the candidate.
"""
import re

from . import integer_abi
from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'masked_comma_copy'
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
            or re.search(r'\b(?:asm|__asm__|volatile|_Atomic|typeof|__typeof__|_Generic|setjmp|longjmp)\b', body)):
        return []
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', context))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    if macros.intersection(re.findall(IDENT, body)) or name in macros:
        return []
    if re.search(rf'\b(?!(?:return|else|case|goto)\b){IDENT}(?:\s+|\s*\*+\s*){IDENT}\s*\([^;{{}}]*\)\s*\{{', body):
        return []
    pairs = brace_pairs(clean, part.opening, part.end)
    if pairs is None:
        return []
    signature = clean[clean.rfind(name, 0, part.opening):part.opening]
    params = re.findall(rf'\b(s32|int)\s+({IDENT})(?=\s*[,)]\s*)', signature)
    result = []
    for kind, param in params:
        if integer_abi.scalar(kind, _blank(context), 'mips') != (32, True):
            continue
        if re.search(rf'(?<![\w.>]){re.escape(param)}\s*\)*\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))|(?:\+\+|--)\s*\(*\s*\b{re.escape(param)}\b|&\s*\(*\s*{re.escape(param)}\b', body):
            continue
        decls = re.compile(rf'(?m)^[ \t]*(?P<type>s32|int)\s+(?P<local>{IDENT})\s*;[ \t]*$')
        for decl in decls.finditer(clean, part.opening + 1, part.end):
            local = decl['local']
            if local == param or integer_abi.scalar(decl['type'], _blank(context), 'mips') != (32, True):
                continue
            if any(part.opening < a < decl.start() < b for a, b in pairs.items()):
                continue
            shadow = rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}\s*(?:\*\s*|\s+)(?P<name>{re.escape(local)}|{re.escape(param)})\s*(?:[;=,\[)]|$)'
            signature_at = clean.rfind(name, 0, part.opening)
            shadows = list(re.finditer(shadow, clean[signature_at:part.end]))
            if len(shadows) != 2 or not any(signature_at + m.start('name') == decl.start('local') for m in shadows):
                continue
            if re.search(rf'&\s*\(*\s*{re.escape(local)}\b', body):
                continue
            assignment = re.compile(rf'(?<![\w.>]){re.escape(local)}\s*=\s*{re.escape(param)}\s*&\s*(?P<mask>0[xX](?:[fF]{{2}}|[fF]{{4}})|255|65535)(?=\s*[,;)])')
            assigned = list(assignment.finditer(body))
            writes = list(re.finditer(rf'(?<![\w.>]){re.escape(local)}\s*\)*\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))|(?:\+\+|--)\s*\(*\s*\b{re.escape(local)}\b', body))
            if not assigned or len(writes) != len(assigned) or len({m['mask'].lower() for m in assigned}) != 1:
                continue
            if not any(re.match(r'\s*,', body[m.end():]) for m in assigned):
                continue  # the ordinary family handles statement-only copies
            inside = [(m.start(), m.end()) for m in assigned]
            local_decl = decl.start('local') - (part.opening + 1)
            reads = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', body)
                     if m.start() != local_decl and not any(a <= m.start() < b for a, b in inside)]
            if not reads:
                continue
            expression = f'({param} & {assigned[0]["mask"]})'
            edits = [(part.opening + 1 + m.start(), part.opening + 1 + m.end(), expression) for m in assigned + reads]
            result.append((FAMILY, edit(source, edits)))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
