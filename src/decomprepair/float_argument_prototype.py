"""A float passed as its bit pattern in an integer register: the callee's prototype says `f32`, the call a float literal.

m2c has no prototype for a callee it never saw defined, so a float the game passed (`lui $a2, 0x41A0`) is written as the
integer `0x41A00000` into a parameter it types as `M2C_UNK` or `s32`. The bits and the register are the same as the
original's `f32` parameter and `20.0f` argument, but GCC 2.7.2 schedules a float constant in an argument register
differently from an integer constant: the `addiu $a0, $zero, 0xA` of the first argument comes after the `lui`/`ori`
pairs only with the floats. Two matched N64 functions (`sn-n64-281` and `gcc-2.7.2-kmc`-style o32 profiles alike):

    M2C_UNK f(M2C_UNK, M2C_UNK, M2C_UNK, M2C_UNK, s32, s32, s32);   f(0xA, 0x4542B000, 0x451EA000, 0x4423C000, ...)
 -> void f(s32, f32, f32, f32, s32, s32, s32);                      f(0xA, 3115.0f, 2538.0f, 655.0f, ...)      60 -> 0

    f32 g(f32, f32, M2C_UNK);   g(temp, M2C_FIELD(arg0, f32 *, 8), 0x41A00000)
 -> f32 g(f32, f32, f32);       g(temp, M2C_FIELD(arg0, f32 *, 8), 20.0f)                                     120 -> 0

(the float literal alone, with the old prototype, scored 260: the literal would be converted by value, so both edits
go together). `float_argument_bits` (float_bit_argument_repairs) already made the first edit, but only for a profile
that spells `-mgp32`/`-mabi=32` (this one does not: `-G0 -mips3 -O2 -mfp64`) and never for a callee whose first argument
is a float (the second case).

What is checked instead of the flags is the target itself: its `jal callee` is preceded by a `lui $aN` (and its `ori`)
that builds exactly the literal's bits in the register of that argument's position (`$a1`-`$a3`), so the argument
travels in an integer register in the original too. o32 gives that register to any argument from the third on, and to the
second when the first is not a float; a position the target filled from FP registers has no such `lui`. Only o32 flags
are required to be absent from the exclusion list (`-mabi=eabi`, `-mabi=n32`/`64`, `-mgp64`, `-m64`), and only
prototypes the source itself declares (a header's can't be edited). Without an assembly the explicit o32 flags
(`-mgp32`, `-mabi=32`) stand in for the evidence, as in `float_argument_bits`.

Zeros say nothing by their bits. But GCC 2.7.2 sets each integer zero from `$zero`, while two `0.0f` arguments are
one constant it puts in the first register and copies (`addu $a1,$zero,$zero; addu $a2,$a1,$zero`, and the same after a
`lui` for `0.5f, 0.5f`). The target's copy therefore counts as evidence for the positions it joins: three KMC GCC 2.7.2
`-O1` calls of one callee, `f(0x41, 0, 0, 0, 0, 0xA0)` one row off, were exact with `f32` parameters and `0.0f, 0.0f`.

A literal is a "round" float when it is finite, its exponent is in a sane range (roughly 1e-4 .. 1e7) and the value is
the float nearest to a short decimal (3115.0f, 20.0f, 0.5f): `float_text`. Every call to the callee in the function must
pass such a literal (or zero) at the position, since any other value would be converted, not reinterpreted. Children:
all changeable positions of all callees at once, each callee's positions together, then each position alone (at most
`LIMIT`)."""
import re

from .csource import _blank, find
from .float_bit_argument_repairs import FLOATING, INTEGER_PARAMETER, TYPE_WORDS, _prototypes, float_text
from .integer_repair_support import split_args
from .pattern_repairs import close
from .target_call_arity_repairs import IDENT, LINE

