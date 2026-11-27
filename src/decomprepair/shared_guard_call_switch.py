"""Recover a small switch from an m2c range test and a jump into a shared call.

An N64 function's target compared a byte against three switch cases. Its draft wrote the compare tree as
`if (x == K || (x >= K && x < HI && x >= LO)) { v = A; goto L; } v = B; if (guard) { L: call(v); }`.
Restoring cases K and LO through HI-1, with the guarded call in the default, scored 51,180 -> 50,125 with KMC
GCC 2.7.2 -G0 -mips3 -mgp32 -mfp32 -O2; an -O1 diagnostic scored 8,240 -> 6,970. This is one observation,
not a match. The rewrite requires nonvolatile byte reads, a bounded range, a private label and call-only local,
and target comparisons against the three boundaries. The generated default preserves the original guard.
"""
import re

from . import m2cfix
from .csource import find
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'shared_guard_call_switch'
FAMILIES = (FAMILY,)
LIMIT = 8
NUM = r'(?:0[xX][0-9A-Fa-f]+|0|[1-9][0-9]*)'
_FIELD = re.compile(rf'M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*u8\s*\*\s*,\s*(?P<offset>{NUM})\s*\)')
_MACRO = re.compile(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
                    r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)[ \t]*$')
_CONDITION = re.compile(
    rf'\s*\(\s*@\s*==\s*(?P<key>{NUM})\s*\)\s*\|\|\s*'
    rf'\(\s*\(\s*@\s*>=\s*(?P<floor>{NUM})\s*\)\s*&&\s*'
    rf'\(\s*@\s*<\s*(?P<high>{NUM})\s*\)\s*&&\s*\(\s*@\s*>=\s*(?P<low>{NUM})\s*\)\s*\)\s*'
)
_HEAD = re.compile(r'\bif\s*\(')


def _number(text):
    return int(text, 16 if text.lower().startswith('0x') else 10)


def _evidence(asm, values):
    comparisons = {_number(m[1]) for m in re.finditer(rf'\bslti\s+\$\w+\s*,\s*\$\w+\s*,\s*({NUM})\b', asm or '')}
    return set(values) <= comparisons and bool(re.search(r'\bbeq\b', asm or ''))



def _emit(callee, args, index, value):
    items = list(args)
    items[index] = value
    return callee + '(' + ', '.join(arg.strip() for arg in items) + ');'

