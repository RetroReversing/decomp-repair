"""Float arguments m2c passed as their bit patterns, written back as float literals with a float parameter.

m2c sees `lui $a1, 0x437A` before a call to a function it has no prototype for, and writes the argument as the
integer `0x437A0000`. When the original passed `250.0f` to an `f32` parameter, the bits and the register are the
same under o32 (after an integer first argument, floats travel in integer registers), but gcc 2.7.2 schedules the
argument set-up differently: in an N64 game the `lui` came before the other arguments' moves only with the float.
The rewrite retypes the callee's parameter in the source's own prototype to `f32` and writes every call's
argument there as the float with those bits, so the bits each call passes are unchanged.

Only o32 (`-mgp32`, `-mabi=32`): where floats have registers of their own (the PS2's EABI, or a float first
argument here) the change would move the argument. Only literals whose bits are a short, ordinary float; only
prototypes the source itself declares (the header can't be edited); and only when every call to the callee passes
such a literal (or zero) at that position, since anything else would be converted by value instead.
"""
import re
import struct

from .csource import _blank, find
from .integer_repair_support import IDENT, split_args
from .pattern_repairs import close

# The label observed_repairs' narrower version uses (fixed constants, `s32`/`int` prototypes only), so ranking that
# learned to prefer it applies here too.
FAMILY = 'float_argument_bits'
FAMILIES = (FAMILY,)
LIMIT = 4
INTEGER_PARAMETER = re.compile(r'\s*(?:(?:signed|unsigned|const)\s+)*(?:s32|u32|int|long|M2C_UNK|M2C_UNK32|unsigned)'
                               r'(?:\s+' + IDENT + r')?\s*')
TYPE_WORDS = {'signed', 'unsigned', 'const', 's32', 'u32', 'int', 'long', 'M2C_UNK', 'M2C_UNK32'}
FLOATING = re.compile(r'\b(?:f32|f64|float|double)\b')
LITERAL = re.compile(r'\s*(0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*')


def float_text(bits):
    """`bits` as a C float literal, when they are an ordinary float with a short decimal form; else None."""
    if bits == 0:
        return '0.0f'
    exponent = bits >> 23 & 0xFF
    if not 1 <= bits <= 0xFFFFFFFF or exponent in (0, 0xFF) or not 0x70 <= exponent <= 0x96:
        return None  # zero/denormal, inf/NaN, or outside roughly 1e-4 .. 1e7: an integer, not a float's bits
    value = struct.unpack('>f', struct.pack('>I', bits))[0]
    for digits in range(1, 8):
        text = f'{value:.{digits}g}'
        if struct.unpack('>I', struct.pack('>f', float(text)))[0] == bits:
            break
    else:
        return None
    return repr(float(text)) + 'f'  # (250.0f, 0.5f, 0.001f: Python's shortest form of the decimal found)


def _prototypes(clean, span):
    """Each prototype the source declares outside the function: name -> (start, end of its parameter list)."""
    found = {}
    pattern = r'(?m)^[ \t]*(?:extern\s+)?(?:' + IDENT + r'[\s*]+)+(' + IDENT + r')\s*\(([^;{}()]*)\)\s*;'
    for hit in re.finditer(pattern, clean):
        if span[0] <= hit.start() < span[1]:
            continue
        found.setdefault(hit[1], []).append((hit.start(2), hit.end(2)))
    return {name: places[0] for name, places in found.items() if len(places) == 1}


def variants(source, name, header='', arch='mips', flags=()):
    flags = set(flags)
    if arch != 'mips' or not flags & {'-mgp32', '-mabi=32'} or flags & {'-m64', '-mgp64', '-mabi=64', '-mabi=n32', '-mabi=eabi'}:
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    declared_elsewhere = set(re.findall(r'\b(' + IDENT + r')\s*\(', _blank(header)))
    edits = []  # one rewrite per (callee, parameter): its edits
    for callee, (low, high) in _prototypes(clean, span).items():
        if callee == name or callee in declared_elsewhere:
            continue
        params = [(low + a, low + b) for a, b in split_args(clean[low:high])]
        texts = [clean[a:b] for a, b in params]
        if not texts or FLOATING.search(texts[0]) or any(FLOATING.search(t) and 'double' in t or '...' in t for t in texts):
            continue  # a float first argument puts floats in $f12/$f14; doubles and varargs move arguments too
        calls = []
        for hit in re.finditer(r'(?<![\w.>])' + re.escape(callee) + r'\s*\(', clean[opening:span[1]]):
            start = opening + hit.end() - 1
            end = close(clean, start)
            if not end:
                break
            args = [(start + 1 + a, start + 1 + b) for a, b in split_args(clean[start+1:end-1])]
            calls.append(args)
        if not calls or any(len(args) != len(params) for args in calls):
            continue
        # (a float first argument goes in $f12 and moves the later ones; alone, it moves nothing: an N64 function
        # called `f(0x3F800000)` where the game passed 1.0f in $f12, 94.8% until the prototype said `f32`)
        for index in range(0 if len(params) == 1 else 1, len(params)):
            if not INTEGER_PARAMETER.fullmatch(texts[index]):
                continue
            changes, useful = [], False
            for args in calls:
                a, b = args[index]
                literal = LITERAL.fullmatch(clean[a:b])
                value = int(literal[1], 0) if literal else None
                text = float_text(value) if value is not None else None
                if text is None:
                    break
                useful |= value != 0
                changes.append((a, b, ' ' + text if clean[a:a+1] == ' ' else text))
            else:
                if useful:
                    last = texts[index].split()[-1]
                    param = 'f32' + (' ' + last if last not in TYPE_WORDS else '')
                    lead = re.match(r'\s*', texts[index])[0]
                    changes.append((params[index][0], params[index][1], lead + param))
                    edits.append(changes)
    result = []
    def apply(groups):
        text = source
        for start, end, replacement in sorted((c for g in groups for c in g), reverse=True):
            text = text[:start] + replacement + text[end:]
        return text
    if len(edits) > 1:
        result.append((FAMILY, apply(edits)))  # every float-bit argument at once: what the original most likely had
    result.extend((FAMILY, apply([group])) for group in edits)
    return result[:LIMIT]
