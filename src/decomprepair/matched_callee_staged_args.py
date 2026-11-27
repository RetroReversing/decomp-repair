"""Stage nested call arguments when the target and a matched callee establish their widths.

A draft declared a matched s32-returning helper as s16 and nested it alongside
a second call in an s16 argument. The target calls the helpers in sequence,
keeps the first full word across the second call, and narrows it afterwards.
Correcting the prototype and staging both calls changed a KMC MIPS handler
from 2745 to 2030. Choosing call order can change a draft with side effects;
the target call sequence and the matched callee provide the evidence.
"""
import re

from .integer_repair_support import IDENT, edit, split_args, view
from .pattern_repairs import close

FAMILY = 'matched_callee_staged_args'
FAMILIES = (FAMILY,)


def _target(asm, second):
    lines = [re.sub(r'\s+', ' ', re.sub(r'/\*.*?\*/', '', x).strip()) for x in (asm or '').splitlines()]
    for i, line in enumerate(lines):
        if not re.fullmatch(r'(?i:jal) ' + re.escape(second), line):
            continue
        if not any(re.match(r'(?i:jal) \w+', x) for x in lines[max(0, i - 5):i]):
            continue
        tail = lines[i + 1:i + 8]
        save = next((re.fullmatch(r'(?i:addu) (\$\w+),\s*\$v0,\s*\$zero', x) for x in tail
                     if re.fullmatch(r'(?i:addu) (\$\w+),\s*\$v0,\s*\$zero', x)), None)
        if not save:
            continue
        shift = next((re.fullmatch(r'(?i:sll) (\$\w+),\s*' + re.escape(save[1]) + r',\s*(?:0x10|16)', x)
                      for x in tail if re.fullmatch(r'(?i:sll) (\$\w+),\s*' + re.escape(save[1]) + r',\s*(?:0x10|16)', x)), None)
        if shift and any(re.fullmatch(r'(?i:sra) ' + re.escape(shift[1]) + r',\s*' + re.escape(shift[1]) + r',\s*(?:0x10|16)', x) for x in tail):
            return True
    return False


def variants(source, name, asm, callees='', header=''):
    part = view(source, name)
    if not part or not callees or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.clean[part.opening:part.end]):
        return []
    result = []
    for hit in re.finditer(r'(?m)^(?P<indent>[ \t]*)(?P<outer>' + IDENT + r')\s*\(', part.clean[part.opening:part.end]):
        start = part.opening + hit.start('outer')
        arg_start = part.opening + hit.end() - 1
        stop = close(part.clean, arg_start)
        if not stop or not re.match(r'\s*;', part.clean[stop:]):
            continue
        text = part.clean[arg_start + 1:stop - 1]
        spans = split_args(text)
        if len(spans) != 3:
            continue
        args = [source[arg_start + 1 + a:arg_start + 1 + b].strip() for a, b in spans]
        first = re.fullmatch(r'(' + IDENT + r')\s*\(\s*' + IDENT + r'\s*,\s*' + IDENT + r'\s*\)', args[1])
        second = re.match(r'(' + IDENT + r')\s*\(', args[2])
        if not first or not second or close(args[2], second.end() - 1) != len(args[2]) or not _target(asm, second[1]):
            continue
        if not re.fullmatch(r'\(u8\s*\*\)\s*' + IDENT + r'\s*\+\s*4', args[0]):
            continue
        if re.search(r'\+\+|--|(?<![=!<>])=(?!=)', args[2]):
            continue
        proto = re.search(r'(?m)^\s*s16(?P<space>\s+)' + re.escape(first[1]) + r'\s*\([^;{}]*\)\s*;', part.clean[:part.opening])
        actual = re.search(r'\bs32\s+' + re.escape(first[1]) + r'\s*\([^;{}]*\)\s*\{', callees)
        outer = re.search(r'(?m)^\s*void\s+' + re.escape(hit['outer']) + r'\s*\(\s*void\s*\*\s*,\s*s16\s*,\s*s32\s*\)\s*;', part.clean[:part.opening])
        if not proto or not actual or not outer or re.search(r'\b(?:volume|duration)\b', part.clean[part.opening:part.end]):
            continue
        if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+(?:' + re.escape(first[1]) + '|' + re.escape(second[1]) + r'|s16|s32|u8)\b', source + '\n' + header):
            continue
        replacement = (f'{{ s32 volume = {args[1]}; s32 duration = {args[2]}; '
                       f'{hit["outer"]}({args[0]}, volume, duration); }}')
        semi = stop + re.match(r'\s*;', part.clean[stop:]).end()
        type_at = proto.start() + len(proto.group()) - len(proto.group().lstrip())
        result.append((FAMILY, edit(source, [(type_at, type_at + 3, 's32'), (start, semi, replacement)])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'callees', 'header'), 'archs': ('mips',), 'order': 40}
