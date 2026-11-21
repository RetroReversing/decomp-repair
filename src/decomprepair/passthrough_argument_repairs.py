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

from . import m2cfix, mips_regions, mips_return_paths
from .csource import _blank, find
from .float_bit_argument_repairs import float_text
from .integer_abi import scalar
from .integer_repair_support import NUMBER, calls, edit, integer, view
from .pattern_repairs import close
from .target_call_arity_repairs import _instructions

FAMILY = 'passthrough_argument'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def variants(source, name, *, asm=None, arch=None, header='', callees='', require_evidence=False,
             selected_call=None, selected_slot=0, resolve=None, indirect=None):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    signature = clean[span[0]:opening]
    definition = re.search(rf'\b{re.escape(name)}\s*\(', signature)
    if not definition or not (closing := close(signature, definition.end() - 1)):
        return []
    params = [p.strip() for p in m2cfix._split_top_level(signature[definition.end():closing - 1])]
    names = [re.search(IDENT + r'\s*$', p)[0].strip() if re.search(IDENT + r'\s*$', p) else None for p in params]
    if not names or names == ['void']:
        return []
    incoming = None
    if require_evidence:
        context = header+'\n'+source
        kinds = [re.sub(r'\b'+re.escape(n)+r'\s*$', '', p).strip() if n else '' for n,p in zip(names,params)]
        # For a targeted call, verify the parameter types through the measured slot.
        checked = kinds[:selected_slot + 1] if selected_call is not None else kinds[:4]
        if arch != 'mips' or not all(_integer_parameter(k, context) for k in checked):
            return []
        if selected_call is None:
            incoming = _incoming_calls(asm)
        else:
            address = resolve(selected_call) if resolve is not None else None
            raw = f'func_{address:08X}' if address is not None else selected_call
            if selected_slot == 0:
                proven = _entry_a0_reaches(asm, selected_call, indirect=indirect) or (
                    raw != selected_call and _entry_a0_reaches(asm, raw, indirect=indirect))
            else:
                roots = _incoming_calls(asm)
                proven = selected_slot in roots.get(selected_call, roots.get(raw, ()))
            incoming = {selected_call: {selected_slot}} if proven else {}
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
        for k, param in enumerate(names[:4]):
            if selected_call is not None and k != selected_slot:
                continue
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


def _entry_a0_reaches(asm, callee, *, first_only=False, indirect=None):
    """Require the incoming a0 on every route to a selected first call."""
    if (0 in _incoming_calls(asm).get(callee, ())
            and not any(op in mips_regions.CONDITIONAL | {'b', 'j'} for op, _ in _instructions(asm))):
        return True
    decoded = mips_return_paths.graph(asm, indirect=indirect)
    if not decoded:
        return False
    rows, destinations = decoded
    sites = [i for i, row in enumerate(rows) if row.split() == ['jal', callee]]
    if not sites or (not first_only and len(sites) != 1):
        return False
    call = sites[0]
    pending = [(0, True)]
    seen = set()
    reached = False

    def preserves_a0(row):
        op, *args = row.split(None, 1)
        registers = {'a0': 0}
        return _transfer(registers, op, args[0] if args else '') and registers.get('a0') == 0

    while pending:
        pc, incoming = pending.pop()
        if pc >= len(rows) or (pc, incoming) in seen:
            continue
        seen.add((pc, incoming))
        if len(seen) > mips_return_paths.LIMIT:
            return False
        op = rows[pc].split()[0]
        if op in mips_regions.CALLS | mips_regions.CONDITIONAL | mips_regions.JUMPS:
            delayed = incoming and preserves_a0(rows[pc + 1])
            if pc == call:
                if not delayed:
                    return False
                reached = True
            if op in mips_regions.CALLS:
                pending.append((pc + 2, False))
            elif indirect and pc in indirect:
                pending.extend((target, delayed) for target in indirect[pc])
            elif pc in destinations:
                pending.append((destinations[pc], delayed))
                if op in mips_regions.CONDITIONAL:
                    pending.append((pc + 2, incoming if op.endswith('l') else delayed))
        elif op != 'break':
            pending.append((pc + 1, incoming and preserves_a0(rows[pc])))
    return reached


