"""A parameter the target copies only after it has loaded the stack parameters: declared narrow in the original.

GCC 2.x copies the parameters out of their registers in order as the function starts, but a narrow one (`u16 step`) is
first moved as it arrives and converted by instructions emitted after every parameter's: its `move $s5,$a3` comes after
the `lw` of the stack parameters declared after it. A KMC GCC 2.7.2 (`-O1`) text drawer had that one row and the add's
operand order left (65) with `s32 step`, and was exact with `u16 step` and the `u16` position it is added to (370 with
the parameter alone, so the two go in one child).

late_param_narrow
    The target's prologue copies `$a1`-`$a3` into a saved register after a stack parameter's load, and the source declares
    that parameter as a word (`s32`, `u32`, `int`): `u16` and `s16`, together with each word local the parameter is
    added into (`x = step + x`, `x += step`); then the parameter alone. Parameters are taken as one register each, so a
    signature with `double`, `long long` or `float` parameters is left alone.

Hypothesis from one match for why the conversion's move is late; the exact judge decides every child."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, split_args
from .pattern_repairs import close
from .target_call_arity_repairs import LINE

FAMILY = 'late_param_narrow'
FAMILIES = (FAMILY,)
LIMIT = 4
WORD = r'(?:s32|u32|int|unsigned\s+int|unsigned)'
FRAME = re.compile(r'\$sp\s*,\s*\$sp\s*,\s*-(0x[0-9a-fA-F]+|\d+)')
LOAD = re.compile(r'\$\w+\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)')
COPY = re.compile(r'\$(?:s[0-7]|fp|s8)\s*,\s*\$a([1-3])(?:\s*,\s*\$zero)?\s*$')


def late_copies(asm):
    """The positions (1-3) whose copy into a saved register follows a stack parameter's load in the prologue."""
    frame, loaded, late = 0, False, set()
    for line in asm.splitlines():
        hit = LINE.match(line)
        if not hit:
            continue
        op, args = hit['op'], hit['args'].strip()
        if op.startswith(('j', 'b')):
            break
        if op in ('addiu', 'addu') and (found := FRAME.search(args)):
            frame = int(found[1], 0)
        elif op in ('lw', 'lhu', 'lbu', 'lh', 'lb') and frame and (found := LOAD.search(args)):
            loaded |= int(found[1], 0) >= frame + 16
        elif op in ('addu', 'move', 'or') and loaded and (found := COPY.match(args)):
            late.add(int(found[1]))
    return late


def variants(source, name, asm='', arch='mips'):
    if arch != 'mips' or not asm:
        return []
    late = late_copies(asm)
    span = find(source, name)
    if not late or not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    head = re.search(r'\b' + re.escape(name) + r'\s*\(', clean[span[0]:opening]) if opening >= 0 else None
    if not head:
        return []
    start = span[0] + head.end() - 1
    end = close(clean, start)
    if not end:
        return []
    params = [(start + 1 + a, start + 1 + b) for a, b in split_args(clean[start + 1:end - 1])]
    if any(re.search(r'\b(?:f32|f64|float|double|long\s+long|s64|u64)\b', clean[a:b]) for a, b in params):
        return []
    body = clean[opening:span[1]]
    result = []
    for position in sorted(late):
        if position >= len(params):
            continue
        low, high = params[position]
        declared = re.fullmatch(r'\s*(' + WORD + r')\s+(' + IDENT + r')\s*', clean[low:high])
        if not declared:
            continue
        param = declared[2]
        sums = set(re.findall(r'\b(' + IDENT + r')\s*\+=\s*' + param + r'\s*;', body))
        sums |= {a for a, b, c in re.findall(r'\b(' + IDENT + r')\s*=\s*(' + IDENT + r')\s*\+\s*(' + IDENT + r')\s*;', body)
                 if {b, c} == {a, param}}
        locals_ = []
        for local in sorted(sums - {param}):
            hit = re.search(r'(?m)^[ \t]*(' + WORD + r')\s+' + local + r'\s*(?=[;=])', body)
            if hit:
                locals_.append((opening + hit.start(1), opening + hit.end(1)))
        for places in ([*locals_], []) if locals_ else ([],):
            for width in ('u16', 's16'):
                edits = [(low + declared.start(1), low + declared.end(1)), *places]
                text = source
                for a, b in sorted(edits, reverse=True):
                    text = text[:a] + width + text[b:]
                result.append((FAMILY, text))
    return list(dict.fromkeys(result))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'arch'), 'archs': ('mips',)}
