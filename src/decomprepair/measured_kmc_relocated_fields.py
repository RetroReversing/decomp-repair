"""Recover direct relocations and pointer typing from measured KMC field accesses."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_PTR = _shape('''
    M2C_FIELD(M2C_FIELD(&@base, void **, @offset), s8 *, 0x2E) = 1;
    M2C_FIELD(M2C_FIELD(&@base, void **, @offset), s8 *, 0x2F) = (s8) ((s32) M2C_FIELD(@arg, s32 *, 0x90) / 2);
''', numbers=('offset',))
_BYTE = _shape('''
    s32 @value;
    if ((u8) M2C_FIELD(&@base, u8 *, @offset) >= 2U) {
        @value = M2C_FIELD(@arg, s32 *, 0xC);
        if (!(@value & 6)) { M2C_FIELD(@arg, s32 *, 0xC) = (s32) (@value | 2); }
    } else { M2C_FIELD(&@base, u8 *, @offset) = (u8) (M2C_FIELD(&@base, u8 *, @offset) + 1); }
''', numbers=('offset',))
_SWAP = _shape('''
    s32 @value;
    M2C_FIELD(&@base, s32 *, @first) = (s32) M2C_FIELD(&@base, s32 *, @second);
    @value = M2C_FIELD(&@base, s32 *, @first);
    M2C_FIELD(&@base, s32 *, @second) = @value;
''', numbers=('first', 'second'))
_ADDRESS = _shape('''
    return M2C_FIELD(&@base, s32 *, @offset) + ((M2C_FIELD((M2C_FIELD(&@base, s32 *, @offset) + (@arg & 0xFFFF)), u8 *, 0x32) * 0x28) + 0x44);
''', numbers=('offset',))


def variants(source, name, header, rows, resolve=None):
    if not resolve or not 10 <= len(rows) <= 16:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    if re.search(r'\bvolatile\b', part.body):
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    symbols = list(dict.fromkeys(re.findall(rf'%hi\(({IDENT})\)', target)))
    draft_text = ' '.join(part.body.split())
    context = part.clean + '\n' + _blank(header)
    start = part.opening + 1
    signature = part.clean[:part.opening]

    def alias(symbol, base, offset):
        original, resolved = resolve(base), resolve(symbol)
        return (original is not None and resolved is not None and original + integer(offset) == resolved
                and not re.search(rf'\b{re.escape(symbol)}\b', context))

    if len(symbols) == 1 and (draft := _PTR.fullmatch(draft_text)):
        symbol = symbols[0]
        sig = re.search(rf'\bvoid {re.escape(name)}\(void \*{draft["arg"]}\)\s*$', signature)
        if (not sig or not alias(symbol, draft['base'], draft['offset'])
                or (f'lui $a0, %hi({symbol})', '') not in changes
                or 'sb $v0, 47($a0)' not in target):
            return []
        expression = f'M2C_FIELD(&{draft["base"]}, void **, {draft["offset"]})'
        body = source[start:part.end-1]
        if body.count(expression) != 2:
            return []
        fixed = edit(source, [(sig.start(), sig.start(), f'extern void *{symbol};\n\n'),
                              (start, part.end-1, body.replace(expression, symbol))])
        return [('measured_relocated_pointer_reloads', fixed)]

    if len(symbols) == 1 and (draft := _BYTE.fullmatch(draft_text)):
        symbol = symbols[0]
        if (not re.search(rf'\bvoid {re.escape(name)}\(void \*{draft["arg"]}\)\s*$', signature)
                or not alias(symbol, draft['base'], draft['offset'])
                or (f'lui $at, %hi({symbol})', '') not in changes
                or 'sltiu $v0, $v1, 2' not in target):
            return []
        expression = f'M2C_FIELD(&{draft["base"]}, u8 *, {draft["offset"]})'
        body = source[start:part.end-1]
        if body.count(expression) != 3:
            return []
        pos = signature.rfind('void ' + name)
        fixed = edit(source, [(pos, pos, f'extern u8 {symbol};\n\n'),
                              (start, part.end-1, body.replace(expression, symbol))])
        return [('measured_relocated_byte_branch', fixed)]

    if len(symbols) == 2 and (draft := _SWAP.fullmatch(draft_text)):
        first, second = symbols
        sig = re.search(rf'\bvoid {re.escape(name)}\(void\)\s*$', signature)
        if (not sig or first == second or integer(draft['first']) == integer(draft['second'])
                or not alias(first, draft['base'], draft['second'])
                or not alias(second, draft['base'], draft['first'])
                or (f'lui $v0, %hi({first})', '') not in changes
                or f'sw $v1, %lo({first})($at)' not in target):
            return []
        body = (f'\n    s32 {draft["value"]};\n\n    {draft["value"]} = {second};\n'
                f'    {second} = {first};\n    {first} = {draft["value"]};\n')
        fixed = edit(source, [(sig.start(), sig.start(), f'extern s32 {first};\nextern s32 {second};\n\n'),
                              (start, part.end-1, body)])
        return [('measured_relocated_word_swap', fixed)]

    if len(symbols) == 1 and (draft := _ADDRESS.fullmatch(draft_text)):
        sig = re.search(rf'\bs32 {re.escape(name)}\(s32 {draft["arg"]}\)\s*$', signature)
        if (not sig or not alias(symbols[0], draft['base'], draft['offset'])
                or ('', 'addiu $v1, $v1, 68') not in changes
                or 'addiu $v0, $v0, 68' not in target
                or re.search(r'\b__repair_table_base\b', context)):
            return []
        expression = f'M2C_FIELD(&{draft["base"]}, s32 *, {draft["offset"]})'
        body = source[start:part.end-1]
        if body.count(expression) != 2:
            return []
        body = body.replace('return ', f'void *__repair_table_base;\n    __repair_table_base = {expression};\n    return ', 1)
        body = body.replace('return ' + expression, 'return __repair_table_base', 1)
        fixed = edit(source, [(start, part.end-1, body)])
        return [('measured_typed_table_base', fixed)]
    return []