def _missing_caller_argument(source, name, header, asm, callee, *, memory_wrapper=False):
    """Restore a missing formal and its forward at one proven call site."""
    added = '__repair_incoming'
    if (added in source + header or re.search(rf'\b{callee}\s*\(', _blank(header))
            or not _entry_a0_reaches(asm, callee) or not (part := view(source, name))):
        return None
    params = r'M2C_UNK arg1, M2C_UNK arg2' if memory_wrapper else 'void'
    signature = re.search(rf'\b(?:void|s32|u32|M2C_UNK)\s+{re.escape(name)}\s*\((?P<args>{params})\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None
    sites = list(calls(part, callee))
    if len(sites) != 1:
        return None
    start, end = sites[0]
    args = part.clean[start:end]
    count = len(m2cfix._split_top_level(args))
    if not args.strip() or not 1 <= count <= 3:
        return None
    if memory_wrapper:
        close_at = part.clean.rfind('}', end, part.end)
        if args != 'arg2, arg1' or part.clean[part.opening+1:close_at].strip() != f'{callee}(arg2, arg1);':
            return None
    prototypes = list(re.finditer(
        rf'(?m)^[ \t]*(?:M2C_UNK|void|s32|u32)\s+{callee}\((?P<types>[^()]+)\);[ \t]*/\* extern \*/',
        source[:part.opening]))
    if len(prototypes) != 1:
        return None
    types = prototypes[0]['types'].strip()
    if types in ('void', '...') or '...' in types or len(m2cfix._split_top_level(types)) != count:
        return None
    ctype, formal = ('void *', f'void *{added}, {params}') if memory_wrapper else ('s32', f's32 {added}')
    return edit(source, [(*signature.span('args'), formal),
                         (prototypes[0].start('types'), prototypes[0].start('types'), f'{ctype}, '),
                         (start, start, f'{added}, ')])


def _forward_stack_output(source, name, header, asm, callee, resolve):
    """Recover the entry argument before a float-returning call's stack output."""
    address = resolve(callee) if resolve is not None else None
    entry_carries_argument = _entry_a0_reaches(asm, callee) or (
        address is not None and _entry_a0_reaches(asm, f'func_{address:08X}'))
    if (not entry_carries_argument or not (part := view(source, name))
            or re.search(rf'\b{callee}\s*\(', _blank(header))):
        return None
    gpr_type = r'(?:[su]32\b|(?:void|f32|[su](?:8|16|32))\s*\*)'
    signature = re.search(
        rf'\bvoid\s+{re.escape(name)}\s*\((?P<formal>void|'
        rf'(?P<kind>{gpr_type})[ \t]*(?P<arg>{IDENT})'
        rf'(?:\s*,\s*{gpr_type}[ \t]*{IDENT}){{0,3}})\)\s*$',
        part.clean[:part.opening],
    )
    sites = list(calls(part, callee))
    prototypes = list(re.finditer(
        rf'(?m)^[ \t]*f32\s+{callee}\((?P<types>(?:M2C_UNK|[su](?:16|32))\s*\*)\);'
        r'[ \t]*/\* extern \*/[ \t]*$', source[:part.opening],
    ))
    if not signature or len(sites) != 1 or len(prototypes) != 1:
        return None
    start, end = sites[0]
    local = re.fullmatch(rf'&(?P<local>{IDENT})', part.clean[start:end].strip())
    if not local:
        return None
    kind = prototypes[0]['types'].rstrip('* ').strip()
    if not re.search(rf'(?m)^\s*{kind}\s+{local["local"]}\s*;', part.clean[part.opening + 1:start]):
        return None
    arg = signature['arg'] or '__repair_incoming'
    changes = [(start, start, f'{arg}, ')]
    if signature['arg'] is None:
        if (re.search(rf'\b{arg}\b', part.clean + header)
                or re.search(rf'\b{re.escape(name)}\s*\(', _blank(header))):
            return None
        changes.append((*signature.span('formal'), f's32 {arg}'))
    pos = prototypes[0].start('types')
    arg_type = signature['kind'] or 's32'
    return edit(source, [(pos, pos, f'{arg_type}, '), *changes])


def _shifted_memory_wrapper(source, name, header, asm, rows, changes):
    """Both named arguments moved down when m2c omitted the destination of memset."""
    if changes != [2, 3, 5] or len(rows) != 9 or tuple(rows[4][1:]) != ('jal memset', 'jal memset'):
        return None
    pairs = [tuple(rows[i][1:]) for i in changes]
    if pairs != [('move $v0, $a1', 'move $v0, $a0'),
                 ('move $a1, $a2', 'move $a0, $a1'),
                 ('move $a2, $v0', 'move $a1, $v0')]:
        return None
    return _missing_caller_argument(source, name, header, asm, 'memset', memory_wrapper=True)


def _relocated_shift_count(rows, changes):
    argument = re.compile(r'(?P<op>lw|lhu|lb|lbu|andi|addiu|move|lui) \$a(?P<reg>[0-3]), (?P<value>.+)')
    relocations = 0
    for i in changes:
        want, have = map(argument.fullmatch, rows[i][1:])
        if not want or not have or int(want['reg']) != int(have['reg']) + 1 or want['op'] != have['op']:
            return None
        # A paired high/low address or load represents one shifted argument.
        symbol = re.search(rf'%lo\(({IDENT}(?: [+-] {NUMBER})?)\)', want['value'])
        paired = symbol and i - 1 in changes and list(rows[i - 1][1:]) == [
            f"lui $a{row['reg']}, %hi({symbol[1]})" for row in (want, have)
        ]
        if not paired and want['value'] == have['value']:
            continue
        low_operands = {
            'addiu': "$a{reg}, %lo({symbol})",
            'lw': "%lo({symbol})($a{reg})",
        }.get(want['op'])
        if (not paired or low_operands is None
                or any(row['value'] != low_operands.format(reg=row['reg'], symbol=symbol[1]) for row in (want, have))):
            return None
        relocations += 1
    return relocations if len(changes) - relocations <= 3 else None


def _repeated_first_call(source, name, header, asm, callee, rows, changes, call):
    """Patch the first of several calls only when its shifted literal identifies it."""
    if len(changes) != 1 or any(row[1] == f'jal {callee}' for row in rows[:call]):
        return None
    _, target, candidate = rows[changes[0]]
    literal = re.fullmatch(rf'addiu \$a1, \$zero, ({NUMBER})', target)
    if (not literal or candidate != f'addiu $a0, $zero, {literal[1]}'
            or re.search(rf'\b{callee}\s*\(', _blank(header))
            or not _entry_a0_reaches(asm, callee, first_only=True) or not (part := view(source, name))):
        return None
    if not re.search(rf'(?m)^\s*(?:M2C_UNK|s32|u32)\s+{callee}\(\);[ \t]*/\* extern \*/',
                     source[:part.opening]):
        return None
    signature = re.search(rf'\b(?:s32|u32|void|M2C_UNK)\s+{re.escape(name)}\s*\('
                          rf'\s*(?:s32|u32|M2C_UNK)\s+({IDENT})\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    sites = list(calls(part, callee))
    if len(sites) < 2:
        return None
    first = part.clean[slice(*sites[0])].strip()
    if not re.fullmatch(NUMBER, first) or integer(first) != integer(literal[1]):
        return None
    caller = signature[1]
    for span in sites[1:]:
        if len(args := m2cfix._split_top_level(part.clean[slice(*span)])) != 2 or args[0].strip() != caller:
            return None
    start = sites[0][0]
    return edit(source, [(start, start, f'{caller}, ')])


_CONDITIONAL_HALFWORD = re.compile(
    rf'lhu \$a1, (?P<offset>{NUMBER})\((?P<base>\$\w+)\)\n'
    rf'(?:sltiu (?P<test>\$\w+), \$a1, (?P<limit>{NUMBER})\n)?'
    r'(?P<branch>beqz|bnez) (?P<tested>\$\w+), \S+\n'
    rf'addiu \$a1, \$a1, (?P<delta>-?{NUMBER})\n'
    r'sh \$a1, (?P=offset)\((?P=base)\)\n'
    rf'(?:(?P<mask>andi \$a1, \$a1, {NUMBER})\n)?jal (?P<callee>{IDENT})\n'
    rf'(?P<slot>(?:andi|addiu) \$a1, \$a1, -?{NUMBER})'
)


def _conditional_halfword_update(source, name, header, asm, rows):
    """Put the update inside its guard and keep the untouched first argument live."""
    # Before decoding the control flow, require the same call with its narrow argument shifted down.
    shifted = set()
    for i, (marker, target, candidate) in enumerate(rows[:-1]):
        if marker == ' ' and target == candidate and target.startswith('jal '):
            marker, target_slot, candidate_slot = rows[i + 1]
            if (marker != ' ' and target_slot.startswith(('andi $a1, $a1, ', 'addiu $a1, $a1, '))
                    and candidate_slot == target_slot.replace('$a1', '$a0')):
                shifted.add(target.removeprefix('jal '))
    if not shifted or not (decoded := mips_return_paths.graph(asm)):
        return None
    instructions, destinations = decoded
    for branch, exit_at in destinations.items():
        has_limit = branch > 0 and instructions[branch - 1].startswith('sltiu ')
        start = branch - 1 - has_limit
        if start < 0 or not 6 <= exit_at - start <= 8:
            continue
        block = '\n'.join(' '.join(line.split()) for line in instructions[start:exit_at])
        target = _CONDITIONAL_HALFWORD.fullmatch(block)
        if not target or target['callee'] not in shifted:
            continue
        if target['tested'] != (target['test'] or '$a1') or target['base'] == '$a1':
            continue
        if target['test'] in {'$zero', '$a1', target['base']} or any(
                start < dest < exit_at for dest in destinations.values()):
            continue
        slot_value = _literal_argument(target['slot'].rsplit(' ', 1)[1])
        if target['mask']:
            if integer(target['mask'].rsplit(' ', 1)[1]) != 0xFFFF or not target['slot'].startswith('addiu '):
                continue
        elif not target['slot'].startswith('andi ') or slot_value != 0xFFFF:
            continue
        delta = _literal_argument(target['delta'])
        if abs(delta) != 1 or (target['mask'] and slot_value != -1):
            continue
        condition = ('<' if target['branch'] == 'beqz' else '>=')
        if target['limit'] is None:
            condition = '!=' if target['branch'] == 'beqz' else '=='
        if candidate := _place_halfword_update(
                source, name, header, asm, target['callee'], integer(target['offset']),
                condition, integer(target['limit'] or '0'), delta, bool(target['mask'])):
            return candidate
    return None


def _place_halfword_update(source, name, header, asm, callee, offset, condition, limit, delta, subtract):
    part = view(source, name)
    if not part or not (closing := close(part.clean, part.opening, '{', '}')):
        return None
    # The generated draft declares two halfword locals. Its assignment may even precede the load.
    masked = rf'(?P=updated)\s*&\s*(?P<mask>{NUMBER})'
    arg = rf'\(\s*{masked}\s*\)\s*-\s*1' if subtract else masked
    body = re.fullmatch(
        rf'\s*u16\s+(?P<old>{IDENT});\s*u16\s+(?P<updated>{IDENT});\s*'
        rf'(?P<setup>.+?)'
        rf'(?P<guard>if\s*\(\s*(?P=old)\s*{condition}\s*(?P<limit>{NUMBER})\s*\)\s*{{)'
        rf'(?P<indent>\n[ \t]+)(?P<field>M2C_FIELD\([^;\n]+,\s*u16\s*\*,\s*(?P<offset>{NUMBER})\))'
        rf'\s*=\s*(?P=updated);\s*{callee}\(\s*{arg}\s*\);\s*}}\s*return\s+0;\s*',
        part.clean[part.opening + 1:closing - 1], re.S)
    if (not body or body['old'] == body['updated'] or integer(body['offset']) != offset
            or integer(body['limit']) != limit or integer(body['mask']) != 0xFFFF):
        return None
    update = re.escape(body['updated']) + rf'\s*=\s*{re.escape(body["old"])}\s*'
    update += (r'\+' if delta > 0 else '-') + r'\s*1;'
    load = rf'{re.escape(body["old"])}\s*=\s*{re.escape(body["field"])};'
    setup = re.fullmatch(rf'(?:(?P<first>{update})\s*{load}|{load}\s*(?P<second>{update}))\s*', body['setup'])
    if not setup:
        return None
    beginning = part.opening + 1
    update_start, update_end = setup.span('first' if setup['first'] else 'second')
    update_start += beginning + body.start('setup')
    update_end += beginning + body.start('setup')
    guard_end = beginning + body.end('guard')
    # Remove the whole old line when the statement has no adjoining code or comment.
    line_start = source.rfind('\n', beginning, update_start) + 1
    line_end = source.find('\n', update_end, guard_end)
    remove = (line_start, line_end + 1) if (
        line_start >= beginning and line_end >= 0
        and not source[line_start:update_start].strip() and not source[update_end:line_end].strip()
    ) else (update_start, update_end)
    moved = edit(source, [
        (*remove, ''),
        (guard_end, guard_end, body['indent'] + source[update_start:update_end]),
    ])
    return _missing_caller_argument(moved, name, header, asm, callee)


def _pointer_call_reuse(source, name, header, asm, rows, i, callee):
    """The guarded pointer argument and the returned pointer occupy the same local."""
    if i < 4 or i + 4 >= len(rows) or rows[i - 1][1] != rows[i + 1][1] or rows[i + 1][1] != 'nop':
        return None
    load = re.fullmatch(rf'lw \$a1, (?P<inner>{NUMBER})\((?P<base>\$\w+)\)', rows[i - 3][1])
    before = re.fullmatch(r'beqz \$a1, (\S+)', rows[i - 2][1])
    after = re.fullmatch(r'beqz \$a1, (\S+)', rows[i + 3][1])
    if (not load or not before or not after or before[1] != after[1]
            or rows[i - 3][2] != rows[i - 3][1].replace('$a1,', '$a0,', 1)
            or rows[i - 2][2] != f'beqz $a0, {before[1]}'
            or tuple(rows[i + 2][1:]) != ('move $a1, $v0', 'move $v1, $v0')
            or rows[i + 3][2] != f'beqz $v1, {after[1]}'):
        return None
    outer = re.fullmatch(rf'lw {re.escape(load["base"])}, ({NUMBER})\(\$s[0-7]\)', rows[i - 4][1])
    uses = [re.fullmatch(rf'lw \$\w+, ({NUMBER})\(\$a1\)', row[1]) for row in rows[i + 4:]]
    if (not outer or not any(use and rows[at][2] == rows[at][1].replace('($a1)', '($v1)')
                             for at, use in enumerate(uses, i + 4))
            or not _entry_a0_reaches(asm, callee)
            or re.search(rf'\b{callee}\s*\(', _blank(header))
            or not (part := view(source, name))):
        return None
    prototype = re.search(
        rf'(?m)^[ \t]*void\s*\*\s*{callee}\((?P<params>s32|)\);(?P<marker>[ \t]*/\* extern \*/)?',
        source[:part.opening])
    if not prototype or (prototype['params'] and not prototype['marker']):
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(\s*void\s*\*\s*({IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None
    incoming = signature[1]
    load_and_call = re.match(
        rf'\s*(?P<type>s32)\s+(?P<item>{IDENT});\n'
        rf'(?P<decl>[ \t]*void\s*\*\s*(?P<returned>{IDENT})\s*;[ \t]*\n)\s*'
        rf'(?P=item)\s*=\s*M2C_FIELD\(M2C_FIELD\({incoming},\s*void\s*\*\*,\s*(?P<outer>{NUMBER})\),\s*'
        rf'(?P<field>s32\s*\*),\s*(?P<inner>{NUMBER})\);\s*'
        rf'if\s*\(\s*(?P=item)\s*!=\s*0\s*\)\s*{{\s*'
        rf'(?P<lhs>(?P=returned))\s*=\s*{callee}\(\s*(?P<arg>(?P=item))\s*\);\s*'
        r'if\s*\(\s*(?P=returned)\s*!=\s*(?:NULL|0)\s*\)\s*{',
        part.body)
    if (not load_and_call or load_and_call['item'] == load_and_call['returned']
            or integer(load_and_call['outer']) != integer(outer[1])
            or integer(load_and_call['inner']) != integer(load['inner'])
            or len(list(calls(part, callee))) != 1):
        return None
    site = load_and_call
    item, returned = site['item'], site['returned']
    start = part.opening + 1
    tail_start = start + site.end('arg')
    tail = part.clean[tail_start:part.end]
    fields = re.findall(rf'M2C_FIELD\({returned},\s*void\s*\*\*,\s*({NUMBER})\)', tail)
    references = list(re.finditer(rf'\b{returned}\b', tail))
    if (not fields or len(references) != len(fields) + 1 or re.search(rf'\b{item}\b', tail)
            or not set(map(integer, fields)) <= {integer(use[1]) for use in uses if use}):
        return None
    changes = [(start + site.start(k), start + site.end(k), replacement)
               for k, replacement in (('type', 'void *'), ('decl', ''), ('field', 'void **'),
                                      ('lhs', item), ('arg', f'{incoming}, {item}'))]
    changes += [(tail_start + hit.start(), tail_start + hit.end(), item) for hit in references]
    if prototype['params']:
        changes.append((*prototype.span('params'), 'void *, void *'))
    return edit(source, changes)


def _shifted_float_literal(source, name, header, asm, rows, changes, resolve):
    """Recognize a float literal displaced by an omitted incoming second argument."""
    if len(changes) != 1:
        return []
    start = changes[0]
    target, current = rows[start][1:]
    value = re.fullmatch(rf'lui \$a2, ({NUMBER})', target)
    if not value or current != f'lui $a1, {value[1]}' or not (literal := float_text(integer(value[1]) << 16)):
        return []
    for marker, wanted, have in rows[start + 1:start + 7]:
        if marker != ' ' or wanted != have:
            return []
        if callee := re.fullmatch(rf'jal ({IDENT})', wanted):
            if not (part := view(source, name)):
                return []
            sites = list(calls(part, callee[1]))
            if len(sites) != 1:
                return []
            first, last = sites[0]
            if not re.fullmatch(rf'\s*0\s*,\s*{re.escape(literal)}\s*', part.clean[first:last]):
                return []
            return variants(source, name, asm=asm, arch='mips', header=header, require_evidence=True,
                            selected_call=callee[1], selected_slot=1, resolve=resolve)
        if not re.fullmatch(rf'lw \$s[0-7], {NUMBER}\(\$s[0-7]\)', wanted):
            return []
    return []


def _switch_byte_forward(source, name, header, asm, rows, changes, resolve, read_data, big_endian):
    if read_data is None or len(changes) != 1 or 'switch (' not in source:
        return []
    i = changes[0]
    if not 0 < i < len(rows) - 1:
        return []
    load = re.fullmatch(rf'lbu \$a1, ({NUMBER})\((\$s[0-7])\)', rows[i][1])
    callee = re.fullmatch(rf'jal ({IDENT})', rows[i - 1][1])
    if not load or not callee or rows[i][2] != load[0].replace('$a1,', '$a0,', 1):
        return []
    clear = f'sb $zero, {load[1]}({load[2]})'
    if tuple(rows[i - 1]) != (' ', callee[0], callee[0]) or tuple(rows[i + 1]) != (' ', clear, clear):
        return []
    if not (edges := mips_return_paths.switch_edges(asm, read_data, big_endian)):
        return []
    return variants(source, name, asm=asm, arch='mips', header=header, require_evidence=True,
                    selected_call=callee[1], resolve=resolve, indirect=edges)


def shifted_call_variants(source, name, header, asm, rows, *, resolve=None, read_data=None, big_endian=False):
    """Focus passthrough proposals on the measured setup for one changed call."""
    changes = [i for i, (marker, _, _) in enumerate(rows) if marker != ' ']
    if forwarded := _switch_byte_forward(source, name, header, asm, rows, changes, resolve, read_data, big_endian):
        return forwarded
    if forwarded := _shifted_float_literal(source, name, header, asm, rows, changes, resolve):
        return forwarded
    if candidate := _float_wrapper_output(source, name, header, asm, rows, changes):
        return [(FAMILY, candidate)]
    if not 1 <= len(changes) <= 8:
        return []
    if candidate := _conditional_halfword_update(source, name, header, asm, rows):
        return [(FAMILY, candidate)]
    if candidate := _shifted_memory_wrapper(source, name, header, asm, rows, changes):
        return [(FAMILY, candidate)]
    nearby = []
    previous = -2
    for i, (marker, target, candidate) in enumerate(rows):
        if not target.startswith(('jal ', 'jalr ')):
            continue
        local = [j for j in changes if max(previous + 2, i - 7) <= j <= i + 1]
        previous = i
        call = re.fullmatch(rf'jal ({IDENT})', target)
        if marker != ' ' or target != candidate or not call or not local:
            continue
        if i + 1 < len(rows):
            stack_slot = re.fullmatch(rf'addiu \$a1, \$sp, {NUMBER}', rows[i + 1][1])
            if (stack_slot and rows[i + 1][2] == stack_slot[0].replace('$a1', '$a0', 1)
                    and (candidate_source := _forward_stack_output(source, name, header, asm, call[1], resolve))):
                return [(FAMILY, candidate_source)]
        if candidate_source := _pointer_call_reuse(source, name, header, asm, rows, i, call[1]):
            return [(FAMILY, candidate_source)]
        relocations = _relocated_shift_count(rows, local)
        if relocations is not None and i - local[0] <= 4 + relocations:
            nearby.append((call[1], i, local))
        elif (i + 1 in local and _shifted_narrow_reload(rows, changes, i + 1)
              and (candidate_source := _missing_caller_argument(source, name, header, asm, call[1]))):
            return [(FAMILY, candidate_source)]
    if len(nearby) != 1:
        return []
    selected, call, local = nearby[0]
    if forwarded := variants(source, name, asm=asm, arch='mips', header=header, require_evidence=True,
                             selected_call=selected, resolve=resolve):
        return forwarded
    if candidate := _missing_caller_argument(source, name, header, asm, selected):
        return [(FAMILY, candidate)]
    if candidate := _repeated_first_call(source, name, header, asm, selected, rows, local, call):
        return [(FAMILY, candidate)]
    return []


def _shifted_narrow_reload(rows, changes, slot):
    """An earlier byte or halfword calculation and the call reload use the same shifted argument."""
    load = re.fullmatch(rf'(lbu|lhu) \$a1, ({NUMBER})\((\$\w+)\)', rows[slot][1])
    if not load or rows[slot][2] != rows[slot][1].replace('$a1,', '$a0,', 1):
        return False
    return any(i < slot - 1 and re.fullmatch(rf'{load[1]} \$a1, {load[2]}\(\$\w+\)', rows[i][1])
               and rows[i][2] == rows[i][1].replace('$a1,', '$a0,', 1) for i in changes)
