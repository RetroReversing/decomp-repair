"""Declare what m2c's draft uses but never declares, so the draft compiles and can be scored.

Two things m2c writes that no compiler accepts as they stand (a 52-function remainder of one N64 game: 14 of them):

* `*((index * 4) + &jtbl_80000A18)`: a read from a table of words that splat named like a jump table but the code
  uses as data. The symbol is declared nowhere. It becomes `((s32 *)jtbl_80000A18)[index]` with the table declared
  `extern s32 jtbl_80000A18[];`.
* `sp`, `sp68`, `unksp10`: the frame's own address and its slots, used as `sp + offset`, `&sp68`, `sp10[0]` while
  only some of the slots (or none) are declared. The frame becomes one `u8 sp[N]` (N from the prologue) and every
  slot a macro that names the bytes it overlays, so a read through `sp + offset` and the named slot are one place.

Each rewrite keeps the draft's behaviour; the compiler and judge decide the rest.
"""
import re

_TYPES = {'M2C_UNK': 's32', 'M2C_UNK8': 's8', 'M2C_UNK16': 's16', 'M2C_UNK32': 's32'}


def _open(source, close):
    """Index of the `(` matching the `)` at `close`, or None."""
    depth = 0
    for i in range(close, -1, -1):
        if source[i] == ')':
            depth += 1
        elif source[i] == '(':
            depth -= 1
            if depth == 0:
                return i
    return None


def _definition(source, name):
    """The line that opens the function `name` (or the first function when it is not given): its span."""
    pattern = (r'^[A-Za-z_][^\n;#]*\b' + re.escape(name) + r'\([^;\n]*\)[ \t]*\{[ \t]*$') if name else \
        r'^[A-Za-z_][^\n;#]*\)[ \t]*\{[ \t]*$'
    return re.search(pattern, source, re.M)


def table_reads(source, name=''):
    tables = []
    for match in reversed(list(re.finditer(r'\) \+ &(jtbl_[0-9A-Fa-f]+)\)', source))):
        opening = _open(source, match.start())
        if opening is None or opening < 2 or source[opening - 2:opening] != '*(':
            continue
        inner = source[opening + 1:match.start()]
        if not inner.endswith(' * 4'):
            continue
        source = source[:opening - 2] + f'((s32 *){match[1]})[{inner[:-4]}]' + source[match.end():]
        tables.append(match[1])
    if not tables:
        return source
    found = _definition(source, name)
    if found is None:
        return source
    lines = ''.join(f'extern s32 {table}[];\n' for table in sorted(set(tables)))
    return source[:found.start()] + lines + source[found.start():]


_SLOT = re.compile(r'\b(unksp|sp)([0-9A-F]+)\b')
_DECLARED = re.compile(r'^[ \t]+(?P<type>(?!(?:return|goto|else|case)\b)[A-Za-z_][\w \t\*]*?)[ \t]*(?P<name>\b(?:unksp|sp)[0-9A-F]+)(?P<array>\[[^\]\n]*\])?;[^\n]*\n',
                       re.M)


def _frame_size(asm, slots):
    found = re.search(r'addiu\s+\$sp,\s*\$sp,\s*-(0x[0-9A-Fa-f]+|\d+)', asm or '')
    if found:
        return int(found[1], 0)
    top = max([slot[0] for slot in slots.values()] or [0])
    return (top + 8 + 7) // 8 * 8


def stack_frame(source, name='', asm=''):
    found = _definition(source, name)
    if found is None:
        return source
    body = source[found.end():]
    declared = {m['name']: m for m in _DECLARED.finditer(body)}
    used = {m[0] for m in _SLOT.finditer(body)}
    bare = re.search(r'\bsp\b', _DECLARED.sub('', body)) is not None
    if not ((used - set(declared)) or bare) or re.search(r'^[ \t]+u8 sp\[', body, re.M):
        return source
    slots = {}
    for slot in sorted(used):
        offset = int(_SLOT.fullmatch(slot)[2], 16)
        decl = declared.get(slot)
        kind = (decl['type'].strip() if decl else 's32')
        slots[slot] = (offset, _TYPES.get(kind, kind), bool(decl and decl['array']) or f'{slot}[' in body)
    macros = ''
    for slot, (offset, kind, array) in sorted(slots.items(), key=lambda item: item[1][0]):
        where = f'sp + 0x{offset:X}'
        macros += f'#define {slot} ' + (f'(({kind} *)({where}))' if array else f'(*({kind} *)({where}))') + '\n'
    body = _DECLARED.sub('', body)
    frame = f'    u8 sp[{_frame_size(asm, slots)}];\n'
    return (source[:found.start()] + macros + source[found.start():found.end()] + '\n' + frame
            + body.lstrip('\n'))


def rewrite(source, name='', asm='', header=''):
    """The rewritten draft, or None when nothing was undeclared. `header` is accepted for the draft chain's
    calling convention and unused."""
    out = stack_frame(table_reads(source, name), name, asm)
    return out if out != source else None
