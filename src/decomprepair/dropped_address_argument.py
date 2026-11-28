"""A trailing argument m2c dropped that the target sets to a symbol's address.

A callee that only hands its second argument on (`void wrap(s32 bank) { relocate(); .. }`) is byte-exact with one
parameter, so the draft, given that matched definition, calls it with one argument and the address the caller passed is
gone. The caller's own bytes still say what it passed, in each call's straight run and its delay slot:

    lui $a1, %hi(D_A); lw $a0, 0x10($s1); jal wrap; addiu $a1, $a1, %lo(D_A)          wrap(x, D_A);
    lw $a0, 0x730($s1); jal wrap; addu $a1, $s0, $zero        ($s0 holds D_B)         wrap(y, D_B);

`stripped_call_arguments` reads the same evidence only for calls the C leaves empty, `loaded_call_argument` only
arguments loaded from memory. Here, for each callee the C calls as often as the target does (paired in order), a call
with n arguments gets `$an`, `$an+1`, .. while the target sets each of them to a symbol's address since the previous
call. The callee's prototype is emptied (`f()`), and a symbol the source never names is declared `extern u8 SYM[];`.
One child with every callee, then one per callee. MIPS only; the judge decides.

A loader on SN GCC 2.8.1 (`-G0 -mips3 -O2`) made 101 such calls; without the addresses nothing else in its draft can
reach the target.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, calls, edit, split_args, view
from .target_call_arity_repairs import _instructions

FAMILY = 'dropped_address_argument'
FAMILIES = (FAMILY,)

LIMIT = 4
_ARGUMENTS = ('a0', 'a1', 'a2', 'a3')
_NO_WRITE = ('sb', 'sh', 'sw', 'sd', 'swc1', 'sdc1', 'swl', 'swr', 'j', 'jr', 'b', 'beq', 'bne', 'beqz', 'bnez',
             'beql', 'bnel', 'beqzl', 'bnezl', 'blez', 'bgtz', 'bltz', 'bgez', 'mult', 'multu', 'div', 'divu', 'nop')
_HI = re.compile(r'\$(\w+)\s*,\s*%hi\(\s*(\w+)\s*\)')
_LO = re.compile(r'\$(\w+)\s*,\s*\$(\w+)\s*,\s*%lo\(\s*(\w+)\s*\)')
_COPY = re.compile(r'\$(\w+)\s*,\s*\$(\w+)(?:\s*,\s*\$zero)?')


def _sites(asm):
    """{callee: [{argument register: symbol whose address it holds}]}, one entry per `jal`, in order."""
    found = {}
    held = {}   # register -> ('hi' | 'address', symbol)
    fresh = {}  # argument register -> what it was set to since the previous call
    pending = None

    def apply(op, operands):
        target = re.match(r'\$(\w+)', operands)
        if not target or op in _NO_WRITE:
            return
        register, value = target[1], None
        if op == 'lui' and (m := _HI.fullmatch(operands)):
            value = ('hi', m[2])
        elif op == 'addiu' and (m := _LO.fullmatch(operands)):
            if held.get(m[2]) == ('hi', m[3]):
                value = ('address', m[3])
        elif op in ('move', 'addu', 'or', 'daddu') and (m := _COPY.fullmatch(operands)) \
                and (op == 'move') == (operands.count('$') == 2):
            value = held.get(m[2])
        held[register] = value
        if register in _ARGUMENTS:
            fresh[register] = value

    for op, operands in _instructions(asm):
        if pending is not None:  # the delay slot
            apply(op, operands)
            found.setdefault(pending, []).append(
                {register: value[1] for register, value in fresh.items() if value and value[0] == 'address'})
            pending, fresh = None, {}
            for register in list(held):
                if not re.fullmatch(r's[0-8]|fp', register):
                    del held[register]
        elif op == 'jal':
            pending = operands.strip()
        else:
            apply(op, operands)
    return found


def _declare(text, name, symbols):
    """`extern u8 SYM[];` before the function for each symbol the source never names."""
    missing = [s for s in symbols if not re.search(rf'\b{s}\b', _blank(text[:view(text, name).opening]))]
    if not missing:
        return text
    head = re.search(rf'(?m)^[^\n;]*\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{', _blank(text))
    if not head:
        return text
    return text[:head.start()] + ''.join(f'extern u8 {s}[];\n' for s in missing) + text[head.start():]


def _apply(source, name, header, part, choice):
    edits, symbols = [], []
    declared = _blank(header + '\n' + source[:part.opening])
    for callee, added in choice.items():
        for (_start, end), extra in added:
            if not extra:
                continue
            passed = []
            for symbol in extra:
                scalar = re.search(rf'(?m)^[ \t]*extern\b[^;\[(\n]*\b{symbol}[ \t]*;', declared)
                passed.append(f'&{symbol}' if scalar else symbol)
                if symbol not in symbols and not re.search(rf'\b{symbol}\b', declared):
                    symbols.append(symbol)
            edits.append((end, end, ''.join(f', {p}' for p in passed)))
        prototype = re.search(rf'(?m)^[ \t]*[A-Za-z_][\w \t]*?[ \t*]{re.escape(callee)}[ \t]*(\([^;{{}}]*\))[ \t]*;',
                              _blank(source[:part.opening]))
        if prototype and prototype[1] != '()':
            edits.append((prototype.start(1), prototype.end(1), '()'))
    return _declare(edit(source, edits), name, symbols)


def variants(source, name, asm=None, arch=None, header=''):
    """Proposals: each call's dropped symbol addresses written back."""
    if arch not in (None, 'mips') or not asm:
        return []
    part = view(source, name)
    if not part:
        return []
    usable = {}
    for callee, registers in _sites(asm).items():
        if not re.fullmatch(IDENT, callee):
            continue
        found = list(calls(part, callee))
        if len(found) != len(registers):
            continue
        added = []
        for (start, end), values in zip(found, registers):
            arguments = split_args(part.source[start:end]) if part.clean[start:end].strip() else []
            extra = []
            for register in _ARGUMENTS[len(arguments):]:
                if register not in values:
                    break
                extra.append(values[register])
            # `f()` is `stripped_call_arguments`' case.
            added.append(((start, end), extra if arguments else []))
        if any(extra for _span, extra in added):
            usable[callee] = added
    choices = [{callee: added} for callee, added in sorted(usable.items())]
    if len(usable) > 1:
        choices.insert(0, usable)
    return [(FAMILY, _apply(source, name, header, part, choice)) for choice in choices[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'arch', 'header'),
          'archs': ('mips',), 'order': 100}
