"""The arguments of a call m2c wrote empty because the callee's own definition takes none.

A debug print or assert a release build emptied is still called with its arguments: the callee is `jr $ra; nop`, its
matched C is `void f(void) {}`, and m2c, given that prototype, drops what the target loads for it. The call then misses
`lui/addiu` of the message and the copy of the object into `$a0`, and nothing else offers them: `passthrough_argument`
and `argument_passthrough_to_callees` only forward the caller's own registers, `call_forwarded_arguments` only its own
parameters.

stripped_call_arguments
    The evidence is the target's own assembly (MIPS, the O32 argument registers). In the straight run of instructions
    before each `jal` of a callee the C calls as `f()`, and in its delay slot, every `$a0`..`$aK` is written (without a
    gap from `$a0`) by one of: the address of a symbol (`lui`/`addiu %lo`), a small constant, or a copy of a saved
    register that holds one of the caller's own parameters since the entry. The call gets those arguments, the prototype
    `f(void)` becomes `f()`, and a symbol the source never declares is declared `extern u8 SYM[];`. One child per
    callee and one with all of them. Judged like any child.

A 64-instruction N64 object routine (SN gcc 2.8.1, `-G0 -mips3 -O2 -mfp64`) passed its object and a message string to
such an emptied print: 660 -> 330 with the child, and 0 with `statement_slide` after it.
"""
import re

from .argument_passthrough_to_callees import _NO_WRITE, _program
from .csource import _blank
from .integer_repair_support import IDENT, calls, edit, view

FAMILY = 'stripped_call_arguments'
FAMILIES = (FAMILY,)
LIMIT = 6
_ARGUMENTS = ('$a0', '$a1', '$a2', '$a3')
_CONTROL = re.compile(r'^(?:j|jr|jal|jalr|b|b(?:eq|ne|lez|gtz|ltz|gez|eqz|nez|c1t|c1f)l?|b(?:lt|ge)zall?)$')
_SYMBOL = re.compile(r'%(?P<kind>hi|lo)\((?P<symbol>[A-Za-z_]\w*)\)$')
_NUMBER = re.compile(r'^-?(?:0[xX][0-9a-fA-F]+|\d+)$')


def _split(operands):
    return [piece.strip() for piece in operands.split(',')]


def _saved_parameters(instructions):
    """{register: parameter index} for a saved register whose only write is a copy of `$aK` before any call."""
    copies, written = {}, {}
    called = False
    for op, operands in instructions:
        pieces = _split(operands)
        if op not in _NO_WRITE and re.fullmatch(r'\$s[0-7]', pieces[0]):
            if op in ('lw', 'ld') and pieces[-1].endswith('($sp)'):
                continue  # the epilogue's restore
            written[pieces[0]] = written.get(pieces[0], 0) + 1
            source = _copy_source(op, pieces)
            if not called and source in _ARGUMENTS:
                copies[pieces[0]] = _ARGUMENTS.index(source)
        called = called or op in ('jal', 'jalr')
    return {register: index for register, index in copies.items() if written[register] == 1}


def _copy_source(op, pieces):
    if op == 'move' and len(pieces) == 2:
        return pieces[1]
    if op in ('addu', 'or', 'daddu') and len(pieces) == 3 and pieces[2] == '$zero':
        return pieces[1]
    return None


def _values(window, saved, parameters):
    """{argument register: (kind, value)} for what the window leaves in each of `$a0`..`$a3` that it can name."""
    values, high = {}, {}
    for op, operands in window:
        pieces = _split(operands)
        if not pieces or not pieces[0].startswith('$'):
            continue
        register, value = pieces[0], None
        symbol = _SYMBOL.match(pieces[-1])
        if op == 'lui' and symbol and symbol['kind'] == 'hi':
            high[register] = symbol['symbol']
            values.pop(register, None)
            continue
        if op in ('addiu', 'daddiu') and len(pieces) == 3 and symbol and symbol['kind'] == 'lo':
            if high.get(pieces[1]) == symbol['symbol']:
                value = ('symbol', symbol['symbol'])
        elif op in ('addiu', 'ori') and len(pieces) == 3 and pieces[1] == '$zero' and _NUMBER.match(pieces[2]):
            value = ('constant', pieces[2])
        elif op == 'li' and len(pieces) == 2 and _NUMBER.match(pieces[1]):
            value = ('constant', pieces[1])
        else:
            source = _copy_source(op, pieces)
            if source == '$zero':
                value = ('constant', '0')
            elif source in saved and saved[source] < len(parameters):
                value = ('parameter', parameters[saved[source]])
        if value:
            values[register] = value
        else:
            values.pop(register, None)
        high.pop(register, None)
    return values


