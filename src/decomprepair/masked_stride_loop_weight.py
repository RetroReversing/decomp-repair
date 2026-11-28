"""Stage a masked stride and weight its real post-call loop reload.

In one KMC O1 state handler, naming the masked input alone made allocation
worse (530 to 700); nesting the real stride-indexed reload three times in
one-shot scopes then improved it to 510. The scopes are compiler scaffolding.
The exact judge decides the individual and combined children.
"""
import re

from . import goto_load_weight, integer_abi
from .arm_block_support import brace_pairs
from .byte_slot_index_stage import _entry
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'masked_stride_loop_weight'
LIMIT = 32


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = source + '\n' + header
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:volatile|_Atomic|__LINE__|class|namespace|template|operator)\b|::', context):
        return []
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end]
    if (re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', body)
            or re.search(r'\b(?:asm|__asm__|setjmp|longjmp|__builtin_\w*)\b', body)):
        return []
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', context))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    local = '__repair_stride_mask'
    if (macros.intersection(re.findall(IDENT, body)) or {'int', name, local} & macros
            or re.search(rf'\b{local}\b', clean)):
        return []
    if re.search(rf'\b(?!(?:return|else|case|goto)\b){IDENT}(?:\s+|\s*\*+\s*){IDENT}\s*\([^;{{}}]*\)\s*\{{', body):
        return []
    signatures = list(re.finditer(rf'\b{re.escape(name)}\s*\(', clean[:part.opening]))
    pairs = brace_pairs(clean, part.opening, part.end)
    if not signatures or pairs is None:
        return []
    signature = signatures[-1].start()
    params = dict((var, kind) for kind, var in re.findall(rf'\b(s32|int)\s+({IDENT})(?=\s*[,)]\s*)', clean[signature:part.opening]))
    pattern = re.compile(rf'(?m)^[ \t]*(?P<stmt>(?P<stride>{IDENT})\s*=\s*\(\s*(?P<arg>{IDENT})\s*&\s*0[xX][fF]{{4}}\s*\)\s*\*\s*(?:0[xX]64|100)\s*;)')
    result = []
    for hit in pattern.finditer(clean, part.opening + 1, part.end):
        arg, stride = hit['arg'], hit['stride']
        if (arg not in params or arg == stride or not _entry(clean, part.opening + 1, hit.start('stmt'))
                or integer_abi.scalar(params[arg], _blank(context), 'mips') != (32, True)):
            continue
        if re.search(rf'(?<![\w.>]){re.escape(arg)}\s*\)*\s*(?:\+\+|--|(?:<<|>>|[+\-*/%&|^])?=(?!=))|(?:\+\+|--)\s*\(*\s*\b{re.escape(arg)}\b|(?<!&)\&(?!&)\s*\(*\s*{re.escape(arg)}\b', body):
            continue
        declarations = list(re.finditer(rf'(?m)^[ \t]*s32\s+(?P<name>{re.escape(stride)})\s*;', body))
        if len(declarations) != 1 or integer_abi.scalar('s32', _blank(context), 'mips') != (32, True):
            continue
        decl_pos = part.opening + 1 + declarations[0].start('name')
        if any(part.opening < a < decl_pos < b for a, b in pairs.items()):
            continue
        shadow = (rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}'
                  rf'\s*(?:\*\s*|\s+)(?P<name>{re.escape(stride)}|{re.escape(arg)})\s*(?:[;=,\[)]|$)')
        shadows = list(re.finditer(shadow, clean[signature:part.end]))
        if len(shadows) != 2 or not any(signature + m.start('name') == decl_pos for m in shadows):
            continue
        multi = rf'\b{IDENT}\s+[^;{{}}()]*,\s*\**\s*(?:{re.escape(stride)}|{re.escape(arg)})\s*(?:[;=,\[])'
        if re.search(multi, clean[signature:part.end]):
            continue
        decl_at = clean.find('\n', part.opening) + 1
        if not decl_at:
            continue
        indent = re.match(r'[ \t]*', source[hit.start():hit.start('stmt')])[0]
        original = source[hit.start('stmt'):hit.end('stmt')]
        replacement = re.sub(rf'\(\s*{re.escape(arg)}\s*&\s*0[xX][fF]{{4}}\s*\)', local, original, count=1)
        staged = edit(source, [(decl_at, decl_at, f'    int {local};\n'),
                               (hit.start('stmt'), hit.end('stmt'), f'{local} = {arg} & 0xFFFF;\n{indent}{replacement}')])
        result.append((FAMILY, staged))
        if len(result) >= LIMIT:
            return result
        for _, child in goto_load_weight.variants(staged, name, header, flags):
            # Weight only a reload which really indexes through this stride.
            if re.search(rf'do\s*\{{\s*do\s*\{{[^;{{}}]*=\s*\*\s*\(\s*{IDENT}\s*\+\s*{re.escape(stride)}\s*\)', child):
                result.append((FAMILY, child))
                if len(result) >= LIMIT:
                    return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
