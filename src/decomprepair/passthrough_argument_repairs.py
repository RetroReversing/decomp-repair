"""An argument the caller passed on untouched in its own register, which m2c doesn't see.

When a caller hands its own `arg2` to a callee as that callee's third argument too, nothing loads `$a2` before the
call, so m2c leaves it out and the call has one argument too few: its later arguments shift down a register and the
last one off the stack. An N64 function was 95% with `f(arg0, D, x, y)` where the game called `f(arg0, D, arg2, x,
y)`; exact with it. A callee m2c gave no arguments at all may get every one of the caller's (up to four)
at once. Offered for callees declared without parameters (`s32 f();`, m2c's guess), with the caller's
parameter at its own position; and for a callee with a prototype, when the call is its only one in the
function, with the prototype widened by the caller's type (three N64 functions passing their `arg0` on to a
`f32 f(u16 *)` were exact as `f(arg0, &sp10)` with `f32 f(s32, u16 *)`).
"""
import collections
import re
from dataclasses import dataclass

from . import m2cfix
from .csource import _blank, find
from .integer_abi import scalar
from .integer_repair_support import NUMBER, edit, integer, view
from .pattern_repairs import close
from .target_call_arity_repairs import _instructions

FAMILY = 'passthrough_argument'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def variants(source, name, *, asm=None, arch=None, header='', callees='', require_evidence=False, selected_call=None):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    signature = clean[span[0]:opening]
    params_at = signature.rfind('(')
    params = [p.strip() for p in m2cfix._split_top_level(signature[params_at + 1:signature.rfind(')')])]
    names = [re.search(IDENT + r'\s*$', p)[0].strip() if re.search(IDENT + r'\s*$', p) else None for p in params]
    if not names or names == ['void']:
        return []
    incoming = None
    if require_evidence:
        context = header+'\n'+source
        kinds = [re.sub(r'\b'+re.escape(n)+r'\s*$', '', p).strip() if n else '' for n,p in zip(names,params)]
        if arch != 'mips' or not all(_integer_parameter(k, context) for k in kinds[:4]):
            return []
        incoming = _incoming_calls(asm)
        if not incoming:
            return []
    outside = clean[:span[0]] + clean[span[1]:]
    unprototyped = set(re.findall(r'(?m)^[ \t]*(?:extern\s+)?[\w ]+?[\s*]+(' + IDENT + r')\s*\(\s*\)\s*;', outside))
    # a callee with a prototype too, when this is its only call: its parameter list gains the caller's type there
    prototypes = {m[1]: m for m in re.finditer(r'(?m)^[ \t]*(?:extern\s+)?[\w ]+?[\s*]+(' + IDENT
                                               + r')\s*\((?P<params>[^()]*)\)\s*;', outside)
                  if m['params'].strip() and m['params'].strip() != 'void'}
    calls = collections.Counter(re.findall(r'\b(' + IDENT + r')\s*\(', clean[opening:end]))
    result = []
    for call in re.finditer(r'\b(' + IDENT + r')\s*\(', clean[opening:end]):
        prototype = prototypes.get(call[1]) if calls[call[1]] == 1 else None
        if call[1] not in unprototyped and prototype is None:
            continue
        paren = opening + call.end() - 1
        closing = close(clean, paren)
        if not closing:
            continue
        args = [a.strip() for a in m2cfix._split_top_level(clean[paren + 1:closing - 1])] if clean[paren + 1:closing - 1].strip() else []
        if selected_call is not None and call[1] != selected_call:
            continue
        if incoming is not None and (call[1] not in incoming or calls[call[1]] != 1):
            continue
        if len(args) >= 8:
            continue
        if selected_call is None and not args and call[1] in unprototyped and len([n for n in names[:4] if n]) > 1 and None not in names[:4]:
            # (a callee handed all of the caller's own arguments untouched: nothing loads $a0-$a3 before the call, so
            # m2c drops them all; one N64 function, 40 points off with `f()`, was exact as `f(arg0, arg1, arg2)`,
            # the callee keeping its first `$a` registers live where the caller's saves expected them)
            text = source[:closing - 1] + ', '.join(names[:4]) + source[closing - 1:]
            if (incoming is None or _allows(call[1], range(len(names[:4])), len(names[:4]), incoming, header, callees)):
                result.append((FAMILY, text))
        for k, param in enumerate(names[:1] if selected_call is not None else names[:4]):
            if param is None or k > len(args) or (k < len(args) and args[k] == param) or param in args:
                continue
            if incoming is not None and not _allows(call[1], [k], len(args)+1, incoming, header, callees):
                continue
            # insert before the k-th argument (or at the end)
            if k < len(args):
                spot = paren + 1
                for _ in range(k):
                    spot = _next_argument(clean, spot)
                insert, at = param + ', ', spot + (len(clean[spot:]) - len(clean[spot:].lstrip()))
            else:
                insert, at = (', ' if args else '') + param, closing - 1
            text = source[:at] + insert + source[at:]
            if prototype is not None:
                types = m2cfix._split_top_level(prototype['params'])
                if len(types) != len(args) or '...' in prototype['params']:
                    continue
                kind = re.sub(r'\b' + param + r'\s*$', '', params[k]).strip()
                types.insert(k, kind)
                begin = _absolute(clean, span, prototype.start('params'))
                stop = _absolute(clean, span, prototype.end('params'))
                if stop > at:
                    continue  # (a prototype after the function: not m2c's layout)
                text = text[:begin] + ', '.join(t.strip() for t in types) + text[stop:]
            if text not in [t for _, t in result]:
                result.append((FAMILY, text))
        if len(result) >= 6:
            break
    return result


