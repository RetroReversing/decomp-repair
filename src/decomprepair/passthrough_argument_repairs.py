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

from . import m2cfix
from .csource import _blank, find
from .integer_abi import scalar
from .pattern_repairs import close
from .target_call_arity_repairs import _instructions

FAMILY = 'passthrough_argument'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def variants(source, name, *, asm=None, arch=None, header='', callees='', require_evidence=False):
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
        if incoming is not None and (call[1] not in incoming or calls[call[1]] != 1):
            continue
        if len(args) >= 8:
            continue
        if not args and call[1] in unprototyped and len([n for n in names[:4] if n]) > 1 and None not in names[:4]:
            # (a callee handed all of the caller's own arguments untouched: nothing loads $a0-$a3 before the call, so
            # m2c drops them all; one N64 function, 40 points off with `f()`, was exact as `f(arg0, arg1, arg2)`,
            # the callee keeping its first `$a` registers live where the caller's saves expected them)
            text = source[:closing - 1] + ', '.join(names[:4]) + source[closing - 1:]
            if (incoming is None or _allows(call[1], range(len(names[:4])), len(names[:4]), incoming, header, callees)):
                result.append((FAMILY, text))
        for k, param in enumerate(names[:4]):
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
