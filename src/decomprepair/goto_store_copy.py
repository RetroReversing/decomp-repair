"""Copy a shared store into one predecessor and jump to the next label.

A KMC O1 state handler computes an increment in a temporary, then jumps to a
shared store. Writing that store directly in one predecessor and jumping to
the next label improved a linked diagnostic from 3260 to 3245. Only a
non-escaping temporary used by that store qualifies; the judge decides.
"""
import re

from . import integer_abi
from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'goto_store_copy'
LIMIT = 6


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    context = source + '\n' + header
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b|\b(?:volatile|_Atomic)\b', context):
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
    if macros.intersection(re.findall(IDENT, body)) or {'s32', name} & macros:
        return []
    if re.search(rf'\b(?!(?:return|else|case|goto)\b){IDENT}(?:\s+|\s*\*+\s*){IDENT}\s*\([^;{{}}]*\)\s*\{{', body):
        return []
    if integer_abi.scalar('s32', _blank(context), 'mips') != (32, True):
        return []
    pairs = brace_pairs(clean, part.opening, part.end)
    signatures = list(re.finditer(rf'\b{re.escape(name)}\s*\(', clean[:part.opening]))
    if pairs is None or not signatures:
        return []
    signature = signatures[-1].start()
    pattern = (rf'(?m)^[ \t]*(?P<temp>{IDENT})\s*=\s*\*\s*(?P<ptr>{IDENT})\s*\+\s*1\s*;'
               rf'\s*\n[ \t]*goto\s+(?P<label>{IDENT})\s*;')
    result = []
    for hit in re.compile(pattern).finditer(clean, part.opening + 1, part.end):
        temp, ptr, label = hit['temp'], hit['ptr'], hit['label']
        if clean[part.opening + 1:hit.start()].rstrip()[-1:] not in ('', ';', '{', '}'):
            continue  # an unbraced control or label may govern the assignment
        if len({temp, ptr, label}) != 3:
            continue
        # Both locals are function-scoped, with no shadows or multi-declarators.
        declarations = {}
        for spelling, variable in ((r's32\s+', temp), (r's32\s*\*\s*', ptr)):
            found = list(re.finditer(rf'(?m)^[ \t]*{spelling}(?P<name>{re.escape(variable)})\s*;', body))
            if len(found) != 1:
                break
            declarations[variable] = part.opening + 1 + found[0].start('name')
        if len(declarations) != 2 or any(part.opening < a < at < b for at in declarations.values() for a, b in pairs.items()):
            continue
        shadow = (rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}'
                  rf'\s*(?:\*\s*|\s+)(?P<name>{re.escape(temp)}|{re.escape(ptr)})\s*(?:[;=,\[)]|$)')
        if any(signature + m.start('name') != declarations[m['name']]
               for m in re.finditer(shadow, clean[signature:part.end])):
            continue
        multi = rf'\b{IDENT}\s+[^;{{}}()]*,\s*\**\s*(?:{re.escape(temp)}|{re.escape(ptr)})\s*(?:[;=,\[])'
        if re.search(multi, clean[signature:part.end]) or re.search(rf'(?<!&)\&(?!&)\s*\(*\s*{re.escape(temp)}\b', body):
            continue
        dest = re.compile(rf'\b{re.escape(label)}\s*:(?!:)\s*\*\s*{re.escape(ptr)}\s*=\s*{re.escape(temp)}\s*;\s*(?P<next>{IDENT})\s*:(?!:)')
        labels = list(dest.finditer(body))
        if len(labels) != 1 or len(re.findall(rf'\b{re.escape(label)}\s*:(?!:)', body)) != 1:
            continue
        target = part.opening + 1 + labels[0].start()
        if hit.end() >= target:
            continue
        next_label = labels[0]['next']
        if (next_label in ('case', 'default') or next_label in macros
                or len(re.findall(rf'\b{re.escape(next_label)}\s*:(?!:)', body)) != 1
                or re.search(rf'&&\s*(?:{re.escape(label)}|{re.escape(next_label)})\b', body)):
            continue
        # No read of the temporary except the shared store; other assignments are allowed.
        decl_pos = declarations[temp] - part.opening - 1
        store_read = labels[0].start() + labels[0][0].find(temp)
        for occurrence in re.finditer(rf'(?<![\w.>]){re.escape(temp)}\b', body):
            if occurrence.start() in (decl_pos, store_read):
                continue
            tail = body[occurrence.end():]
            if not re.match(r'\s*=(?!=)', tail):
                break
        else:
            statement = source[hit.start():hit.end()]
            statement = re.sub(rf'\b{re.escape(temp)}\s*=\s*\*\s*{re.escape(ptr)}\s*\+\s*1\s*;',
                               f'*{ptr} = *{ptr} + 1;', statement, count=1)
            statement = re.sub(rf'\bgoto\s+{re.escape(label)}\s*;', f'goto {next_label};', statement, count=1)
            result.append((FAMILY, edit(source, [(hit.start(), hit.end(), statement)])))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
