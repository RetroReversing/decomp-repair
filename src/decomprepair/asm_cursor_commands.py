"""A global command cursor's run, rebuilt from the target's own stores when the draft's version of it is scrambled.

libultra's `gSP*(gfx++, ..)` macros compile to a run where the scheduler stores the next cursor before the words of the
command behind it. m2c's draft of such a run keeps the cursor in locals and, where the target uses a register that
still holds an earlier value of the cursor, prints the global again (`M2C_FIELD(gCursor, s32 *, 8)` after
`gCursor = temp + 8`): the draft then writes a word one command too far and leaves another command short, so no
rewrite that reads the draft can recover the commands (`gbi_macro_commands` writes no child). On a 61-instruction SN
GCC 2.8.1 light setup (`-G0 -mips3 -O2`) such a draft scored 845; its three commands written as the target stores them,
each through a command pointer of its own, scored 20, and `independent_statement_swap` finished it.

The commands are read from the assembly: the target's registers are followed along each straight-line stretch (constants,
symbol addresses, a global's loaded value plus an offset), and a global that is stored back advanced by whole 8-byte
commands is a cursor. Both words of every command it passed must be stored exactly once, as a constant, a symbol's
address, or another global's value plus an offset; anything else and nothing is proposed. In the C, the run of statements
that uses the cursor (through the global, a pointer to it, or locals read from it) is replaced by

    {
        CursorCommand *cmd = gCursor++;
        cmd->w0 = ..;
        cmd->w1 = ..;
    }

per command. A listing may still call the cursor by its address name after the project renamed it; then the one
global the draft writes is taken for it (the judge checks the address). The run must be consecutive plain assignments with no call, and its locals used nowhere else, so every
statement removed is one that built the commands the target stores. Reads text only; never compiles or judges."""
import re

from .csource import _blank
from .hand_found_support import HIGH, IDENT, RELOCATED, blocks, calls_in, instructions, mentions_of, number, stmts
from .integer_repair_support import edit, view

FAMILY = 'asm_cursor_commands'
FAMILIES = (FAMILY,)
TYPE = 'CursorCommand'
_STORES = {'sw', 'sh', 'sb', 'swc1', 'sdc1', 'sd', 'swl', 'swr'}
_BRANCH = re.compile(r'(?:b|j)[a-z0-9]*|bc1[tf]l?')
_HALF = re.compile(r'\(\s*(?P<n>-?(?:0[xX][0-9a-fA-F]+|\d+))\s*(?P<op>>>\s*16|&\s*0[xX][fF]{4})\s*\)')
_IMMEDIATE = re.compile(r'-?(?:0[xX][0-9a-fA-F]+|\d+)')
_ADDRESS = re.compile(rf'%lo\(\s*(?P<symbol>{IDENT})\s*(?:\+\s*(?P<add>0[xX][0-9a-fA-F]+|\d+))?\s*\)')
_PLAIN = re.compile(r'(?P<offset>-?(?:0[xX][0-9a-fA-F]+|\d+))?\((?P<base>\$\w+)\)')


def _stretches(asm):
    """The instructions of each straight-line stretch (labels and branches end one; a delay slot belongs to its
    branch's stretch)."""
    found, current, slot = [], [], False
    for line in (asm or '').splitlines():
        text = re.sub(r'/\*.*?\*/', ' ', line).strip()
        if text.endswith(':') or text.startswith(('glabel', 'endlabel', 'dlabel', 'jlabel', 'alabel')):
            if current:
                found.append(current)
            current, slot = [], False
            continue
        for op, args in instructions(text):
            if _BRANCH.fullmatch(op) and op != 'break':
                slot = True
                if op.endswith('l') and op != 'jal':
                    current.append(('branch-likely', []))
                continue
            current.append((op, args))
            if slot:
                found.append(current)
                current, slot = [], False
    if current:
        found.append(current)
    return found


def _immediate(text):
    half = _HALF.fullmatch(text)
    if half:
        value = number(half['n']) & 0xFFFFFFFF
        return (value >> 16) << 16 if half['op'].startswith('>') else value & 0xFFFF
    return number(text) if _IMMEDIATE.fullmatch(text) else None