def _absolute(clean, span, offset):
    """A position in `clean[:span[0]] + clean[span[1]:]` as a position in `clean`."""
    return offset if offset < span[0] else offset + (span[1] - span[0])


def _next_argument(text, start):
    """Where the argument after the one starting at `start` begins."""
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        depth += (ch in '([{') - (ch in ')]}')
        if depth == 0 and ch == ',':
            return i + 1
    return len(text)


def _integer_parameter(kind, context):
    value = scalar(kind, context, 'mips')
    return (value is not None and value[0] <= 32) or bool(re.fullmatch(r'[\w\s]+\*+[\w\s*]*',kind))


def _allows(callee, positions, count, incoming, header, callees):
    if not set(positions) <= incoming[callee]:
        return False
    evidence = _blank(header+'\n'+callees)
    for declaration in re.finditer(rf'(?m)^\s*(?:extern\s+)?[\w *]+[\s*]+{re.escape(callee)}\s*\(([^()]*)\)\s*[;{{]', evidence):
        params = declaration[1].strip()
        if params and (params == 'void' or '...' in params or
                       len(m2cfix._split_top_level(params)) != count):
            return False
    return True


_ARGUMENTS = ('a0', 'a1', 'a2', 'a3')
_CALLER_SAVED = set(_ARGUMENTS) | {'at', 'v0', 'v1', 'ra'} | {f't{n}' for n in range(10)}
_NO_GPR_WRITE = {'nop','sw','sb','sh','sd','swc1','sdc1','mult','multu','div','divu','mtlo','mthi','mtc1'}
_GPR_WRITE = set('addiu addi addu daddiu daddu subu add sub and andi or ori xor xori nor '
                 'lui sll srl sra sllv srlv srav slt slti sltu sltiu mflo mfhi mfc1 '
                 'lb lbu lh lhu lw lwu ld lwl lwr move li la neg negu'.split())


def _transfer(registers, op, operands):
    if op in _NO_GPR_WRITE:
        return True
    if op not in _GPR_WRITE:
        return False
    args = [arg.strip() for arg in operands.split(',')]
    if not re.fullmatch(r'\$[a-z][a-z0-9]*', args[0]):
        return False
    dest = args[0][1:]
    source = None
    if op == 'move' and len(args) == 2:
        source = args[1]
    elif op in {'addu', 'daddu', 'or'} and len(args) == 3 and '$zero' in args[1:]:
        source = args[2] if args[1] == '$zero' else args[1]
    elif op in {'addiu','ori','sll'} and len(args) == 3 and args[2] in {'0','0x0'}:
        source = args[1]
    origin = registers.get(source[1:]) if source and source.startswith('$') else None
    registers.pop(dest, None)
    if origin is not None and dest != 'zero':
        registers[dest] = origin
    return True


