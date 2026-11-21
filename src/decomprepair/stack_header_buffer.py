"""Restore a serialized stack buffer whose individual fields m2c declares as separate locals."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .large_stack_drafts import _shape
from .measured_stack_drafts import _lines
from .stack_read_retry import _decimal

START = re.compile(
    r'addiu \$sp, \$sp, -(?P<frame>\d+)\naddiu \$a0, \$sp, (?P<base>\d+)\n'
    rf'sw \$ra, (?P<save>\d+)\(\$sp\)\njal (?P<read>{IDENT})\naddiu \$a1, \$zero, (?P<size>\d+)\n'
)
FIELD = re.compile(
    rf'jal (?P<call>{IDENT})\naddiu \$a0, \$sp, (?P<address>\d+)\n'
    rf'lui \$at, %hi\((?P<symbol>{IDENT}) \+ (?P<offset>\d+)\)\n'
    r'(?P<store>sh|sw) \$v0, %lo\((?P=symbol) \+ (?P=offset)\)\(\$at\)\n'
)


def _evidence(asm):
    if 'jal' not in (asm or '') or '%hi' not in asm:
        return None
    lines = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                      if not line.startswith(('glabel ', 'endlabel ')))
    lines = _decimal(lines).replace('addu $v0, $zero, $zero', 'move $v0, $zero')
    start = START.match(lines)
    if not start:
        return None
    frame, base, size, save = (int(start[key]) for key in ('frame', 'base', 'size', 'save'))
    if base < 16 or base % 4 or size > 128 or base + size > save or save + 4 > frame or frame % 8:
        return None
    fields = []
    previous_end = 1  # The source names the read destination separately from the fields.
    pos = start.end()
    while field := FIELD.match(lines, pos):
        width = 2 if field['store'] == 'sh' else 4
        offset = int(field['address']) - base
        if offset < previous_end or offset + width > size:
            return None
        fields.append((field['call'], field['symbol'], int(field['offset']), f's{width * 8}', offset))
        previous_end = offset + width
        pos = field.end()
    if not 2 <= len(fields) <= 8:
        return None
    if lines[pos:] != f'lw $ra, {save}($sp)\nmove $v0, $zero\njr $ra\naddiu $sp, $sp, {frame}':
        return None
    return start['read'], base, size, fields


REGISTERED_START = re.compile(
    r'addiu \$sp, \$sp, -(?P<frame>\d+)\naddiu \$a0, \$sp, (?P<base>\d+)\n'
    r'addiu \$a1, \$zero, (?P<size>\d+)\nsw \$ra, (?P<saved_ra>\d+)\(\$sp\)\n'
    rf'jal (?P<read>{IDENT})\nsw \$s0, (?P<saved_s0>\d+)\(\$sp\)\n'
)
JAL = re.compile(rf'jal ({IDENT})')
ARGUMENT = re.compile(r'addiu \$a0, \$sp, (\d+)')
RELOC_WORD = re.compile(rf'(sh|sw) \$v0, %lo\((?P<symbol>{IDENT}) \+ (?P<offset>\d+)\)\((?P<reg>\$\w+)\)')
SAVED_WORD = re.compile(r'(sh|sw) \$v0, (?P<offset>\d+)\(\$s0\)')


def _writes_register(line, register):
    return re.match(rf'^(?!s[bhwd](?:c1)? |mtc1 )\w+(?:\.\w+)? {re.escape(register)},', line)


def _written_word(lines, previous, start, stop):
    """Bind the returned word to its store, including the next call's delay slot."""
    for i in range(start, stop):
        line = lines[i]
        relocated = RELOC_WORD.fullmatch(line)
        if relocated:
            address = f'%hi({relocated["symbol"]} + {relocated["offset"]})'
            if i > start and lines[i-1] == f'lui {relocated["reg"]}, {address}':
                return (relocated[1], relocated['symbol'], int(relocated['offset']))
            return None
        saved = SAVED_WORD.fullmatch(line)
        if saved:
            # The witnessed base is established by an adjacent hi/lo pair.
            for j in range(i-1, previous-1, -1):
                if not _writes_register(lines[j], '$s0'):
                    continue
                base = re.fullmatch(rf'addiu \$s0, \$s0, %lo\(({IDENT}) \+ (\d+)\)', lines[j])
                if j > previous and base and lines[j-1] == f'lui $s0, %hi({base[1]} + {base[2]})':
                    return saved[1], base[1], int(base[2]) + int(saved['offset'])
                break
            return None
        if _writes_register(line, '$v0'):
            return None
    return None


def _prefaced_evidence(asm):
    if (asm or '').count('jal') < 4 or '%hi' not in asm:
        return None
    raw = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                    if not line.startswith(('glabel ', 'endlabel ')))
    text = _decimal(raw)
    prologue = REGISTERED_START.match(text)
    if not prologue:
        return None
    frame, base, size, saved_s0, saved_ra = (
        int(prologue[key]) for key in ('frame', 'base', 'size', 'saved_s0', 'saved_ra'))
    if not 16 <= base < saved_s0 < saved_ra < frame or base % 4 or frame % 8 or size > 128 or base + size > saved_s0:
        return None
    # Keep direct calls in the straight-line prefix. Stop before the first branch.
    tail = text[prologue.end():]
    cutoff = re.search(r'(?m)^(?:\.L\w+:|(?:b\w*|j|jr|jalr) )', tail)
    lines = (tail[:cutoff.start()] if cutoff else tail).splitlines()
    calls = [(i, hit[1]) for i, line in enumerate(lines) if (hit := JAL.fullmatch(line))]
    if not 2 <= len(calls) <= 8:
        return None
    fields = []
    previous_end, last = 1, -2
    for n, (i, callee) in enumerate(calls):
        if i + 1 == len(lines):
            return None
        # The next call can set a0 in its delay slot or before jal.
        argument = ARGUMENT.fullmatch(lines[i+1])
        if not argument and not _writes_register(lines[i+1], '$a0'):
            for line in reversed(lines[last+2:i]):
                if _writes_register(line, '$a0'):
                    argument = ARGUMENT.fullmatch(line)
                    break
        if not argument:
            return None
        stop = calls[n+1][0] + 2 if n + 1 < len(calls) else len(lines)
        written = _written_word(lines, last+2, i+2, stop)
        if not written:
            return None
        store, symbol, dest = written
        width = 2 if store == 'sh' else 4
        offset = int(argument[1]) - base
        if offset < previous_end or offset + width > size:
            return None
        fields.append((callee, symbol, dest, width, offset))
        previous_end, last = offset + width, i
    return prologue['read'], base, size, fields


