"""Stage one increment pointer before a shared goto store.

A KMC O1 state handler directly increments one slot then jumps past a shared
store. Holding the real slot pointer, computing its increment, and jumping
to that store improved a linked diagnostic from 510 to 445. The exact judge
decides each candidate.
"""
import re

from . import integer_abi, local_flow
from .arm_block_support import brace_pairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'goto_increment_pointer'
LIMIT = 6


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
    local = '__repair_increment_ptr'
    if macros.intersection(re.findall(IDENT, body)) or {'s32', name, local} & macros or re.search(rf'\b{local}\b', clean):
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
    pattern = (rf'(?m)^[ \t]*(?P<stmt>(?P<ptr>{IDENT})\s*=\s*\(\s*(?P<index>{IDENT})\s*\*\s*4\s*\)\s*\+\s*(?P<table>{IDENT})\s*;'
               rf'\s*\n[ \t]*\*\s*(?P=ptr)\s*=\s*\*\s*(?P=ptr)\s*\+\s*1\s*;\s*\n[ \t]*goto\s+(?P<next>{IDENT})\s*;)')
    flow = local_flow.analyze(source, name)
    if not flow:
        return []
    result = []
    for hit in re.compile(pattern).finditer(clean, part.opening + 1, part.end):
        ptr, table, next_label = hit['ptr'], hit['table'], hit['next']
        if clean[part.opening + 1:hit.start('stmt')].rstrip()[-1:] not in ('', ';', '{', '}'):
            continue
        if not re.search(rf'\bextern\s+char\s+{re.escape(table)}\s*\[\s*\]\s*;', _blank(context)):
            continue
        pointer = list(re.finditer(rf'(?m)^[ \t]*s32\s*\*\s*(?P<name>{re.escape(ptr)})\s*;', body))
        if len(pointer) != 1 or re.search(rf'(?<!&)\&(?!&)\s*\(*\s*{re.escape(ptr)}\b', body):
            continue
        ptr_decl = part.opening + 1 + pointer[0].start('name')
        if any(part.opening < a < ptr_decl < b for a, b in pairs.items()):
            continue
        destination = re.compile(rf'(?P<label>{IDENT})\s*:(?!:)\s*\*\s*{re.escape(ptr)}\s*=\s*(?P<temp>{IDENT})\s*;\s*{re.escape(next_label)}\s*:(?!:)')
        for dest in destination.finditer(body):
            label, temp = dest['label'], dest['temp']
            if len({ptr, table, label, temp, next_label}) != 5:
                continue
            decls = list(re.finditer(rf'(?m)^[ \t]*s32\s+(?P<name>{re.escape(temp)})\s*;', body))
            if len(decls) != 1 or re.search(rf'(?<!&)\&(?!&)\s*\(*\s*{re.escape(temp)}\b', body):
                continue
            temp_decl = part.opening + 1 + decls[0].start('name')
            if any(part.opening < a < temp_decl < b for a, b in pairs.items()):
                continue
            shadow = (rf'\b(?:(?:const|volatile|static|struct|unsigned|signed|long|short)\s+)*{IDENT}'
                      rf'\s*(?:\*\s*|\s+)(?P<name>{re.escape(ptr)}|{re.escape(temp)}|{re.escape(table)})\s*(?:[;=,\[)]|$)')
            expected = {ptr: ptr_decl, temp: temp_decl}
            if any(signature + m.start('name') != expected.get(m['name'])
                   for m in re.finditer(shadow, clean[signature:part.end])):
                continue
            multi = rf'\b{IDENT}\s+[^;{{}}()]*,\s*\**\s*(?:{re.escape(ptr)}|{re.escape(temp)}|{re.escape(table)})\s*(?:[;=,\[])'
            if re.search(multi, clean[signature:part.end]):
                continue
            if (len(re.findall(rf'\b{re.escape(label)}\s*:(?!:)', body)) != 1
                    or len(re.findall(rf'\b{re.escape(next_label)}\s*:(?!:)', body)) != 1
                    or re.search(rf'&&\s*(?:{re.escape(label)}|{re.escape(next_label)})\b', body)):
                continue
            # Its new value must be dead after the shared store, including
            # backward gotos or loops which might reach that store again.
            next_node = flow.labels.get(next_label)
            if temp not in flow.names or next_node is None or temp in flow.nodes[next_node].live:
                continue
            # The increment temporary is read only by the shared store.
            store_read = dest.start('temp')
            for occurrence in re.finditer(rf'(?<![\w.>]){re.escape(temp)}\b', body):
                if occurrence.start() in (temp_decl - part.opening - 1, store_read):
                    continue
                if not re.match(r'\s*=(?!=)', body[occurrence.end():]):
                    break
            else:
                at = clean.find('\n', part.opening) + 1
                if not at:
                    continue
                indent = re.match(r'[ \t]*', source[hit.start():hit.start('stmt')])[0]
                replacement = (f'{local} = ({hit["index"]} * 4) + {table};\n{indent}'
                               f'{temp} = *{local} + 1;\n{indent}{ptr} = {local};\n{indent}goto {label};')
                result.append((FAMILY, edit(source, [(at, at, f'    s32 *{local};\n'),
                                                    (hit.start('stmt'), hit.end('stmt'), replacement)])))
                if len(result) >= LIMIT:
                    return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
