"""The parameters m2c left off the front of a wrapper's signature, passed through, with the stack ones typed.

m2c names parameters by the registers it sees used. A wrapper that hands its first arguments on untouched never
reads `$a0`/`$a1`, so m2c starts at `arg2` and shifts every later parameter into the wrong stack slot:
`void *f(s32 arg2, s32 arg3, s32 arg4, ...)` calling `g(arg2 & 0xFFFF, ...)`. An N64 function was 84% so and exact as
`f(s32 arg0, s32 arg1, u16 arg2, ... )` calling `g(arg0, arg1, arg2, ...)`. The missing parameters are added as `s32`
and passed first to the call that forwards the others; each stack parameter takes the width the target reads it
with (`lhu 0x52($sp)` in a 0x40-byte frame is the 5th parameter, `u16`), and a `u16`/`u8` parameter loses m2c's mask.
"""
import re

from . import m2cfix
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'leading_parameters'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
WIDTHS = {'lhu': 'u16', 'lh': 's16', 'lbu': 'u8', 'lb': 's8', 'lw': 's32'}
MASKS = {'u16': '0xFFFF', 'u8': '0xFF'}


def stack_types(asm):
    """Parameter index -> C type, from the target's loads of its own incoming stack arguments."""
    frame = re.search(r'addiu\s+\$sp\s*,\s*\$sp\s*,\s*-(0x[0-9a-fA-F]+|\d+)', asm or '')
    size = int(frame[1], 0) if frame else 0
    types = {}
    for hit in re.finditer(r'\b(lhu|lh|lbu|lb|lw)\s+\$\w+\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)', asm or ''):
        offset = int(hit[2], 0) - size
        if offset >= 0x10:
            types.setdefault(offset // 4, WIDTHS[hit[1]])
    return types


def variants(source, name, asm):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    params_open = clean.rfind('(', span[0], opening)
    params_close = close(clean, params_open)
    params = [p.strip() for p in m2cfix._split_top_level(source[params_open + 1:params_close - 1])]
    first = re.search(r'\barg(\d+)\s*$', params[0]) if params else None
    if not first or not 0 < int(first[1]) <= 3:
        return []
    missing = int(first[1])
    names = [re.search(IDENT + r'\s*$', p)[0].strip() for p in params]
    # the call that forwards every parameter, in order
    body = clean[opening:end]
    for call in re.finditer(r'\b(' + IDENT + r')\s*\(', body):
        paren = opening + call.end() - 1
        closing = close(clean, paren)
        args = [a.strip() for a in m2cfix._split_top_level(source[paren + 1:closing - 1])] if closing else []
        uses = [re.search(r'\b(arg\d+)\b', a) for a in args]
        if len(args) == len(names) and all(u and u[1] == n for u, n in zip(uses, names)):
            break
    else:
        return []
    callee = call[1]
    types = stack_types(asm)
    new_params = [f's32 arg{i}' for i in range(missing)]
    new_args = [f'arg{i}' for i in range(missing)]
    for index, (param, arg) in enumerate(zip(params, args), start=missing):
        kind = types.get(index)
        name_ = names[index - missing]
        if kind in MASKS and re.fullmatch(r'\(?\s*' + name_ + r'\s*&\s*' + MASKS[kind] + r'\s*\)?', arg):
            new_params.append(f'{kind} {name_}')
            new_args.append(name_)
        elif kind is not None:
            new_params.append(f'{kind} {name_}')
            new_args.append(re.sub(r'^\(\s*s32\s*\)\s*', '', arg))
        else:
            # a register parameter m2c masked: the mask says its width
            mask = re.fullmatch(r'\(?\s*' + name_ + r'\s*&\s*(0xFFFF|0xFF)\s*\)?', arg)
            if mask:
                new_params.append(('u16 ' if mask[1] == '0xFFFF' else 'u8 ') + name_)
                new_args.append(name_)
            else:
                new_params.append(param)
                new_args.append(re.sub(r'^\(\s*s32\s*\)\s*', '', arg))
    text = (source[:paren + 1] + ', '.join(new_args) + source[closing - 1:end] + source[end:])
    text = text[:params_open + 1] + ', '.join(new_params) + text[params_close - 1:]
    # the callee's prototype gains the same number of leading `s32`s
    proto = re.search(r'(?m)^([^\n;{}]*\b' + re.escape(callee) + r'\s*\()([^()]*)\)\s*;', _blank(text[:text.find(name)]))
    if proto and proto[2].strip() and proto[2].strip() != 'void':
        at = proto.start(2)
        text = text[:at] + 's32, ' * missing + text[at:]
    return [(FAMILY, text)]
