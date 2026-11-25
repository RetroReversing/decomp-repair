"""The caller's own arguments passed on to every callee that receives them untouched, the signature widened to them.

A function that only tests one of its arguments and then calls one of two functions with all of them,

    andi $v0, $a2, 0x10              (the test reads $a2 and leaves it alone)
    bnez $v0, L
    jal f                            ($a0..$a2 still the caller's, on this path)
    ...
L:  jal g                            (and on this one)

is drafted by m2c as `void h(s32 arg2) { if (!(arg2 & 0x10)) { f(); return; } g(); }`: no instruction loads
`$a0`..`$a2` before either call, so it sees no arguments, and it names the one parameter it saw by its register. With
`arg2` dead after the test, GCC computes the test into `$a2` itself (`andi $a2, $a2, 0x10`: two register rows). The
game's source passed the arguments on, `void h(s32 arg0, s32 arg1, s32 arg2) { ... f(arg0, arg1, arg2); ... g(arg0,
arg1, arg2); }`, which keeps `$a2` live to the calls, so the test takes `$v0`. Passing only `arg2` on (to one or both
callees) is worse (200): each callee needs every argument in its own register. `passthrough_argument` gives one call
at a time and proves the registers only along a straight entry path, which a branch ends.

A KMC GCC 2.7.2 N64 dispatcher (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, 13 instructions) went 10 -> 0 with
the first child.

The evidence is the target's own assembly (MIPS, the O32 argument registers): a forward analysis over its branches
finds, for each `jal`, the argument registers that hold the caller's value on every path from the entry (an
instruction writing one, or an earlier call, ends it; a branch's delay slot counts on both paths). `variants` needs
every parameter named by its register (`argN`, N <= 3, integer or pointer types: m2c's names), no parameter written in
the body, and calls of callees with no prototype that names parameters (`f();` or undeclared) and no arguments, each
`jal`ed once. For each count K from the highest parameter's index + 1 up to the registers every such call receives
(`$a0`..`$a(K-1)`), the child declares `arg0`..`arg(K-1)` (an added one as `s32`) and passes them all to every such
call. At most 4 children."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'argument_passthrough_to_callees'
FAMILIES = (FAMILY,)
LIMIT = 4
_REGISTERS = ('$a0', '$a1', '$a2', '$a3')
_LINE = re.compile(r'^\s*(?:/\*.*?\*/)?\s*(?P<op>[a-z][\w.]*)\s*(?P<args>[^\n]*)$')
_LABEL = re.compile(r'^\s*(?P<label>[.\w$]+):\s*$')
_STORES = {'sb', 'sh', 'sw', 'sd', 'swl', 'swr', 'sdl', 'sdr', 'swc1', 'sdc1', 'sc', 'scd'}
_NO_WRITE = _STORES | {'nop', 'mult', 'multu', 'div', 'divu', 'dmult', 'dmultu', 'ddiv', 'ddivu', 'mtlo', 'mthi',
                       'mtc1', 'dmtc1', 'ctc1', 'teq', 'tne', 'break', 'syscall', 'cache', 'sync'}
_CONDITIONAL = re.compile(r'^b(?:eq|ne|lez|gtz|ltz|gez|eqz|nez|c1t|c1f)l?$')
_PARAMETER = re.compile(r'^(?P<type>[\w\s]+?[\s*]+)(?P<name>arg(?P<index>[0-3]))$')
_INTEGER = re.compile(r'^(?:(?:un)?signed\s+)?(?:[su](?:8|16|32)|char|short|int|long|M2C_UNK(?:8|16|32)?)$')


def _program(asm):
    """[(op, operands)] and {label: index} of the function's instructions."""
    instructions, labels = [], {}
    for line in (asm or '').splitlines():
        label = _LABEL.match(line)
        if label:
            labels[label['label']] = len(instructions)
            continue
        found = _LINE.match(line)
        if found and not line.strip().startswith(('.', 'glabel', 'endlabel')):
            instructions.append((found['op'], found['args'].strip()))
    return instructions, labels


def _kills(op, operands):
    """The argument registers `op` writes itself (a call's clobbers come after its delay slot)."""
    if op in ('jal', 'jalr') or op in _NO_WRITE or _CONDITIONAL.match(op) or op in ('b', 'j', 'jr'):
        return set()
    first = operands.split(',')[0].strip()
    return {first} & set(_REGISTERS)


