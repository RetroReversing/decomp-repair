"""Split independent promoted-byte locals across goto-connected blocks.

A MIPS KMC O1 state handler reused one promoted byte slot index in two arms.
The existing reaching-definition analysis proved their values independent;
separate identical ``__typeof__`` locals reduced its linked diagnostic from
225 to 205. The compiler reason is a register-allocation hypothesis.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, view
from .join_tail_arm_split_repairs import web_split

FAMILY = 'typeof_goto_web_split'
LIMIT = 8
_DECL = re.compile(rf'(?P<type>__typeof__\s*\(\s*\*\s*(?P<table>{IDENT})\s*\+\s*0\s*\))\s+(?P<name>{IDENT})\s*;')


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = _blank(source + '\n' + header)
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:volatile|_Atomic|asm|__asm__|setjmp|longjmp|__LINE__|__COUNTER__|__builtin_\w*|class|namespace|template|operator)\b|::', context):
        return []
    part = view(source, name)
    if not part:
        return []
    body = part.body
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', context))
    if macros.intersection(re.findall(IDENT, body)) or re.search(rf'&&\s*{IDENT}\b', body):
        return []
    result = []
    for decl in _DECL.finditer(part.clean, part.opening + 1, part.end):
        var, table = decl['name'], decl['table']
        # Restrict the declaration to function scope, with no shadow or escape.
        prefix = part.clean[part.opening + 1:decl.start()]
        if prefix.count('{') != prefix.count('}') or prefix.rstrip()[-1:] not in ('', ';', '}'):
            continue
        if not re.search(rf'\bextern\s+unsigned\s+char\s+{re.escape(table)}\s*\[\s*\]\s*;', context):
            continue
        possible_decl = (rf'(?:__typeof__\s*\([^;{{}}]*\)|{IDENT}(?:\s+{IDENT})*)'
                         rf'(?:\s+\**\s*|\s*\*+\s*){re.escape(var)}\s*(?=[;=,\[])')
        shadows = list(re.finditer(possible_decl, body))
        if len(shadows) != 1 or re.search(rf'(?<!&)\&(?!&)\s*\(*\s*{re.escape(var)}\b', body):
            continue
        split = web_split(source, name, extra=[decl], only=var)
        if split:
            result.append((FAMILY, split[0]))
            if len(result) >= LIMIT:
                break
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
