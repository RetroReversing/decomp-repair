"""Restore a measured post-store reload in a two-bit flag update."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_flag_reload'

_SOURCE = re.compile(
    rf'\s*if\s*\(\s*\(\s*u32\s*\)\s*\(\s*(?P<call>{IDENT})\s*\(\s*\)\s*-\s*(?P<start>{NUMBER})\s*\)\s*<\s*(?P<limit>{NUMBER})\s*\)\s*\{{\s*'
    rf'(?P<value>{IDENT})\s*=\s*M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*s32\s*\*\s*,\s*(?P<off>{NUMBER})\s*\)\s*\|\s*(?P<mask>{NUMBER})\s*;\s*'
    rf'\}}\s*else\s*\{{\s*(?P=value)\s*=\s*M2C_FIELD\(\s*(?P=base)\s*,\s*s32\s*\*\s*,\s*(?P=off)\s*\)\s*&\s*~\s*(?P=mask)\s*;\s*\}}\s*'
    rf'(?P<old>{IDENT})\s*=\s*M2C_FIELD\(\s*(?P=base)\s*,\s*s32\s*\*\s*,\s*(?P=off)\s*\)\s*;\s*'
    rf'M2C_FIELD\(\s*(?P=base)\s*,\s*s32\s*\*\s*,\s*(?P=off)\s*\)\s*=\s*(?P=value)\s*;\s*'
    rf'if\s*\(\s*(?P=old)\s*&\s*(?P<test>{NUMBER})\s*\)\s*\{{\s*'
    rf'M2C_FIELD\(\s*(?P=base)\s*,\s*s32\s*\*\s*,\s*(?P=off)\s*\)\s*=\s*\(\s*s32\s*\)\s*\(\s*(?P=old)\s*&\s*~\s*(?P=mask)\s*\)\s*;\s*\}}\s*')


def variants(source, name, header, rows):
    part = view(source, name)
    context = source + '\n' + header
    if (not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s32|u32)\s*;', header)
            or '__repair_flag_' in context):
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    body = part.clean[part.opening + 1:end - 1]
    hit = _SOURCE.search(body)
    if not hit or body[hit.end():].strip():
        return []
    prefix = body[:hit.start()]
    if re.sub(rf'\bs32\s+{IDENT}\s*;', '', prefix).strip():
        return []
    value, old, base, call = (hit[k] for k in ('value', 'old', 'base', 'call'))
    if len({value, old, base, call}) != 4:
        return []
    mask, test, offset = (integer(hit[k]) for k in ('mask', 'test', 'off'))
    if not (0 < mask < 0x8000 and 0 < test < 0x10000 and not mask & test):
        return []
    decls = {d['name']: d['type'] for d in locals_for(part)}
    signature = part.clean[part.clean.rfind(name, 0, part.opening):part.opening]
    if (decls.get(value) != 's32' or decls.get(old) != 's32'
            or not re.search(rf'\bvoid\s*\*\s*{re.escape(base)}\s*(?:,|\))', signature)
            or not re.search(rf'\bs32\s+{re.escape(call)}\s*\(\s*\)\s*;', context)
            or re.search(rf'\bs32\s+{re.escape(call)}\s*\([^;{{}}]*\)\s*\{{', part.clean)
            or any(re.search(rf'&\s*{re.escape(n)}\b', body) for n in (value, old, base))):
        return []
    macros = re.findall(r'(?m)^\s*#\s*define[^\n]*', context)
    if any(re.search(rf'\b{re.escape(n)}\b', line) for n in (value, old, base, call) for line in macros):
        return []
    definitions = re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b[^\n]*', context)
    if (len(definitions) != 1 or not re.fullmatch(
            r'\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
            r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)\s*', definitions[0])
            or re.search(r'/[*/]|#', source[part.opening + 1 + hit.start():part.opening + 1 + hit.end()])):
        return []
    lines = [normalized_integer_lines((a, b)) for _, a, b in rows]
    target = [a for a, _ in lines if a]
    candidate = [b for _, b in lines if b]
    # The target writes the chosen flags and then loads that word for the bit
    # test; the candidate loads it before the write. The target also prepares
    # the clear mask in a normal branch delay slot.
    found = False
    for i in range(len(target) - 2):
        store = re.fullmatch(rf'sw (\$\w+), {offset}\((\$s[0-7])\)', target[i])
        if not store:
            continue
        reload = re.fullmatch(rf'lw (\$\w+), {offset}\({re.escape(store[2])}\)', target[i + 1])
        if not reload or not re.fullmatch(rf'andi \$\w+, {re.escape(reload[1])}, {test}', target[i + 2]):
            continue
        if (target[i] in candidate and target[i + 1] in candidate
                and candidate.index(target[i + 1]) < candidate.index(target[i])
                and any(re.fullmatch(r'beqz \$\w+, \d+', target[j])
                        and target[j+1] == f'addiu $v1, $zero, {-mask-1}' for j in range(len(target)-1))):
            found = True
            break
    if not found:
        return []
    field = f'M2C_FIELD({base}, volatile s32 *, {hit["off"]})'
    replacement = (f'\n    __repair_flag_call = {call}();\n    __repair_flag_mask = ~{hit["mask"]};\n'
                   f'    if ((u32) (__repair_flag_call - {hit["start"]}) < {hit["limit"]}) {{\n'
                   f'        {value} = {field} | {hit["mask"]};\n    }} else {{\n'
                   f'        {value} = {field} & __repair_flag_mask;\n    }}\n'
                   f'    {field} = {value};\n    {old} = {field};\n'
                   f'    if ({old} & {hit["test"]}) {{\n'
                   f'        {field} = (s32) ({old} & ~{hit["mask"]});\n    }}\n')
    return [(FAMILY, edit(source, [(part.opening + 1, part.opening + 1,
                                    '\n    s32 __repair_flag_call;\n    s32 __repair_flag_mask;'),
                                   (part.opening + 1 + hit.start(), part.opening + 1 + hit.end(), replacement)]))]