def _sites(asm, parameters):
    """{callee: [(kind, value), ...]} for each callee whose every `jal` loads the same leading arguments."""
    instructions, labels = _program(asm)
    starts = set(labels.values())
    saved = _saved_parameters(instructions)
    found = {}
    for index, (op, operands) in enumerate(instructions):
        if op != 'jal':
            continue
        begin = index
        while begin > 0 and begin not in starts:
            before = instructions[begin - 1][0]
            if _CONTROL.match(before) or (begin >= 2 and _CONTROL.match(instructions[begin - 2][0])):
                break  # a branch or call, or its delay slot
            begin -= 1
        values = _values(instructions[begin:index] + instructions[index + 1:index + 2], saved, parameters)
        leading = []
        for register in _ARGUMENTS:
            if register not in values:
                break
            leading.append(values[register])
        callee = operands.strip()
        found[callee] = leading if found.get(callee, leading) == leading else []
    return {callee: leading for callee, leading in found.items() if leading}


def _parameter_names(part):
    head = part.clean[:part.opening].rstrip()
    inside = head[head.rfind('(') + 1:-1]
    names = [re.search(rf'({IDENT})\s*$', piece) for piece in inside.split(',')]
    if not all(names) or inside.strip() == 'void' or any(len(piece.split()) < 2 and '*' not in piece
                                                          for piece in inside.split(',')):
        return []
    return [found[1] for found in names]


def _argument(kind, value, source, header):
    """The C spelling of one argument, and the declaration it needs (or '')."""
    if kind != 'symbol':
        return value, ''
    declared = re.search(rf'(?m)^[ \t]*extern\b[^;()]*?\b{re.escape(value)}\b\s*(?P<array>\[)?[^;()]*;',
                         _blank(source + '\n' + header))
    if declared:
        return (value if declared['array'] else '&' + value), ''
    return value, f'extern u8 {value}[];\n'


def _unprototyped(text, callee):
    return re.sub(rf'(?m)^([ \t]*(?:extern[ \t]+)?[\w ]+?[ \t*]+{re.escape(callee)}[ \t]*)\([ \t]*void[ \t]*\)([ \t]*;)',
                  r'\1()\2', text)


def _apply(source, name, header, callees):
    """`source` with the arguments of every callee in `callees` ({callee: values}) written in."""
    part = view(source, name)
    changes, declarations = [], []
    for callee, values in callees.items():
        written = [_argument(kind, value, source, header) for kind, value in values]
        declarations += [text for _, text in written if text and text not in declarations]
        spelled = ', '.join(text for text, _ in written)
        changes += [(start, end, spelled) for start, end in calls(part, callee)]
    text = edit(source, changes)
    for callee in callees:
        text = _unprototyped(text, callee)
    if declarations:
        start = view(text, name)
        head = text.rfind('\n', 0, text.rfind(name, 0, start.opening)) + 1
        text = text[:head] + ''.join(declarations) + text[head:]
    return text


def variants(source, name, asm=None, arch=None, header=''):
    """Proposals: the arguments the target loads, written into the calls the C leaves empty."""
    if arch not in (None, 'mips') or not asm:
        return []
    part = view(source, name)
    if not part:
        return []
    usable = {}
    for callee, values in _sites(asm, _parameter_names(part)).items():
        found = list(calls(part, callee))
        if found and all(not part.clean[start:end].strip() for start, end in found):
            usable[callee] = values
    choices = [{callee: values} for callee, values in sorted(usable.items())]
    if len(usable) > 1:
        choices.insert(0, usable)
    return [(FAMILY, _apply(source, name, header, choice)) for choice in choices[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'arch', 'header'),
          'archs': ('mips',)}