def _follow(ops):
    """(final values of the stored globals, {global: [(offset, size, value)]} of stores through its advanced values).

    A value is ('const', n), ('addr', symbol, k), ('load', symbol, k) (a global's value plus k) or None."""
    regs, globals_, writes = {'$zero': ('const', 0), '$0': ('const', 0)}, {}, {}
    for op, args in ops:
        if op == 'branch-likely':
            return {}, {}
        if op in _STORES and len(args) == 2:
            value = regs.get(args[0])
            hit = RELOCATED.fullmatch(args[1])
            if hit:
                symbol = hit['symbol']
                globals_[symbol] = value if op == 'sw' and not hit['add'] else None
                continue
            plain = _PLAIN.fullmatch(args[1])
            base = plain and regs.get(plain['base'])
            if base and base[0] == 'load':
                at = base[2] + number(plain['offset'] or '0')
                writes.setdefault(base[1], []).append((at, 4 if op == 'sw' else 0, value))
            continue
        if not args or not args[0].startswith('$'):
            continue
        to, found = args[0], None
        if op == 'lui' and len(args) == 2:
            high = HIGH.match(args[1])
            if high:
                found = ('hi', high['symbol'])
            else:
                value = _immediate(args[1])
                if value is not None:
                    shifted = value if _HALF.fullmatch(args[1]) else (value & 0xFFFF) << 16
                    found = ('const', shifted)
        elif op == 'lw' and len(args) == 2:
            hit = RELOCATED.fullmatch(args[1])
            if hit and not hit['add']:
                symbol = hit['symbol']
                found = globals_[symbol] if symbol in globals_ else ('load', symbol, 0)
        elif op in ('move', 'or', 'addu') and (len(args) == 2 or len(args) == 3 and args[2] in ('$zero', '$0')):
            found = regs.get(args[1])
        elif op in ('addiu', 'ori') and len(args) == 3:
            source = regs.get(args[1])
            address = _ADDRESS.fullmatch(args[2])
            value = _immediate(args[2])
            if address and source and source == ('hi', address['symbol']) and op == 'addiu':
                found = ('addr', address['symbol'], number(address['add'] or '0'))
            elif value is not None and source:
                if source[0] == 'const':
                    word = source[1] | value if op == 'ori' else source[1] + value
                    found = ('const', word & 0xFFFFFFFF)
                elif op == 'addiu' and source[0] in ('load', 'addr'):
                    found = (source[0], source[1], source[2] + value)
        regs[to] = found
    return globals_, writes


def commands(asm):
    """{cursor symbol: [(w0 value, w1 value)]} for each global the target advances by whole commands in one stretch,
    both words of each command stored once. A cursor advanced in two stretches is left out."""
    found, seen = {}, set()
    for ops in _stretches(asm):
        globals_, writes = _follow(ops)
        for symbol, value in globals_.items():
            if not value or value[0] != 'load' or value[1] != symbol or value[2] <= 0 or value[2] % 8:
                continue
            if symbol in seen:
                found.pop(symbol, None)
                continue
            seen.add(symbol)
            words = {}
            for at, size, stored in writes.get(symbol, []):
                if size != 4 or at % 4 or at in words or not 0 <= at < value[2] or stored is None:
                    break
                if stored[0] not in ('const', 'addr', 'load') or stored[0] == 'load' and (
                        stored[1] == symbol or stored[1] in globals_):
                    break
                words[at] = stored
            else:
                if len(words) == value[2] // 4:
                    found[symbol] = [(words[at], words[at + 4]) for at in range(0, value[2], 8)]
    return found


def _spell(value):
    if value[0] == 'const':
        return f'0x{value[1]:X}' if value[1] > 9 else str(value[1])
    kind, symbol, add = value
    if kind == 'addr':
        base = f'(char *)&{symbol}'
    elif add:
        base = f'(char *){symbol}'
    else:
        return f'(unsigned int){symbol}'
    if not add:
        return f'(unsigned int){base}'
    return f'(unsigned int)({base} {"-" if add < 0 else "+"} 0x{abs(add):X})'


def _written_globals(part, header):
    """The declared globals the function itself assigns, directly or through a local that holds their address."""
    declared = set(re.findall(rf'(?m)^[ \t]*extern\s+[^;()\[\]]*?\b({IDENT})\s*;',
                              part.clean[:part.opening] + '\n' + _blank(header or '')))
    body = part.clean[part.opening + 1:part.end - 1]
    found = set()
    for symbol in declared:
        word = re.escape(symbol)
        targets = [rf'(?<![\w.>*]){word}']
        targets += [rf'\(?\*\s*{re.escape(alias)}\)?' for alias in re.findall(rf'\b({IDENT})\s*=\s*&\s*{word}\s*;', body)]
        if any(re.search(rf'(?:^|[;{{}}])\s*{target}\s*=(?!=)', body) for target in targets):
            found.add(symbol)
    return found


