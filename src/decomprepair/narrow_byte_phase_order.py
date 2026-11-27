"""Narrow a masked-result and bounded-offset scratch, then order a sibling computation first.

A MIPS handler uses one word local for a call result consumed through `& 255`
and later for a channel offset. The channel is masked to 15, so its product by
16 is at most 240. Declaring that scratch u8 and moving an independent pitch
calculation before the channel setup changed a KMC score from 295 to 260. Both
steps are offered together because narrowing alone scored 320.
"""
import re

from . import pointer_pair_repairs
from .case_temporary_repairs import DECLARATION, _depth_at
from .integer_repair_support import IDENT, edit, view

FAMILY = 'narrow_byte_phase_order'
FAMILIES = (FAMILY,)


def variants(source, name, header=''):
    part = view(source, name)
    if not part or not pointer_pair_repairs.context(source, name, header)[0]:
        return []
    context = source + '\n' + (header or '')
    if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+(?:s32|u8)\b|\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s32|u8)\s*;', context):
        return []
    declarations = list(DECLARATION.finditer(part.clean, part.opening + 1, part.end))
    result = []
    for decl in declarations:
        if decl['type'].strip() != 's32' or _depth_at(part.clean, part.opening + 1, decl.start()):
            continue
        scratch = decl['name']
        if sum(d['name'] == scratch for d in declarations) != 1:
            continue
        body = part.clean[part.opening + 1:part.end]
        if re.search(r'&\s*' + re.escape(scratch) + r'\b|\bsizeof\s*\(?\s*' + re.escape(scratch) + r'\b', body):
            continue
        mentions = list(re.finditer(r'\b' + re.escape(scratch) + r'\b', body))
        if len(mentions) != 6:
            continue
        shape = re.compile(
            r'(?P<phase>' + IDENT + r')\s*=\s*\(\s*(?P<channel>' + IDENT + r')\s*&\s*(?:0[xX][fF]{2}|255)\s*\)\s*;\s*'
            + re.escape(scratch) + r'\s*=\s*(?P=phase)\s*\*\s*(?:0x10|16)\s*;\s*'
            r'(?P<bend>(?P<value>' + IDENT + r')\s*=\s*[^;{}]+;)')
        for hit in shape.finditer(part.clean, part.opening + 1, part.end):
            phase, channel, value = hit['phase'], hit['channel'], hit['value']
            if len({scratch, phase, channel, value}) != 4:
                continue
            phase_decl = next((d for d in declarations if d['name'] == phase and d['type'].strip() == 'u8'), None)
            chan_decl = next((d for d in declarations if d['name'] == channel and d['type'].strip() == 'u8'), None)
            if not phase_decl or not chan_decl:
                continue
            if any(len(re.findall(r'(?m)(?:^|[;{}])[ \t]*[A-Za-z_][\w \t*]*[ \t*]' + re.escape(var) + r'\s*[;=]', part.clean[part.opening:part.end])) != 1
                   for var in (scratch, phase, channel)):
                continue
            if not re.search(r'\b' + re.escape(channel) + r'\s*=\s*' + IDENT + r'\s*&\s*(?:0[xX][fF]|15)\s*;', body):
                continue
            for var in (phase, channel):
                if len(re.findall(r'\b' + re.escape(var) + r'\s*(?:\+\+|--|[+*/%&|^\-]?=(?!=))', body)) != 1:
                    break
                if re.search(r'&\s*' + re.escape(var) + r'\b', body):
                    break
            else:
                bend = hit['bend']
                expr = bend[bend.find('=') + 1:-1]
                if (re.search(r'\b(?:' + '|'.join(map(re.escape, (scratch, phase, value))) + r')\b', expr)
                        or re.search(r'\+\+|--|(?<![=!<>])=(?!=)|' + IDENT + r'\s*\(', expr)):
                    continue
                writes = list(re.finditer(r'\b' + re.escape(scratch) + r'\s*=(?!=)', body))
                if len(writes) != 2:
                    continue
                pan_call = re.search(r'\b' + re.escape(scratch) + r'\s*=\s*(' + IDENT + r')\s*\([^;{}]*\)\s*;', body)
                if not pan_call or not re.search(r'\bs32\s+' + re.escape(pan_call[1]) + r'\s*\([^;{}]*\)\s*;', part.clean[:part.opening]):
                    continue
                if len(re.findall(r'\b' + re.escape(scratch) + r'\s*&\s*(?:0[xX][fF]{2}|255)\b', body)) != 1:
                    continue
                if len(re.findall(r'\b' + re.escape(scratch) + r'\s*\+\s*M2C_FIELD\s*\(', body)) != 2:
                    continue
                # Same initialized values: reorder a pure independent assignment.
                setup = source[hit.start():hit.start('bend')]
                bend_text = source[hit.start('bend'):hit.end('bend')]
                indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, hit.start()) + 1:hit.start()]).group()
                replacement = bend_text + '\n' + indent + setup.rstrip()
                result.append((FAMILY, edit(source, [(decl.start('type'), decl.start('type') + 3, 'u8'),
                                                      (hit.start(), hit.end(), replacement)])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 40}