def _incoming_calls(asm):
    # Prove origins along a straight-line entry path only. A branch, indirect
    # transfer or unknown operation ends the proof. The callee sees the delay
    # slot's writes and may clobber every caller-saved register afterwards.
    instructions = list(_instructions(asm))
    counts = collections.Counter(args for op,args in instructions if op == 'jal')
    registers = {reg: index for index,reg in enumerate(_ARGUMENTS)}
    result = {}
    pc = 0
    while pc < len(instructions):
        op, operands = instructions[pc]
        pc += 1
        if op != 'jal':
            if not _transfer(registers, op, operands):
                break
            continue
        registers.pop('ra', None)
        if pc == len(instructions) or not _transfer(registers, *instructions[pc]):
            break
        if re.fullmatch(IDENT, operands) and counts[operands] == 1:
            result[operands] = {i for i,reg in enumerate(_ARGUMENTS) if registers.get(reg) == i}
        for reg in _CALLER_SAVED:
            registers.pop(reg, None)
        pc += 1
    return result


_FRAME = (
    rf'addiu \$sp, \$sp, -(?P<frame>{NUMBER})\nsw \$ra, (?P<save>{NUMBER})\(\$sp\)\n'
)
_CALL = rf'jal (?P<callee>{IDENT})\n'
_RESTORE = r'\nlw \$ra, (?P=save)\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, (?P=frame)'
_GLOBAL_WRAPPER = re.compile(
    rf'lui \$a1, %hi\((?P<global>{IDENT})\)\nlw \$a1, %lo\((?P=global)\)\(\$a1\)\n'
    + _FRAME + _CALL + 'nop' + _RESTORE,
)
_LITERAL_WRAPPER = re.compile(
    _FRAME + _CALL + rf'(?:addiu \$a1, \$zero, (?P<literal>-?{NUMBER})|'
    r'addu \$a1, \$zero, \$zero|move \$a1, \$zero)' + _RESTORE,
)

_ADDRESS_WRAPPER = re.compile(
    _FRAME + rf'lui \$a1, %hi\((?P<address>{IDENT})\)\n' + _CALL
    + r'addiu \$a1, \$a1, %lo\((?P=address)\)'
    + rf'(?:\njal (?P<followup>{IDENT})\nnop)?' + _RESTORE,
)

_FIELD_WRAPPER = re.compile(
    rf'lui \$v0, %hi\((?P<base>{IDENT})\)\nlw \$v0, %lo\((?P=base)\)\(\$v0\)\n'
    + _FRAME + _CALL + rf'lw \$a1, (?P<offset>{NUMBER})?\(\$v0\)' + _RESTORE,
)
_FILL_WRAPPER = re.compile(
    _FRAME + r'(?:addu \$a1, \$zero, \$zero|move \$a1, \$zero)\n'
    + rf'jal (?P<callee>memset)\naddiu \$a2, \$zero, (?P<size>{NUMBER})' + _RESTORE,
)


@dataclass(frozen=True)
class _EntryCall:
    callee: str
    arguments: str
    prototype: str
    literals: tuple[tuple[str, int], ...] = ()
    followup: str | None = None
    incoming: str = 's32'


def _literal_argument(text):
    value = integer(text.removeprefix('-'))
    return -value if text.startswith('-') else value