FAMILY = 'float_argument_prototype'
FAMILIES = (FAMILY,)
LIMIT = 8
COPY = re.compile(r'\$(a[1-3])\s*,\s*\$(a[1-3]|zero)(?:\s*,\s*\$zero)?\s*$')
O32_FLAGS = {'-mgp32', '-mabi=32'}
OTHER_ABI_FLAGS = {'-m64', '-mgp64', '-mabi=64', '-mabi=n32', '-mabi=eabi'}
ARGUMENT_POSITIONS = (1, 2, 3)  # `$a1`-`$a3`: the registers the evidence reads (the first argument is float_argument_bits')
LITERAL = re.compile(r'\s*(?:\(\s*(?:(?:un)?signed\s+)?(?:short|char|int|long|s8|u8|s16|u16|s32|u32)\s*\)\s*)?'
                     r'(-?)(0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*')
LUI = re.compile(r'\$(a[0-3])\s*,\s*\(?\s*(0[xX][0-9a-fA-F]+)\s*(?:>>\s*16\s*)?\)?')
ORI = re.compile(r'\$(a[0-3])\s*,\s*\$(a[0-3])\s*,\s*\(?\s*(0[xX][0-9a-fA-F]+)\s*(?:&\s*0[xX][fF]{4}\s*)?\)?')
STORES = {'sw', 'sb', 'sh', 'sd', 'swc1', 'sdc1', 'swl', 'swr', 'sc'}
ENDS_BLOCK = {'j', 'jr', 'jal', 'jalr', 'b', 'beq', 'bne', 'beqz', 'bnez', 'blez', 'bgtz', 'bltz', 'bgez', 'bc1t', 'bc1f',
              'beql', 'bnel', 'beqzl', 'bnezl'}


def evidence(asm, copies=None):
    """{callee: {argument position: {bits the target's `lui`/`ori` builds in that argument's register at a call}}}.

    A register copy (`addu $a2,$a1,$zero`) carries the bits along; `copies`, when given, collects {callee: {positions that
    shared one register's value that way, the source's and the destination's}}."""
    code = []
    for line in asm.splitlines():
        if re.fullmatch(r'\s*[.\w]+:\s*', line):
            code.append(('label', ''))
        elif (hit := LINE.match(line)) and hit['op'] not in {'glabel', 'endlabel'}:
            code.append((hit['op'], hit['args'].strip()))
    found = {}
    registers = {}
    shared = []  # (source register, destination register) of each live copy

    def end(register):
        registers.pop(register, None)
        shared[:] = [pair for pair in shared if register not in pair]

    def step(op, args):
        if op in ('addu', 'move', 'or') and (hit := COPY.match(args)) and not (op != 'move' and args.count(',') != 2):
            to, of = hit[1], hit[2]
            end(to)
            if of == 'zero':
                registers[to] = 0
            elif of in registers:
                registers[to] = registers[of]
                shared.append((of, to))
        elif op == 'lui' and (hit := LUI.match(args)):
            end(hit[1])
            value = int(hit[2], 16)
            registers[hit[1]] = (value >> 16 if value > 0xFFFF or '>>' in args else value) << 16
        elif op == 'ori' and (hit := ORI.match(args)) and hit[1] == hit[2] and hit[1] in registers:
            registers[hit[1]] |= int(hit[3], 16) & 0xFFFF
        elif op not in STORES:
            for register in re.findall(r'\$(a[0-3])\b', args.split(',')[0]):
                end(register)  # (any other write to the register ends what the lui built)

    for at, (op, args) in enumerate(code):
        if op == 'label':
            registers.clear()
            shared.clear()
        elif op in ('jal', 'jalr'):
            if op == 'jal' and at + 1 < len(code):
                step(*code[at + 1])  # the delay slot runs before the callee
            if op == 'jal':
                for position in ARGUMENT_POSITIONS:
                    if f'a{position}' in registers:
                        found.setdefault(args, {}).setdefault(position, set()).add(registers[f'a{position}'])
                if copies is not None and shared:
                    copies.setdefault(args, set()).update(int(register[1]) for pair in shared for register in pair)
            registers.clear()
            shared.clear()
        elif op in ENDS_BLOCK:
            registers.clear()
            shared.clear()
        else:
            step(op, args)
    return found


def _bits(text):
    literal = LITERAL.fullmatch(text)
    if not literal:
        return None
    value = int(literal[2], 0)
    return -value & 0xFFFFFFFF if literal[1] else value