def incoming_calls(asm):
    """{callee: {argument index}} for each callee `jal`ed exactly once: the argument registers that hold the caller's own
    value at that call on every path from the entry. Empty when the code has an indirect jump it cannot follow."""
    instructions, labels = _program(asm)
    count = len(instructions)
    successors = [[index + 1] if index + 1 < count else [] for index in range(count)]
    for index, (op, operands) in enumerate(instructions):
        if index + 1 >= count:
            continue
        target = operands.split(',')[-1].strip()
        if op in ('bltzal', 'bgezal', 'bltzall', 'bgezall'):
            return {}  # a conditional call: not followed
        if op in ('j', 'b') or _CONDITIONAL.match(op):
            if target not in labels:
                return {}
            if _CONDITIONAL.match(op) and op.endswith('l') and index + 2 < count:
                # a likely branch annuls its delay slot when it falls through: the slot runs on the taken path only,
                # so an argument register the slot writes (`bnel $v0, $zero, L` / `addiu $a0, $zero, -0x14`) is still
                # the caller's value on the path that continues past it
                successors[index] = [index + 1, index + 2]
                successors[index + 1] = [labels[target]]
                continue
            # the branch's delay slot runs on both paths
            successors[index + 1] = [labels[target]] + ([index + 2] if op not in ('j', 'b') and index + 2 < count else [])
        elif op == 'jr':
            if operands.strip() != '$ra':
                return {}
            successors[index + 1] = []
    state = [None] * count
    state[0] = set(_REGISTERS)
    seen = {}
    work = [0]
    while work:
        index = work.pop()
        op, operands = instructions[index]
        after = state[index] - _kills(op, operands)
        if index >= 1 and instructions[index - 1][0] in ('jal', 'jalr'):
            if instructions[index - 1][0] == 'jal':
                seen[index - 1] = after  # what the callee receives: the delay slot ran
            after = set()  # the callee may change every argument register
        for following in successors[index]:
            merged = after if state[following] is None else state[following] & after
            if merged != state[following]:
                state[following] = merged
                work.append(following)
    callees = [operands for op, operands in instructions if op == 'jal']
    return {instructions[index][1]: {_REGISTERS.index(reg) for reg in registers}
            for index, registers in seen.items() if callees.count(instructions[index][1]) == 1}


def _parameters(part):
    """[(type, index)] of the definition's parameters when every one is an `argN` of integer or pointer type, else
    None; [] for none."""
    head = part.clean[:part.opening]
    if '(' not in head or ')' not in head:
        return None
    signature = part.source[head.rindex('(') + 1:head.rindex(')')].strip()
    if signature in ('', 'void'):
        return []
    out = []
    for piece in signature.split(','):
        found = _PARAMETER.match(re.sub(r'\s+', ' ', piece.strip()))
        if not found:
            return None
        kind = found['type'].strip()
        if '*' not in kind and not _INTEGER.match(kind):
            return None
        out.append((kind, int(found['index'])))
    if [index for _, index in out] != sorted({index for _, index in out}):
        return None
    return out


def _written(body, parameter):
    name = re.escape(parameter)
    return bool(re.search(rf'(?<![\w.>]){name}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', body)
                or re.search(rf'(?:\+\+|--)\s*{name}\b|(?<![\w.>]){name}\s*(?:\+\+|--)', body)
                or re.search(rf'&\s*{name}\b', body))


def _prototyped(callee, text):
    """Whether `text` declares `callee` with a parameter list (`(void)` included): then its arguments are fixed."""
    for found in re.finditer(rf'\b{re.escape(callee)}\s*\(([^()]*)\)\s*;', text):
        if found[1].strip():
            return True
    return False


def variants(source, name, asm=None, arch=None, header=''):
    """Proposals: the caller's arguments passed on to every argument-less call that receives them untouched."""
    if arch not in (None, 'mips') or not asm:
        return []
    part = view(source, name)
    if not part:
        return []
    parameters = _parameters(part)
    if parameters is None:
        return []
    clean, body_at = part.clean, part.opening + 1
    body = clean[body_at:part.end - 1]
    if any(_written(body, f'arg{index}') for _, index in parameters):
        return []
    incoming = incoming_calls(asm)
    outside = _blank(header) + '\n' + clean[:part.opening] + clean[part.end:]
    sites = []
    for hit in re.finditer(rf'(?<![\w.>])({IDENT})\s*\(', clean[body_at:part.end - 1]):
        callee, opening = hit[1], body_at + hit.end() - 1
        end = close(clean, opening, '(', ')')
        if not end or clean[opening + 1:end - 1].strip() or callee in ('if', 'while', 'for', 'switch', 'return', 'sizeof'):
            continue
        if callee not in incoming or _prototyped(callee, outside):
            continue
        sites.append((callee, opening + 1, end - 1))
    if not sites:
        return []
    reach = 0
    while all(reach in incoming[callee] for callee, _, _ in sites) and reach < len(_REGISTERS):
        reach += 1
    lowest = max((index + 1 for _, index in parameters), default=1)
    head = part.clean[:part.opening]
    signature_at, signature_end = head.rindex('(') + 1, head.rindex(')')
    kinds = {index: kind for kind, index in parameters}
    out = []
    for count in range(lowest, reach + 1):
        def declare(index):
            kind = kinds.get(index, 's32')
            return f'{kind}{"" if kind.endswith("*") else " "}arg{index}'
        names = ', '.join(f'arg{index}' for index in range(count))
        changes = [(signature_at, signature_end, ', '.join(declare(index) for index in range(count)))]
        changes += [(start, stop, names) for _, start, stop in sites]
        out.append(edit(source, changes))
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'arch', 'header'),
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