def _run(part, cursor):
    """(start, end) of the consecutive plain assignments that use `cursor`, or None."""
    clean = part.clean
    for lo, hi in blocks(part):
        spans = stmts(part, lo, hi)
        names = {cursor}
        related = []
        for index, (start, end) in enumerate(spans):
            text = clean[start:end]
            if not any(mentions_of(text, name) for name in names):
                continue
            hit = re.fullmatch(r'(?P<lhs>[^=;{}]+?)\s*=(?!=)\s*(?P<rhs>[^;{}]*);', text)
            if not hit or calls_in(text, allow=('M2C_FIELD', 'sizeof')):
                return None
            lhs = hit['lhs'].strip()
            if re.fullmatch(IDENT, lhs):
                # only the cursor itself or a local: a global set from the cursor is work the commands don't cover
                if lhs != cursor and not re.search(rf'(?:{IDENT}\s+)+\**\s*{lhs}\s*;', part.body):
                    return None
                names.add(lhs)
            elif not any(mentions_of(lhs, name) for name in names):
                return None
            related.append(index)
        if not related:
            continue
        if related != list(range(related[0], related[-1] + 1)):
            return None
        first, last = spans[related[0]][0], spans[related[-1]][1]
        rest = clean[part.opening + 1:first] + clean[last:part.end]
        for name in names - {cursor}:
            for at in mentions_of(rest, name):
                before = rest[:at]
                before = before[max(before.rfind(c) for c in ';{}') + 1:]
                if not re.fullmatch(rf'\s*(?:{IDENT}\s+)+\**\s*', before):
                    return None
        if mentions_of(rest, cursor):
            return None
        return first, last
    return None


def variants(source, name, header='', arch='mips', asm=''):
    if arch != 'mips':
        return []
    found = commands(asm)
    part = view(source, name) if found else None
    if not part:
        return []
    outside = part.clean[:part.opening] + '\n' + _blank(header or '')
    children = []
    for symbol, words in found.items():
        cursor = symbol
        if not re.search(rf'\b{re.escape(symbol)}\b', source + '\n' + (header or '')):
            # a listing keeps the address name of a global the project renamed since: the one global the draft writes
            written = _written_globals(part, header)
            if not re.fullmatch(r'D_[0-9A-Fa-f]{8}', symbol) or len(written) != 1:
                continue
            cursor = written.pop()
        if not re.search(rf'\b{re.escape(cursor)}\b', outside):
            continue
        used = {value[1] for pair in words for value in pair if value[0] != 'const'}
        if not all(re.search(rf'\b{re.escape(symbol)}\b', source + '\n' + (header or '')) for symbol in used):
            continue
        span = _run(part, cursor)
        if not span:
            continue
        kind = TYPE
        while re.search(rf'\b{kind}\b', source + '\n' + (header or '')):
            kind += '_'
        local = next(n for n in ('cmd', 'gcmd', 'repair_cmd') if not re.search(rf'\b{n}\b', source))
        edits = []
        declared = list(re.finditer(rf'(?m)^[ \t]*extern\s+[^;()\[\]]*?\*\s*{re.escape(cursor)}\s*;', part.clean[:part.opening]))
        elsewhere = part.clean[part.end:]
        typedef = f'typedef struct {{ unsigned int w0; unsigned int w1; }} {kind};\n'
        if len(declared) == 1 and not mentions_of(elsewhere, cursor):
            line = declared[0]
            edits.append((line.start(), line.end(), f'{typedef}extern {kind} *{cursor};'))
            advance = f'{cursor}++'
        else:
            at = source.rfind('\n', 0, source.rfind(name, 0, part.opening)) + 1
            edits.append((at, at, typedef))
            advance = f'(*({kind} **)&{cursor})++'
        first, last = span
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, first) + 1:first])[0]
        written = [f'{{\n{indent}    {kind} *{local} = {advance};\n{indent}    {local}->w0 = {_spell(w0)};\n'
                   f'{indent}    {local}->w1 = {_spell(w1)};\n{indent}}}' for w0, w1 in words]
        edits.append((first, last, f'\n{indent}'.join(written)))
        children.append((FAMILY, edit(source, edits)))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'arch', 'asm'),
          'archs': ('mips',)}
