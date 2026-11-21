"""Recover a standalone word when m2c turns a relocated update into a field."""

import re

from .csource import find
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import abi_register_names
from .mips_addresses import resolved
from .sdk_io_repairs import instructions
from .target_call_arity_repairs import _instructions

TARGET = re.compile(
    rf'lui \$v0, %hi\((?P<base>{IDENT})(?: \+ (?P<offset>{NUMBER}))?\)\n'
    r'lw \$v0, %lo\((?P=base)(?(offset) \+ (?P=offset))\)\(\$v0\)\n'
    rf'lui \$v1, \((?P<multiplier>{NUMBER}) >> 16\)\n'
    r'ori \$v1, \$v1, \((?P=multiplier) & 0xFFFF\)\n'
    r'mult \$v0, \$v1\nmflo \$v0\n'
    rf'addiu \$v1, \$v0, (?P<increment>{NUMBER})\n'
    rf'addiu \$v0, \$v0, (?P<result>{NUMBER})\n'
    rf'sra \$v0, \$v0, (?P<shift>{NUMBER})\n'
    r'lui \$at, %hi\((?P=base)(?(offset) \+ (?P=offset))\)\n'
    r'sw \$v1, %lo\((?P=base)(?(offset) \+ (?P=offset))\)\(\$at\)\n'
    rf'jr \$ra\nandi \$v0, \$v0, (?P<mask>{NUMBER})'
)

DRAFT = re.compile(
    rf'\s*s32 (?P<product>{IDENT});\s*'
    rf'(?P=product) = (?P<read>M2C_FIELD\(&(?P<base>{IDENT}), s32 \*, (?P<offset>{NUMBER})\))'
    rf' \* (?P<multiplier>{NUMBER});\s*'
    rf'(?P<write>(?P=read)) = \(s32\) \((?P=product) \+ (?P<increment>{NUMBER})\);\s*'
    rf'return \(\(s32\) \((?P=product) \+ (?P<result>{NUMBER})\) >> (?P<shift>{NUMBER})\)'
    rf' & (?P<mask>{NUMBER});\s*'
)


def _target(asm):
    if 'mflo' not in asm or 'andi' not in asm or '%hi(' not in asm:
        return None
    lines = (f'{op} {" ".join(args.split())}' for op, args in _instructions(abi_register_names(asm)))
    return TARGET.fullmatch('\n'.join(lines))


def applies(asm):
    return _target(asm) is not None


def rewrite(source, name, asm, header='', resolve=None):
    """Use a typed alias for the word read and written by the original function."""
    if resolve is None or 'M2C_FIELD' not in source or not (target := _target(asm)):
        return None
    part = view(source, name)
    if not part or not re.search(rf'\bs32\s+{re.escape(name)}\(void\)\s*$', part.clean[:part.opening]):
        return None
    start = part.opening + 1
    stop = part.clean.rfind('}', start, part.end)
    draft = DRAFT.fullmatch(part.clean, start, stop)
    if not draft or any(integer(draft[field]) != integer(target[field])
                        for field in ('multiplier', 'increment', 'result', 'shift', 'mask')):
        return None
    bases = [resolve(binding['base']) for binding in (target, draft)]
    if None in bases:
        return None
    address = bases[0] + integer(target['offset'] or '0')
    if address != bases[1] + integer(draft['offset']) or not 0 <= address <= 0xFFFFFFFF or address % 4:
        return None
    words = instructions(asm)
    if len(words) != 13:
        return None
    addresses = resolved(b''.join(word.to_bytes(4, 'big') for word in words))
    # The two relocations must resolve in the words at the actual load and store.
    if (addresses.get(4), addresses.get(40)) != (address, address):
        return None
    alias = f'D_{address:08X}'
    if resolve(alias) != address or re.search(rf'\b{alias}\b', source + '\n' + header):
        return None
    definition = find(source, name)[0]
    return edit(source, [
        (definition, definition, f'extern s32 {alias};\n\n'),
        (*draft.span('read'), alias),
        (*draft.span('write'), alias),
    ])
