"""Recover m2c's untyped dispatch-table calls from a measured MIPS word load and jalr."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .measured_stack_drafts import _lines
from .pattern_repairs import close

REG = r'\$\w+'
RELOC = rf'(?P<symbol>{IDENT})(?: \+ (?P<offset>{NUMBER}))?'
ARG_SETUP = r'(?:(?:move|addu|addiu|lw|lhu|andi) \$a[0-3], [^\n]+\n){0,2}'
TAIL = ARG_SETUP + r'jalr (?P=call)\n(?P<delay>[^\n]+)'
IN_PLACE = re.compile(
    rf'sll (?P<index>{REG}), (?P<input>{REG}), (?:2|0x2)\n'
    rf'lui (?P<base>{REG}), %hi\((?P<address>{RELOC})\)\n'
    r'addu (?P=base), (?P=base), (?P=index)\n'
    rf'lw (?P<call>{REG}), %lo\((?P=address)\)\((?P=base)\)\n' + TAIL
)
HOISTED = re.compile(
    rf'sll (?P<index>{REG}), (?P<input>{REG}), (?:2|0x2)\n'
    rf'addu (?P<word>{REG}), (?P=index), (?P<base>\$s[0-7])\n'
    rf'lw (?P<call>{REG}), (?:0|0x0)?\((?P=word)\)\n' + TAIL
)
BASE = re.compile(rf'lui (?P<base>\$s[0-7]), %hi\((?P<address>{RELOC})\)\n'
                  r'addiu (?P=base), (?P=base), %lo\((?P=address)\)')

FIELD = rf'M2C_FIELD\({IDENT}, u16 \*, {NUMBER}\)'
INDEX = rf'\((?P<index>{FIELD}|{IDENT}) \* (?:4|0x4)\)'
C_ADDRESSES = (
    re.compile(rf'&(?P<symbol>{IDENT}) \+ {INDEX}'),
    re.compile(rf'(?:\(char \*\))?&(?P<symbol>{IDENT}) \+ (?P<offset>{NUMBER}) \+ {INDEX}'),
    re.compile(rf'{INDEX} \+ \((?:\(char \*\))?&(?P<symbol>{IDENT}) \+ (?P<offset>{NUMBER})\)'),
)
INVOKE = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?:(?P<result>{IDENT}) = )?(?P<call>\*(?:\(s32 \*\))?\()')


def _evidence(asm):
    if not asm or 'jalr' not in asm:
        return None
    lines = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                      if not line.startswith(('glabel ', 'endlabel ')))
    lines = re.sub(r'(?m)^addu (\$\w+), (\$\w+), \$zero$', r'move \1, \2', lines)
    if len(re.findall(r'(?m)^jalr\s', lines)) != 1:
        return None
    table = dispatch = IN_PLACE.search(lines)
    if not dispatch:
        dispatch = HOISTED.search(lines)
        if not dispatch:
            return None
        bases = [hit for hit in BASE.finditer(lines, 0, dispatch.start()) if hit['base'] == dispatch['base']]
        if len(bases) != 1:
            return None
        table = bases[0]
        before = lines[:table.start()].splitlines()
        between = lines[table.end():dispatch.start()].splitlines()
        if len(before) > 8 or any(re.match(r'[bj]', op) for op in before):
            return None
        if any(re.match(rf'^(?!b|j|sw |sh |sb |sd |mtc1 )\w+ {re.escape(table["base"])}(?:,|$)', op)
               for op in between):
            return None
    return lines, table['symbol'], integer(table['offset'] or '0'), dispatch


def applies(asm):
    return _evidence(asm) is not None


def _same_address(source, offset, symbol, addend, resolve):
    if source == symbol:
        return offset == addend
    if resolve is None:
        return False
    base, target = resolve(source), resolve(symbol)
    return base is not None and target is not None and base + offset == target + addend


def _queue_boundary(part, lines, call, finish):
    """Keep the return-address save before direct-call setup in a terminal message wrapper."""
    start = re.match(
        rf'addiu \$sp, \$sp, -{NUMBER}\nsw \$s0, {NUMBER}\(\$sp\)\nmove \$s0, \$a0\n'
        rf'sw \$ra, {NUMBER}\(\$sp\)\naddiu \$a0, \$s0, (?P<queue>{NUMBER})\n'
        rf'addiu \$a1, \$sp, (?P<local>{NUMBER})\njal (?P<callee>{IDENT})\n'
        rf'addiu \$a2, \$zero, (?P<flag>{NUMBER})\n', lines)
    if not start or not re.search(r'\njalr \$v0\nnop\n(\.L\w+):\nj \1\nnop\n', lines):
        return None
    prefix = part.clean[part.opening+1:call.start()]
    draft = re.fullmatch(
        rf'\s*M2C_UNK (?P<local>{IDENT});\s*{start["callee"]}\({IDENT} \+ (?P<queue>{NUMBER}), '
        rf'&(?P=local), (?P<flag>{NUMBER})\);\s*', prefix)
    if (not draft or integer(draft['queue']) != integer(start['queue'])
            or integer(draft['flag']) != integer(start['flag'])
            or draft['local'] != f'sp{integer(start["local"]):X}'
            or not re.fullmatch(r'\s*(?P<label>\w+):\s*goto (?P=label);\s*', part.clean[finish:part.clean.rfind('}', finish, part.end)])):
        return None
    indent = call['indent']
    return part.opening + 1 + prefix.index(start['callee'] + '('), f'do {{ }} while (0);\n{indent}'


def _resident_table(part, lines, call, finish, table):
    """Hold a table base across the measured receive/dispatch loop."""
    queue = re.search(
        rf'\nsw \$ra, {NUMBER}\(\$sp\)\n(?P<prepare>addiu \$a0, \$s0, (?P<offset>{NUMBER}))\n'
        rf'(?P<label>\.L\w+):\naddiu \$a1, \$sp, {NUMBER}\njal (?P<receive>{IDENT})\n', lines)
    if not queue or f'\nj {queue["label"]}\n{queue["prepare"]}\n' not in (lines + '\n'):
        return []
    prefix = part.clean[part.opening+1:call.start()]
    entry = re.fullmatch(
        rf'\s*M2C_UNK {IDENT};\s*void \*(?P<queue>{IDENT});\s*'
        rf'(?P<prepare>(?P=queue) = (?P<object>{IDENT}) \+ (?P<offset>{NUMBER});)\s*'
        rf'(?P<label>{IDENT}):\s*{queue["receive"]}\((?P=queue), &{IDENT}, {NUMBER}\);\s*', prefix)
    if not entry or integer(entry['offset']) != integer(queue['offset']):
        return []
    repeat = rf'\s*{IDENT}\([^;\n]*\);\s*{re.escape(entry["prepare"])}\s*goto {entry["label"]};\s*'
    if not re.fullmatch(repeat, part.clean[finish:part.clean.rfind('}', finish, part.end)]):
        return []
    indent, begin = call['indent'], part.opening + 1
    return [(begin, begin, f'\n{indent}char *__repair_dispatch_table;'),
            (begin+entry.start('prepare'), begin+entry.start('prepare'),
             f'__repair_dispatch_table = {table};\n{indent}do {{ }} while (0);\n{indent}')]


def rewrite(source, name, asm, header='', resolve=None):
    """A word read from a relocated table supplies the callable value, using byte offsets."""
    fresh = '__repair_dispatch_offset'
    if ')(' not in source:
        return None
    if not (target := _evidence(asm)) or not (part := view(source, name)):
        return None
    lines, symbol, addend, dispatch = target
    matches = []
    for call in INVOKE.finditer(part.clean, part.opening+1, part.end):
        end = close(part.clean, call.end()-1)
        if not end or part.clean[end:end+1] != '(':
            continue
        finish = close(part.clean, end)
        if not finish or part.clean[finish:finish+1] != ';':
            continue
        raw = part.clean[call.end():end-1]
        address = next((hit for pattern in C_ADDRESSES if (hit := pattern.fullmatch(raw))), None)
        if address:
            matches.append((call, end, finish+1, address))
    if len(matches) != 1:
        return None
    call, end, finish, address = matches[0]
    offset = integer(address.groupdict().get('offset') or '0')
    if not _same_address(address['symbol'], offset, symbol, addend, resolve):
        return None

    kind = 'void'
    if result := call['result']:
        declaration = re.findall(rf'(?m)^\s*(s32|u32|void \*)\s*{result}\s*;', part.clean[:call.start()])
        if len(declaration) != 1:
            return None
        kind = declaration[0]

    index = address['index']
    base = f'(char *)&{address["symbol"]}'
    if offset:
        base += f' + 0x{offset:X}'
    expression = f'({index} * 4)'
    edits = []
    if not result and part.clean[end:finish] == '();':
        if boundary := _queue_boundary(part, lines, call, finish):
            edits.append((boundary[0], boundary[0], boundary[1]))
        elif dispatch.re is HOISTED and '__repair_dispatch_table' not in source + header:
            edits = _resident_table(part, lines, call, finish, base)
            if edits:
                base = '__repair_dispatch_table'
    elif (not result and fresh not in source + header
          and (field := re.fullmatch(rf'M2C_FIELD\((?P<base>{IDENT}), u16 \*, (?P<offset>{NUMBER})\)', index))
          and part.clean[end:finish] == f'({field["base"]});'
          and part.clean[part.opening+1:call.start()].rstrip().endswith('do {')
          and (delay := re.fullmatch(r'move \$a0, (\$s[0-7])', dispatch['delay']))):
        previous = lines[max(0, dispatch.start()-80):dispatch.start()].splitlines()
        load = re.fullmatch(rf'lhu {re.escape(dispatch["input"])}, ({NUMBER})?\({re.escape(delay[1])}\)',
                            previous[-1]) if previous else None
        if load and integer(load[1] or '0') == integer(field['offset']):
            indent = call['indent']
            edits.append((call.start(), call.start(), f'{indent}u32 {fresh} = {expression};\n'))
            expression = fresh
    edits.append((call.start('call'), end, f'(*({kind} (**)())({base} + {expression}))'))
    return edit(source, edits)