def _prototype_edits(part, header, names):
    """Replace only the placeholder pointer types on declarations m2c owns."""
    edits = []
    outside = part.clean[:part.opening+1] + part.clean[part.end:]
    for callee in sorted(names):
        if re.search(rf'\b{callee}\b', header):
            return None
        first_arg = re.compile(
            rf'(?m)^[ \t]*(?:extern[ \t]+)?(?:M2C_UNK|[su]16|[su]32)[ \t]+{callee}'
            r'\s*\(\s*(?P<ptr>M2C_UNK\s*\*)\s*(?:,\s*M2C_UNK\s*)?\);[ \t]*/\* extern \*/[ \t]*$'
        )
        prototypes = list(first_arg.finditer(part.source, 0, part.opening))
        if len(prototypes) != 1 or len(re.findall(rf'\b{callee}\b', outside)) != 1:
            return None
        pointer = prototypes[0].span('ptr')
        if not part.clean[pointer[0]:pointer[1]].strip():
            return None
        edits.append((*pointer, 'void *'))
    return edits


def _rewrite_prefaced(part, header, target, local):
    read, base, size, fields = target
    slots = [f'sp{base:X}', *(f'sp{base + offset:X}' for _, _, _, _, offset in fields)]
    start = part.opening + 1
    cursor = start
    edits = []
    for i, slot in enumerate(slots):
        decl = re.match(rf'\s*(?P<decl>M2C_UNK {slot};)', part.clean[cursor:])
        if not decl or len(re.findall(rf'\b{slot}\b', part.body)) != 2:
            return None
        a, b = decl.span('decl')
        edits.append((cursor+a, cursor+b, f'u8 {local}[{size}];' if i == 0 else ''))
        cursor += decl.end()
    # C may have scalar temporaries for the rest of the function. Do not move or rewrite them.
    while decl := re.match(rf'\s*(?:s32|u32|s16|u16|void\s*\*)\s*{IDENT};', part.clean[cursor:]):
        cursor += decl.end()
    call = re.match(rf'\s*{read}\((?P<addr>&{slots[0]}), (?P<size>{NUMBER})\);', part.clean[cursor:])
    if not call or integer(call['size']) != size:
        return None
    a,b = call.span('addr')
    edits.append((cursor+a, cursor+b, local))
    cursor += call.end()
    for slot, (callee, symbol, dest, width, offset) in zip(slots[1:], fields):
        field = re.match(
            rf'\s*M2C_FIELD\(&{symbol}, [su]{width*8} \*, (?P<dest>{NUMBER})\) = '
            rf'{callee}\((?P<addr>&{slot})\);', part.clean[cursor:])
        if not field or integer(field['dest']) != dest:
            return None
        a,b = field.span('addr')
        edits.append((cursor+a, cursor+b, f'{local} + {offset}'))
        cursor += field.end()
    prototypes = _prototype_edits(part, header, {read, *(callee for callee, *_ in fields)})
    return edit(part.source, edits+prototypes) if prototypes else None



def applies(asm):
    return _evidence(asm) is not None or _prefaced_evidence(asm) is not None


def rewrite(source, name, asm, header=''):
    """Combine the read destination and each observed field address into one byte array."""
    local = '__repair_header_bytes'
    if 'M2C_FIELD' not in source or local in source + header:
        return None
    if not (part := view(source, name)):
        return None
    if not (target := _evidence(asm)):
        alternative = _prefaced_evidence(asm)
        return _rewrite_prefaced(part, header, alternative, local) if alternative else None
    read, base, size, fields = target
    declarations = [f'M2C_UNK sp{base:X};']
    calls = [f'{read}(&sp{base:X}, {size});']
    replacement = [f'{read}({local}, {size});']
    for call, symbol, dest, kind, offset in fields:
        slot = f'sp{base + offset:X}'
        field = f'M2C_FIELD(&{symbol}, {kind} *, {dest})'
        declarations.append(f'M2C_UNK {slot};')
        calls.append(f'{field} = {call}(&{slot});')
        replacement.append(f'{field} = {call}({local} + {offset});')
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    body = ' '.join(_decimal(part.clean[start:end]).split())
    if not _shape(' '.join(declarations + calls + ['return 0;'])).fullmatch(body):
        return None
    edits = _prototype_edits(part, header, {read, *(call for call, *_ in fields)})
    if edits is None:
        return None
    replacement.append('return 0;')
    edits.append((start, end, f'\n    u8 {local}[{size}];\n\n    ' + '\n    '.join(replacement) + '\n'))
    return edit(source, edits)
