"""Forward an incoming pointer when the target proves it reaches a call unchanged."""

import re

from .csource import _blank, find
from .integer_repair_support import IDENT, NUMBER, edit, view
from .mips import normalized_integer_lines
from .passthrough_argument_repairs import _entry_a0_reaches


def variants(source, name, header, rows, asm):
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    callees = re.findall(rf'\bjal ({IDENT})\b', target)
    if len(callees) != 1:
        return []
    callee = callees[0]
    if callee == name or not _entry_a0_reaches(asm, callee) or find(source, callee):
        return []
    part = view(source, name)
    if not part or re.search(rf'\b{re.escape(callee)}\s*\(', _blank(header)):
        return []
    signature = re.search(rf'\b(?:void|s32|u32)\s+{re.escape(name)}\s*\(\s*void\s*\*\s*'
                          rf'(?P<arg>{IDENT})(?:\s*,\s*[^()]*)?\)\s*$', part.clean[:part.opening])
    if not signature:
        return []
    arg = signature['arg']
    if re.search(rf'&\s*{re.escape(arg)}\b|(?:\+\+|--)\s*{re.escape(arg)}\b|'
                 rf'\b{re.escape(arg)}\s*(?:[+*/&|^-]?=(?!=)|\+\+|--)', part.body):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*define\s+(' + IDENT + r')\b', source + '\n' + header))
    if macros.intersection((arg, callee, name)):
        return []
    prototypes = list(re.finditer(rf'(?m)^\s*(?:extern\s+)?(?:void|s32|u32|M2C_UNK)\s+'
                                  rf'{re.escape(callee)}\s*\(\s*(?P<type>s32|u32|M2C_UNK)\s*\)\s*;',
                                  part.clean[:part.opening]))
    outside = part.clean[:part.opening] + part.clean[part.end:]
    if len(prototypes) != 1 or len(re.findall(rf'\b{re.escape(callee)}\s*\(', outside)) != 1:
        return []
    calls = list(re.finditer(rf'\b{re.escape(callee)}\s*\(\s*(?P<literal>{NUMBER})\s*\)', part.body))
    if len(calls) != 1 or len(re.findall(rf'\b{re.escape(callee)}\s*\(', part.body)) != 1:
        return []
    m = calls[0]
    start = part.opening + 1
    return [('measured_forward_entry_pointer', edit(source, [
        (*prototypes[0].span('type'), 'void *'),
        (start + m.start('literal'), start + m.end('literal'), arg),
    ]))]
