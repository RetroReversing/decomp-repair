"""Restore the typed load and early failure return of a measured uncached read."""

import re

from .integer_repair_support import IDENT, edit, locals_for, refs, view
from .mips import abi_register_names

SAVED = r'\$s[0-7]'
REG = r'\$\w+'
WITNESS = re.compile(
    rf'(?m)^jal (?P<callee>{IDENT})\n(?P<delay>nop|(?:addu|move) {SAVED}, \$a1(?:, \$zero)?)\n'
    rf'bnez \$v0, (?P<exit>\.L\w+)\naddiu \$v0, \$zero, -(?:0x)?1\n'
    r'lui \$v0, %hi\(D_A0000000\)\n'
    rf'or \$v0, (?P<addr>{SAVED}), \$v0\n'
    rf'lw (?P<value>{REG}), %lo\(D_A0000000\)\(\$v0\)\n'
    r'(?:addu \$v0, \$zero, \$zero|move \$v0, \$zero)\n'
    rf'sw (?P=value), (?:0x0|0)?\((?P<out>{SAVED})\)\n'
    r'(?P=exit):$'
)
TAIL = re.compile(
    rf'(?P<status>{IDENT}) = -1; if \((?P<callee>{IDENT})\(\) == 0\) {{ '
    rf'(?P=status) = 0; \*(?P<out>{IDENT}) = \*(?:\(s32 \*\))?\((?P<addr>{IDENT}) \| '
    r'(?:\(s32\)\s*&D_A0000000|0xA0000000[Uu]?)\); } return (?P=status);'
)


def _evidence(asm):
    if 'D_A0000000' not in asm:
        return None
    lines = [' '.join(re.sub(r'/\*.*?\*/|#.*', '', line).split())
             for line in abi_register_names(asm).splitlines()]
    asm = '\n'.join(filter(None,lines))
    hit = WITNESS.search(asm)
    if not hit or hit['addr'] == hit['out'] or hit['value'] in ('$zero', '$v0',hit['addr'],hit['out']):
        return None
    before = asm[:hit.start()]
    if hit['delay'] != 'nop':
        out = re.escape(hit['out'])
        if not re.fullmatch(rf'(?:addu {out}, \$a1, \$zero|move {out}, \$a1)', hit['delay']):
            return None
        # The delay slot consumes the original incoming output pointer.
        if re.search(r'(?m)^(?:[bj]\w*\s|\w+ \$a1(?:,|$))', before):
            return None
        before += hit['delay'] + '\n'
    for address, incoming in ((hit['addr'],'$a0'),(hit['out'],'$a1')):
        reg, arg = re.escape(address),re.escape(incoming)
        moves = re.findall(rf'(?m)^(?!sw |sd |sh |sb |b\w* |j\w* )\w+ {reg}, [^\n]+',before)
        if len(moves) != 1 or not re.fullmatch(rf'(?:addu {reg}, {arg}, \$zero|move {reg}, {arg})',moves[0]):
            return None
    return hit['callee']


def applies(asm):
    return _evidence(asm) is not None


def rewrite(source, name, asm, resolve=None):
    """Keep earlier checks and their calls. Change only the witnessed final read and return."""
    if (('D_A0000000' not in source and '0xA0000000' not in source)
            or not (callee := _evidence(asm))):
        return None
    if resolve is not None and resolve('D_A0000000') not in (None, 0xA0000000):
        return None
    part = view(source,name)
    if part is None:
        return None
    signature = re.search(rf'\bs32\s+{re.escape(name)}\(\s*s32\s+({IDENT}),\s*s32\s*\*\s*({IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None
    end = len(part.clean[:part.end].rstrip())-1
    # Search from each statement boundary so earlier diagnostics remain untouched.
    for hit in re.finditer(rf'(?m)^[ \t]*(?={IDENT}\s*=\s*-1\s*;)',part.clean[part.opening+1:end]):
        start = part.opening+1+hit.start()
        tail = TAIL.fullmatch(' '.join(part.clean[start:end].split()))
        if not tail or tail['callee'] != callee or (tail['addr'],tail['out']) != signature.groups():
            continue
        previous = part.clean[part.opening+1:start].rstrip()
        if not previous.endswith(('}', ';')):
            continue
        local = next((decl for decl in locals_for(part) if decl['name'] == tail['status'] and decl['type'] == 's32'),None)
        if not local or any(ref.start() < start for ref in refs(part,local)):
            continue
        text = f'''    if ({callee}() != 0) {{
        return -1;
    }}
    *{tail['out']} = *(s32 *)({tail['addr']} | 0xA0000000);
    return 0;
'''
        return edit(source,[(local.start(),local.end(),''),(start,end,text)])
    return None