def _entry_wrapper(asm):
    """Describe a wrapper that supplies later arguments without touching the first."""
    if 'jal' not in (asm or ''):
        return None
    text = '\n'.join(f'{op} {" ".join(args.split())}'.rstrip() for op, args in _instructions(asm))
    word = r's32|M2C_UNK'
    if target := _GLOBAL_WRAPPER.fullmatch(text):
        return _EntryCall(target['callee'], target['global'], word)
    if target := _LITERAL_WRAPPER.fullmatch(text):
        literal = _literal_argument(target['literal'] or '0')
        return _EntryCall(target['callee'], rf'(?P<value>-?{NUMBER})', word, (('value', literal),))
    if target := _ADDRESS_WRAPPER.fullmatch(text):
        return _EntryCall(target['callee'], '&'+target['address'], r'M2C_UNK \*', followup=target['followup'])
    if target := _FIELD_WRAPPER.fullmatch(text):
        base, offset = target['base'], integer(target['offset'] or '0')
        field = rf'M2C_FIELD\({base}, s32 \*, (?P<offset>{NUMBER})\)'
        if not offset:
            field = rf'(?:{field}|\*{base})'
        return _EntryCall(target['callee'], field, word, (('offset', offset),))
    if target := _FILL_WRAPPER.fullmatch(text):
        return _EntryCall(target['callee'], rf'(?P<fill>{NUMBER}),\s*(?P<size>{NUMBER})',
                          rf'(?:{word}),\s*(?:{word})', (('fill', 0), ('size', integer(target['size']))),
                          incoming='void *')
    return None


def entry_wrapper_applies(asm):
    return _entry_wrapper(asm) is not None


def missing_entry_argument(source, name, asm, header=''):
    """Recover the caller's own parameter when m2c dropped it from the signature."""
    if not (target := _entry_wrapper(asm)) or not (span := find(source, name)):
        return None
    clean = _blank(source)
    callee = target.callee
    if (re.search(rf'\b{callee}\s*\(|(?m:^[ \t]*#\s*define\s+arg0\b)', _blank(header))
            or re.search(r'\barg0\b', clean[slice(*span)])):
        return None
    tail = rf'\s*{target.followup}\(\);' if target.followup else ''
    wrapper = re.fullmatch(
        rf'\s*void\s+{re.escape(name)}\((?P<params>void)\)\s*{{\s*'
        rf'{callee}\((?P<args>{target.arguments})\);{tail}\s*}}\s*', clean[slice(*span)])
    if not wrapper or any(_literal_argument(wrapper[key] or '0') != value for key, value in target.literals):
        return None
    # Only widen the prototype marked as generated by m2c.
    declarations = list(re.finditer(
        rf'(?m)^[ \t]*M2C_UNK {callee}\((?P<argtype>{target.prototype})\);[ \t]*/\* extern \*/[ \t]*$',
        source[:span[0]]))
    if len(declarations) != 1 or len(re.findall(rf'\b{callee}\s*\(', clean)) != 2:
        return None

    offset = span[0]
    space = '' if target.incoming.endswith('*') else ' '
    return edit(source, [
        (declarations[0].start('argtype'), declarations[0].start('argtype'), f'{target.incoming}, '),
        (offset + wrapper.start('params'), offset + wrapper.end('params'), f'{target.incoming}{space}arg0'),
        (offset + wrapper.start('args'), offset + wrapper.start('args'), 'arg0, '),
    ])