def variants(source, name, asm, header=''):
    part, span = view(source, name), find(source, name)
    if not part or not span or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[span[0]:part.end]):
        return []
    macros = source + '\n' + (header or '')
    if (len(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b', macros)) != 1 or not _MACRO.search(macros)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:u8|s32|M2C_UNK)\s*;', macros)
            or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+(?:u8|s32|M2C_UNK)\b', macros)
            or not re.search(r'\btypedef\s+unsigned\s+char\s+u8\s*;', macros)
            or not re.search(r'\btypedef\s+(?:signed\s+)?int\s+s32\s*;', macros)):
        return []
    clean, out = part.clean, []
    for head in _HEAD.finditer(clean, part.opening + 1, part.end):
        cond_end = close(clean, head.end() - 1)
        if not cond_end:
            continue
        condition = clean[head.end():cond_end - 1]
        fields = list(_FIELD.finditer(condition))
        if len(fields) != 4 or len({(f['base'], _number(f['offset'])) for f in fields}) != 1:
            continue
        base = fields[0]['base']
        if re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+{re.escape(base)}\b', macros):
            continue
        normalized = _FIELD.sub('@', re.sub(r'\(\s*s32\s*\)', '', condition))
        tested = _CONDITION.fullmatch(normalized)
        if not tested:
            continue
        key, floor, high, low = (_number(tested[n]) for n in ('key', 'floor', 'high', 'low'))
        if not (0 <= key < 256 and 0 <= floor <= low < high <= 256 and high - low <= 8
                and key not in range(low, high) and _evidence(asm, (floor, high, low))):
            continue
        then = re.match(r'\s*\{', clean[cond_end:part.end])
        if not then:
            continue
        then_open = cond_end + then.end() - 1
        then_end = close(clean, then_open, '{', '}')
        if not then_end:
            continue
        first = re.fullmatch(rf'\s*(?P<var>{IDENT})\s*=\s*(?P<value>{NUM})\s*;\s*goto\s+(?P<label>{IDENT})\s*;\s*',
                             clean[then_open + 1:then_end - 1])
        if not first:
            continue
        var, label = first['var'], first['label']
        rest = re.match(rf'\s*{re.escape(var)}\s*=\s*(?P<value>{NUM})\s*;\s*if\s*\(', clean[then_end:part.end])
        if not rest:
            continue
        second_open = then_end + rest.end() - 1
        second_end = close(clean, second_open)
        if not second_end:
            continue
        block = re.match(r'\s*\{', clean[second_end:part.end])
        if not block:
            continue
        block_open = second_end + block.end() - 1
        block_end = close(clean, block_open, '{', '}')
        if not block_end or re.match(r'\s*else\b', clean[block_end:part.end]):
            continue
        call = re.fullmatch(rf'\s*{re.escape(label)}\s*:\s*(?P<callee>{IDENT})\((?P<args>[^;{{}}]*)\)\s*;\s*',
                            clean[block_open + 1:block_end - 1])
        if not call or re.search(r'/[*/]|#', source[head.start():block_end]):
            continue
        # A macro can hide reads of the local or turn a call into something other than a function call.
        macro_tokens = re.findall(r'\b[A-Za-z_]\w*\b', clean[second_open + 1:block_end])
        if any(token not in ('M2C_FIELD', 'u8', 'u16', 's32') and
               re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+{re.escape(token)}\b', macros)
               for token in macro_tokens):
            continue
        if (len(re.findall(rf'\bgoto\s+{re.escape(label)}\s*;', part.body)) != 1
                or len(re.findall(rf'\b{re.escape(var)}\b', part.body)) != 4
                or re.search(rf'&&\s*{re.escape(label)}\b', part.body)
                or re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+(?:{re.escape(var)}|{re.escape(label)})\b', macros)):
            continue
        decl = list(re.finditer(rf'(?m)^[ \t]*(?:s32|int|M2C_UNK)\s+{re.escape(var)}\s*;[ \t]*\n',
                                clean[part.opening:part.end]))
        if (len(decl) != 1 or any(_number(v) > 127 for v in (first['value'], rest['value']))
                or ('M2C_UNK' in decl[0][0] and not re.search(r'\btypedef\s+s32\s+M2C_UNK\s*;', macros))):
            continue
        args = m2cfix._split_top_level(call['args'])
        positions = [i for i, arg in enumerate(args) if arg.strip() == var]
        if len(positions) != 1:
            continue
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, head.start()) + 1:head.start()])[0]
        field = source[head.end() + fields[0].start():head.end() + fields[0].end()]
        guard = source[second_open + 1:second_end - 1]
        # Match source spelling of the call's arguments (the clean string is only used for offsets).
        start_args = block_open + 1 + call.start('args')
        end_args = block_open + 1 + call.end('args')
        call_args = m2cfix._split_top_level(source[start_args:end_args])
        labels = '\n'.join(f'{indent}case {value:#x}:' for value in [key, *range(low, high)])
        replacement = (f'switch ({field}) {{\n{labels}\n{indent}    {_emit(call["callee"], call_args, positions[0], first["value"])}\n{indent}    break;\n'
                       f'{indent}default:\n{indent}    if ({guard}) {{\n{indent}        {_emit(call["callee"], call_args, positions[0], rest["value"])}\n'
                       f'{indent}    }}\n{indent}    break;\n{indent}}}')
        d = decl[0]
        out.append((FAMILY, edit(source, [(part.opening + d.start(), part.opening + d.end(), ''),
                                         (head.start(), block_end, replacement)])))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