def _calls(clean, callee, opening, end):
    calls = []
    for hit in re.finditer(r'(?<![\w.>])' + re.escape(callee) + r'\s*\(', clean[opening:end]):
        start = opening + hit.end() - 1
        close_at = close(clean, start)
        if not close_at:
            return None
        calls.append([(start + 1 + a, start + 1 + b) for a, b in split_args(clean[start + 1:close_at - 1])])
    return calls


def variants(source, name, header='', arch='mips', asm='', flags=()):
    flags = set(flags or ())
    if arch != 'mips' or flags & OTHER_ABI_FLAGS:
        return []
    copies = {}
    seen = evidence(asm, copies) if asm else {}
    if not seen and not flags & O32_FLAGS:
        return []  # neither the target nor the profile says the arguments travel in integer registers
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    declared_elsewhere = set(re.findall(r'\b(' + IDENT + r')\s*\(', _blank(header)))
    groups = []  # per callee: [(position, changes)], each position's literal edits (the prototype's apart)
    for callee, (low, high) in _prototypes(clean, span).items():
        if callee == name or callee in declared_elsewhere:
            continue
        if seen and callee not in seen:
            continue
        params = [(low + a, low + b) for a, b in split_args(clean[low:high])]
        texts = [clean[a:b] for a, b in params]
        unlisted = not clean[low:high].strip()  # `f32 g();`: the calls say how many there are
        if any(re.search(r'\b(?:f64|double)\b', t) or '...' in t for t in texts):
            continue  # doubles take two registers (and an alignment), varargs promote: the arguments would move
        calls = _calls(clean, callee, opening, span[1])
        if not calls:
            continue
        if unlisted:
            if len({len(args) for args in calls}) != 1:
                continue
            texts = ['s32'] * len(calls[0])
        if any(len(args) != len(texts) for args in calls):
            continue
        positions = []
        for index in ARGUMENT_POSITIONS:
            if index >= len(texts) or (index == 1 and FLOATING.search(texts[0])):
                continue  # (a float first argument puts the second in $f14: the argument would move)
            already = bool(re.search(r'\b(?:f32|float)\b', texts[index]))
            if not already and not INTEGER_PARAMETER.fullmatch(texts[index]):
                continue
            changes, useful = [], False
            for args in calls:
                a, b = args[index]
                bits = _bits(clean[a:b])
                text = float_text(bits) if bits is not None else None
                if text is None or (bits and seen and bits not in seen[callee].get(index, ())):
                    break
                # (zeros alone say nothing, unless the target copies one into the other: an integer zero is set from
                # `$zero` each time, a float constant is one register the second argument copies)
                useful |= bool(bits) or index in copies.get(callee, ())
                changes.append((a, b, ' ' + text if clean[a:a + 1] == ' ' else text))
            else:
                if useful:
                    positions.append((index, changes, already))
        if positions:
            groups.append((callee, (low, high), params, texts, unlisted, positions))

    def apply(chosen):
        """chosen: [(group, indexes)] -> the source with those positions' literals and prototype parameters edited."""
        edits = []
        for (callee, (low, high), params, texts, unlisted, positions), indexes in chosen:
            retyped = {i for i, _, already in positions if i in indexes and not already}
            for index, changes, _ in positions:
                if index in indexes:
                    edits.extend(changes)
            if not retyped:
                continue
            if unlisted:
                edits.append((low, high, ', '.join('f32' if i in retyped else 's32' for i in range(len(texts)))))
                continue
            for index in retyped:
                last = texts[index].split()[-1]
                lead = re.match(r'\s*', texts[index])[0]
                edits.append((params[index][0], params[index][1], lead + 'f32' + (' ' + last if last not in TYPE_WORDS else '')))
        text = source
        for start, end, replacement in sorted(edits, reverse=True):
            text = text[:start] + replacement + text[end:]
        return text

    result, singles = [], []
    whole = [(group, {i for i, _, _ in group[5]}) for group in groups]
    if len(whole) > 1:
        result.append(apply(whole))
    for entry in whole:
        if len(entry[1]) > 1:
            result.append(apply([entry]))
        singles.extend(apply([(entry[0], {index})]) for index in sorted(entry[1]))
    result.extend(singles)
    unique = list(dict.fromkeys(text for text in result if text != source))
    return [(FAMILY, text) for text in unique[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'arch', 'asm', 'flags'),
          'archs': ('mips',)}