def _float_wrapper_output(source, name, header, asm, rows, changes):
    """Recover the unchanged output pointer in a wrapper whose integer save moved."""
    if len(changes) != 2 or changes[1] != changes[0] + 3:
        return None
    first, last = changes
    earlier, later = rows[first], rows[last]
    if earlier[0] != 'o' or later[0] != 'o' or earlier[2] or later[1] or earlier[1] != later[2]:
        return None
    save = re.fullmatch(rf'sw (\$s[0-7]), {NUMBER}\(\$sp\)', earlier[1])
    if not save or first < 4 or last + 6 >= len(rows):
        return None
    fp_args = []
    for arg, row in enumerate((first - 4, first - 2, first + 1), 1):
        fp = re.fullmatch(rf'sdc1 (\$f\d+), {NUMBER}\(\$sp\)', rows[row][1])
        if not fp or rows[row+1][1] != f'mtc1 $a{arg}, {fp[1]}':
            return None
        fp_args.append(fp[1])
    if not re.fullmatch(rf'sw \$ra, {NUMBER}\(\$sp\)', rows[last+1][1]):
        return None
    callee = re.fullmatch(rf'jal ({IDENT})', rows[last+2][1])
    if not callee or rows[last+3][1] != f'move {save[1]}, $a0':
        return None
    store_start = last + 4
    const = re.fullmatch(rf'lui (\$\w+), {NUMBER}', rows[store_start][1])
    if const and re.fullmatch(rf'mtc1 {re.escape(const[1])}, \$f\d+', rows[store_start+1][1]):
        store_start += 2
    base = re.escape(save[1])
    stores = [re.fullmatch(rf'swc1 {re.escape(reg)}, ({NUMBER})?\({base}\)', row[1])
              for reg, row in zip(fp_args, rows[store_start:store_start+3])]
    if len(stores) != 3 or not all(stores):
        return None
    incoming = _incoming_calls(asm)
    if callee[1] not in incoming or not _allows(callee[1], [0], 1, incoming, header, ''):
        return None
    if not (part := view(source, name)):
        return None
    signature = re.search(
        rf'\bvoid\s+{re.escape(name)}\s*\(\s*void\s*\*\s*(?P<out>{IDENT})'
        rf',\s*f32 ({IDENT}),\s*f32 ({IDENT}),\s*f32 ({IDENT})\)\s*$', part.clean[:part.opening])
    if not signature or not re.search(rf'(?m)^\s*M2C_UNK {callee[1]}\(\);\s*/\* extern \*/',
                                      source[:part.opening]):
        return None
    out = signature['out']
    call = re.compile(rf'(?m)^[ \t]*{callee[1]}\((?P<args>)\);')
    sites = list(call.finditer(part.clean, part.opening + 1, part.end))
    if len(sites) != 1 or not re.fullmatch(r'\s*', part.clean[part.opening+1:sites[0].start()]):
        return None
    fields = re.findall(rf'(?m)^\s*M2C_FIELD\({out}, f32 \*, ({NUMBER})\) = ({IDENT});',
                        part.clean[sites[0].end():part.end])
    expected = [(integer(store[1] or '0'), arg) for store, arg in zip(stores, signature.groups()[1:])]
    if [(integer(offset), var) for offset, var in fields] != expected:
        return None
    return edit(source, [(*sites[0].span('args'), out)])


def shifted_call_variants(source, name, header, asm, rows):
    """Focus passthrough proposals on a call whose argument setup is shifted down one register."""
    changes = [i for i, (marker, _, _) in enumerate(rows) if marker != ' ']
    if candidate := _float_wrapper_output(source, name, header, asm, rows, changes):
        return [(FAMILY, candidate)]
    if not 1 <= len(changes) <= 6:
        return []
    argument = re.compile(r'(?P<op>lw|lhu|lb|lbu|andi|addiu|move|lui) \$a(?P<reg>[0-3]), (?P<value>.+)')
    relocations = 0
    for i in changes:
        want, have = map(argument.fullmatch, rows[i][1:])
        if (not want or not have or int(want['reg']) != int(have['reg']) + 1 or want['op'] != have['op']):
            return []
        if want['value'] == have['value']:
            continue
        low = re.fullmatch(rf"\$a{want['reg']}, %lo\(({IDENT})\)", want['value'])
        if (want['op'] != 'addiu' or not low or i - 1 not in changes
                or have['value'] != f"$a{have['reg']}, %lo({low[1]})"
                or list(rows[i - 1][1:]) != [f"lui $a{reg}, %hi({low[1]})" for reg in (want['reg'], have['reg'])]):
            return []
        # A verified relocation pair is one argument spread over two instructions.
        relocations += 1
    if len(changes) - relocations > 3:
        return []

    center = changes[0]
    reach = 4 + relocations
    nearby = set()
    for i in range(max(0, center - 1), min(len(rows), center + reach + 1)):
        marker, target, candidate = rows[i]
        call = re.fullmatch(rf'jal ({IDENT})', target)
        if marker == ' ' and target == candidate and call and all(i - reach <= j <= i + 1 for j in changes):
            nearby.add(call[1])
    if len(nearby) != 1:
        return []
    return variants(source, name, asm=asm, arch='mips', header=header, require_evidence=True,
                    selected_call=nearby.pop())
