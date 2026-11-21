"""Recover MIPS call operands lost when drafting C."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips_returns import instructions
from .pattern_repairs import close

_ANNOTATION = re.compile(r'/\*\s*[0-9a-fA-F]+\s+([0-9a-fA-F]{8})\s+([0-9a-fA-F]{8})\s*\*/\s*(.*)')
_DIRECT = re.compile(r'jal\s+(?P<label>\.L(?P<address>[0-9a-fA-F]{8}))\s*$')
_SAVED = r'\$s[0-7]'
_COPY = re.compile(
    rf'addiu \$sp, \$sp, -(?P<frame>{NUMBER})\n'
    rf'sw (?P<base>{_SAVED}), (?P<base_slot>{NUMBER})\(\$sp\)\n'
    r'(?:addu (?P=base), \$a0, \$zero|move (?P=base), \$a0)\n'
    rf'sw (?P<size>{_SAVED}), (?P<size_slot>{NUMBER})\(\$sp\)\n'
    rf'sw \$ra, (?P<ra_slot>{NUMBER})\(\$sp\)\n'
    r'jal memcpy\n(?:addu (?P=size), \$a2, \$zero|move (?P=size), \$a2)\n'
    r'addu \$v0, (?P=base), (?P=size)\n'
    r'lw \$ra, (?P=ra_slot)\(\$sp\)\n'
    r'lw (?P=base), (?P=base_slot)\(\$sp\)\n'
    r'lw (?P=size), (?P=size_slot)\(\$sp\)\n'
    r'jr \$ra\naddiu \$sp, \$sp, (?P=frame)'
)
_MEMCPY = re.compile(
    r'\bvoid\s*\*\s*memcpy\s*\(\s*void\s*\*\s*(?:\w+)?\s*,\s*'
    r'(?:const\s+void|void\s+const)\s*\*\s*(?:\w+)?\s*,\s*'
    r'(?:size_t|u32|unsigned\s+(?:int|long))(?:\s+\w+)?\s*\)\s*;'
)


def variants(source, name, asm, header, toolchain):
    """Yield at most one repair for a generated draft with an evidenced broken call."""
    if '.L' in source and (candidate := rename_local_calls(source, name, asm, header)):
        return [('initial_external_call_labels', candidate)]
    if toolchain == 'gcc-2.7.2-kmc' and 'memcpy' in source:
        if candidate := _memcpy_wrapper(source, name, asm, header):
            return [('initial_forwarded_memcpy', candidate)]
    return []


def rename_local_calls(source, name, asm, header=''):
    """Name out-of-function direct call targets by the address encoded in the JAL."""
    if not asm or '.L' not in asm:
        return None
    part = view(source, name)
    if not part:
        return None
    decoded = [m for line in asm.splitlines() if (m := _ANNOTATION.search(line))]
    if not decoded:
        return None
    addresses = [int(match[1], 16) for match in decoded]
    first, last = min(addresses), max(addresses)
    targets = {}
    for instruction in decoded:
        if not (call := _DIRECT.fullmatch(instruction[3])):
            continue
        pc, word, address = int(instruction[1], 16), int(instruction[2], 16), int(call['address'], 16)
        encoded = ((pc + 4) & 0xF0000000) | ((word & 0x03FFFFFF) << 2)
        if word >> 26 != 3 or address != encoded or first <= address <= last:
            continue
        targets[call['label']] = f'func_{address:08X}'
    edits = []
    context = _blank(header) + '\n' + part.clean
    for label, symbol in targets.items():
        if re.search(rf'\b{symbol}\b', context) or re.search(rf'(?m)^\s*{re.escape(label)}:', asm):
            continue
        token = rf'(?<![\w.]){re.escape(label)}\b(?=\s*\()'
        stub = re.search(rf'(?m)^[ \t]*(?:extern\s+)?[\w *]+\s+(?P<label>{token})\s*\([^()]*\)\s*;'
                         r'[ \t]*/\* extern \*/', source[:part.opening])
        if not stub or not re.match(token, part.clean[stub.start('label'):]):
            continue
        uses = list(re.compile(token).finditer(part.clean, part.opening + 1, part.end))
        if not uses:
            continue
        edits.append((*stub.span('label'), symbol))
        edits.extend((*use.span(), symbol) for use in uses)
    return edit(source, edits) if edits else None


def _memcpy_wrapper(source, name, asm, header):
    if not asm or not (part := view(source, name)):
        return None
    target = _COPY.fullmatch('\n'.join(' '.join(row.split()) for row in instructions(asm)))
    if (not target or target['base'] == target['size']
            or len({integer(target[slot]) for slot in ('base_slot', 'size_slot', 'ra_slot')}) != 3):
        return None
    signature = re.search(
        rf'\b[su]32\s+{re.escape(name)}\s*\(\s*[su]32\s+(?P<base>{IDENT})\s*,'
        rf'(?P<size>\s*[su]32\s+{IDENT})\s*\)\s*$', part.clean[:part.opening])
    end = close(part.clean, part.opening, '{', '}')
    if not signature or not end:
        return None
    size = signature['size'].split()[-1]
    start = part.opening + 1
    body = re.fullmatch(rf'\s*(?P<call>memcpy\(\s*\))\s*;\s*'
                        rf'return\s+{signature["base"]}\s*\+\s*{size}\s*;\s*',
                        part.clean[start:end - 1])
    if not body or size == signature['base']:
        return None

    prefix = part.clean[:part.opening]
    stub = re.search(r'(?m)^[ \t]*(?:M2C_UNK|s32)\s+memcpy\s*\(\s*\)\s*;[^\S\n]*\n', prefix)
    rest = prefix[:stub.start()] + prefix[stub.end():] if stub else prefix
    context = _blank(header) + '\n' + rest
    declarations = list(_MEMCPY.finditer(context))
    if len(declarations) > 1 or (re.search(r'\bmemcpy\b', context) and not declarations):
        return None
    if declarations:
        declaration = declarations[0]
        remainder = context[:declaration.start()] + context[declaration.end():]
        if re.search(r'\bmemcpy\b', remainder):
            return None
    incoming = 'arg1'
    if re.search(rf'\b{incoming}\b', part.clean + '\n' + _blank(header)):
        return None
    params = 'void *arg1,' + source[slice(*signature.span('size'))]
    call = f'memcpy((void *){signature["base"]}, {incoming}, {size})'
    edits = [(*signature.span('size'), ' ' + params),
             (start + body.start('call'), start + body.end('call'), call)]
    prototype = '' if declarations else 'void *memcpy(void *, const void *, unsigned int);\n'
    if stub:
        edits.append((stub.start(), stub.end(), prototype))
    elif prototype:
        # Insert a declaration before the definition when m2c omitted one.
        at = signature.start()
        edits.append((at, at, prototype))
    return edit(source, edits)
