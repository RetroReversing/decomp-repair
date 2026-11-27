"""A call's argument count from the target's own setup of the argument registers before it.

m2c guesses a callee's arity from what the caller seems to set up, and a constant it misses leaves the call one
argument short: an N64 function created its message queues with `osCreateMesgQueue(&q, msgs)` where the game wrote
`addiu $a2, $zero, 8` before each `jal`. The other way round, a draft passes a trailing argument the game never set.
For each callee, the target's calls (in order) say which of `$a0`-`$a3` were written before the `jal` or in its delay
slot; the C's calls to it, when there are as many, get the missing trailing arguments the target set to constants,
or lose the trailing ones the target never set. A prototype with parameters gains or loses the same ones.
"""
import re

from . import m2cfix
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'target_call_arity'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
LINE = re.compile(r'^\s*(?:/\*.*?\*/)?\s*(?P<op>[a-z][\w.]*)\s*(?P<args>[^\n]*)$')
ARGREG = ('a0', 'a1', 'a2', 'a3')
FLOAT_ARGS = {'f12': 'a0', 'fa0': 'a0', 'f14': 'a1', 'fa1': 'a1'}
STORES = ('sb', 'sh', 'sw', 'sd', 'sc', 'scd', 'swl', 'swr', 'sdl', 'sdr', 'swc1', 'sdc1', 'swc2', 'sdc2', 's.s', 's.d')
COPIES = ('move', 'addu', 'or', 'daddu')
NOT_CALLS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'M2C_FIELD', 'M2C_ERROR', 'M2C_BITWISE', 'do'}


def _instructions(asm):
    for line in (asm or '').splitlines():
        m = LINE.match(line)
        if m and not line.strip().startswith(('.', 'glabel', 'endlabel')) and not m['op'].endswith(':'):
            yield m['op'], m['args'].strip()


def _writes(op):
    """Whether an instruction's first operand is a register it writes: not a store, branch or jump. (The shifts,
    `subu` and `slt` start with `s` too: an N64 allocator's first argument, `sll $a0, $a2, 1` in the delay slot, was
    read as a store and left out.)"""
    return op not in STORES and not op.startswith(('b', 'j'))


def _scratch(op, args, written):
    """An argument register that arithmetic reads into an earlier one before the call held that argument's working
    value: `mult; mflo $a2; sll $a0, $a2, 1` passes one doubled product, not the product as a third argument. A plain
    copy (the same value passed twice) and a load (the register as a base) are left alone."""
    registers = re.findall(r'\$(\w+)', args)
    if len(registers) < 2 or registers[0] not in ARGREG or not _writes(op) or op.startswith(('l', 'm')):
        return
    if op == 'move' or op in COPIES and 'zero' in registers[1:]:
        return
    for read in registers[1:]:
        if read in ARGREG and ARGREG.index(read) > ARGREG.index(registers[0]):
            written.pop(read, None)


def calls(asm, consumed=False, through=False):
    """[(callee, {register: constant or None})] for each `jal`, in order: the argument registers written since the
    previous call or branch target, and in the delay slot.

    With `consumed`, an argument register whose value was stored (`sb $a0, D`), compared by a branch (`beq $a0,
    $v0`) or shifted or added into an earlier argument register (`_scratch`) before the call counts as not set up for it: a value m2c saw left in `$a0` and passed on. Three N64
    functions passed such a leftover (a byte just stored, a switch's selector, a word copied through `$a1`) to a
    callee that takes fewer arguments, and each was exact without it. A value can be both used and passed, so this
    is only an alternative reading, offered beside the ordinary one.

    With `through`, an argument register that a load or store used as its *base address* before the call counts as
    not set up for it too: a PS1/N64-era menu function held a record pointer in `$a1` (`lw $a1, 0($s1)`, then
    `lw $v1, 0x28($a1)` and `sw $v1, 0x28($a1)`) and called three callees that take one argument; the draft passed
    `$a1` to each, and the stray argument register changed the first scheduler's order of the next call's argument
    setup (a load that the target places after a shift stayed before it, 60 until the three calls lost it, then
    exact). A register is often both the pointer a function works through and its argument, so this too is only an
    alternative reading."""
    found = []
    written = {}
    pending = None
    bases = {}  # register -> symbol whose address it holds (`addiu $s2, $s2, %lo(D)`), for loads through it
    for op, args in _instructions(asm):
        dest = re.match(r'\$(\w+)', args)
        # Hard-float MIPS passes the first floating arguments in f12/f14, including writes in a call's delay slot.
        # Treat these as evidence of an argument, not as an absent a0/a1 to be dropped.
        float_dest = dest[1] if dest and op not in ('swc1', 'sdc1') and not op.startswith(('b', 'j')) else None
        if op in ('mtc1', 'dmtc1'):
            moved = re.fullmatch(r'\$\w+\s*,\s*\$(\w+)', args)
            float_dest = moved[1] if moved else None
        if float_dest in FLOAT_ARGS:
            written[FLOAT_ARGS[float_dest]] = None
        if dest and _writes(op) or op == 'jal':
            held = re.fullmatch(r'\$(\w+)\s*,\s*\$\1\s*,\s*%lo\(\s*(\w+)\s*\)', args) if op == 'addiu' else None
            if held:
                bases[held[1]] = held[2]
            elif dest and op != 'lui':
                bases.pop(dest[1], None)
        if pending is not None:  # the delay slot
            if consumed:
                _scratch(op, args, written)
            if dest and dest[1] in ARGREG and _writes(op):
                written[dest[1]] = _argument(op, args, bases, written)
            found.append((pending, written))
            pending, written = None, {}
            continue
        if op == 'jal':
            pending = args.split('+')[0].strip()
            continue
        store = op.startswith(('sw', 'sh', 'sb', 'sd', 'swc1', 'sdc1'))
        if through and op.startswith(('lw', 'lh', 'lb', 'sw', 'sh', 'sb', 'ld', 'sd')):
            base = re.search(r'\(\$(\w+)\)\s*$', args)
            if base and base[1] in ARGREG:
                written.pop(base[1], None)
        if consumed:
            _scratch(op, args, written)
            operands = re.findall(r'\$(\w+)', args)
            if store and operands and op not in ('swc1', 'sdc1'):
                written.pop(operands[0], None)  # (the stored value; the base register stays an argument)
            elif op.startswith('b') and op not in ('b',):
                for read in operands[:2]:
                    written.pop(read, None)
        # (an argument register read into a register that isn't one is a temporary, not an argument: an N64
        # function's `mfhi $a2` then `subu $v1, $a2, $v1` divided by three, and its calls took one argument)
        if dest and not store and dest[1] not in ARGREG and not op.startswith(('b', 'j')):
            for read in re.findall(r'\$(\w+)', args)[1:]:
                if read in ARGREG and read != dest[1]:
                    written.pop(read, None)
        if dest and dest[1] in ARGREG and not store and not (consumed and op.startswith(('b', 'j'))):
            # (a branch reads its first register, never writes it; the ordinary reading keeps counting it, as the
            # family always did, so only the alternative one changes)
            written[dest[1]] = _argument(op, args, bases, written)
    return found


def _argument(op, args, bases, written):
    """The value an argument register is given: `_constant`, or the constant another argument register already got when
    this one is its copy (`addiu $a1, $zero, 0x40` then `addu $a2, $a1, $zero`: the same literal passed twice, SN GCC
    2.8.1; an N64 object update's call was left one argument short without it)."""
    value = _constant(op, args, bases)
    copied = re.fullmatch(r'\$\w+\s*,\s*\$(a[0-3])(?:\s*,\s*\$zero)?', args) if op in ('addu', 'or', 'daddu', 'move') \
        else None
    if value is None and copied and (op == 'move') == (args.count('$') == 2):
        held = written.get(copied[1])
        value = held if isinstance(held, int) else None
    return value


def _constant(op, args, bases=None):
    # (a global loaded straight into the argument, `lbu $a1, %lo(D)($a1)` or through a register holding its address:
    # an N64 function passed `D_801002AD` as a second argument m2c left off, exact with it)
    load = re.fullmatch(r'\$\w+\s*,\s*(?:%lo\(\s*(\w+)\s*\)|(?:0x0|0)?)\(\$(\w+)\)', args) \
        if op in ('lb', 'lbu', 'lh', 'lhu', 'lw') else None
    if load:
        return load[1] or (bases or {}).get(load[2])
    m = re.fullmatch(r'\$\w+\s*,\s*\$zero\s*,\s*(-?(?:0x[0-9a-fA-F]+|\d+))', args)
    if op in ('addiu', 'ori', 'daddiu') and m:
        return int(m[1], 0)
    if op == 'move' and re.fullmatch(r'\$\w+\s*,\s*\$zero', args):
        return 0
    if op in ('addu', 'or', 'daddu') and re.fullmatch(r'\$\w+\s*,\s*\$zero\s*,\s*\$zero', args):
        return 0  # (`move $a0, $zero` as some assemblers write it)
    return None


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    prepared = calls(asm)
    result = _leading_pointer(source, name, clean, opening, end, prepared)
    result += _variants(source, name, asm, clean, opening, end, prepared)
    for text in _variants(source, name, asm, clean, opening, end, calls(asm, consumed=True)):
        if text not in result:
            result.append(text)
    for text in _variants(source, name, asm, clean, opening, end, calls(asm, through=True)):
        if text not in result:
            result.append(text)
    for reading in ({}, {'consumed': True}, {'through': True}, {'consumed': True, 'through': True}):
        merged = _merged(source, name, asm, reading)
        if merged and merged not in [t for _, t in result]:
            result.append((FAMILY, merged))
    return result[:10]


def _leading_pointer(source, name, clean, opening, end, prepared):
    """Try dropping a forwarded pointer before three same-width scalar arguments."""
    span = find(source, name)
    signature = re.search(rf'\b{re.escape(name)}\s*\(([^()]*)\)', clean[span[0]:opening])
    if not signature:
        return []
    pointers = set(re.findall(rf'\bvoid\s*\*\s*({IDENT})\s*(?=,|$)', signature[1]))
    if not pointers:
        return []
    result = []
    body = clean[opening:end]
    for callee, registers in prepared:
        if set(registers) != set(ARGREG[:3]) or sum(other == callee for other, _ in prepared) != 1:
            continue
        pattern = rf'\b{re.escape(callee)}\s*\('
        sites = list(re.finditer(pattern, body))
        declarations = list(re.finditer(pattern+r'([^()]*)\)\s*;', clean[:span[0]]))
        if len(sites) != 1 or len(declarations) != 1 or len(re.findall(pattern, clean)) != 2:
            continue
        proto = declarations[0]
        params = [param.strip() for param in proto[1].split(',')]
        if len(params) != 4 or not re.fullmatch(rf'void\s*\*\s*(?:{IDENT})?', params[0]):
            continue
        widths = [re.fullmatch(rf'([su](?:8|16|32))(?:\s+{IDENT})?', param) for param in params[1:]]
        if not all(widths) or len({width[1] for width in widths}) != 1:
            continue
        start = opening + sites[0].end()
        closing = close(clean, start - 1)
        if not closing:
            continue
        inner = clean[start:closing - 1]
        args = m2cfix._split_top_level(inner)
        if (len(args) != 4 or args[0].strip() not in pointers
                or not all(re.fullmatch(IDENT, arg.strip()) for arg in args[1:])):
            continue
        call_start = start + _offset(inner, 1) + 1
        proto_start = proto.start(1) + proto[1].index(',') + 1
        repaired = source[:start] + source[call_start:].lstrip(' \t')
        repaired = repaired[:proto.start(1)] + repaired[proto_start:].lstrip(' \t')
        result.append((FAMILY, repaired))
    return result


def _merged(source, name, asm, reading):
    """Every callee's change of one reading applied together. A stray trailing argument is the same mistake at each
    call of a function (m2c passed a leftover `$a1` to three one-argument callees), and one callee's change alone
    leaves the argument registers set up as before, so none of the single-callee children scores better; the
    whole set is the step. Only offered when it changes more than one callee."""
    text, changed = source, 0
    for _ in range(8):
        span = find(text, name)
        clean = _blank(text)
        opening = clean.find('{', span[0], span[1]) if span else -1
        end = close(clean, opening, '{', '}') if opening >= 0 else None
        if not end:
            break
        steps = [t for f, t in _variants(text, name, asm, clean, opening, end, calls(asm, **reading))
                 if len(t) < len(text)]
        if not steps:
            break
        text, changed = steps[0], changed + 1
    return text if changed > 1 else None


def _variants(source, name, asm, clean, opening, end, jals):
    targets = {}
    for callee, regs in jals:
        targets.setdefault(callee, []).append(regs)
    every = [m for m in re.finditer(r'\b(' + IDENT + r')\s*\(', clean[opening:end]) if m[1] not in NOT_CALLS]
    # (the target makes a call inside another's argument first: order the C's calls by where each one closes, so a
    # callee renamed in the assembly still pairs with its call when the C nests them)
    every.sort(key=lambda m: close(clean, opening + m.end() - 1) or 0)
    sites = {}
    # (the target's assembly may name a callee by its address, `func_800A1BB0`, where the C has its symbol: when
    # the C makes as many calls as the target and every name both share sits at the same place, pair them in order)
    by_order = len(every) == len(jals) and all(m[1] == j[0] for m, j in zip(every, jals) if m[1] in targets)
    for k, m in enumerate(every):
        if m[1] in targets or by_order:
            sites.setdefault(m[1], []).append(opening + m.end() - 1)
            if by_order and m[1] not in targets:
                targets.setdefault(('order', m[1]), []).append(jals[k][1])
    targets = {k[1] if isinstance(k, tuple) else k: v for k, v in targets.items()}
    result = []
    for callee, parens in sites.items():
        wanted = targets[callee]
        if len(parens) != len(wanted):
            continue
        add, drop = [], []
        call_shapes = []
        for paren, regs in zip(parens, wanted):
            closing = close(clean, paren)
            inner = clean[paren + 1:closing - 1]
            args = [a for a in m2cfix._split_top_level(inner)] if inner.strip() else []
            count = max((ARGREG.index(r) + 1 for r in regs), default=0)
            call_shapes.append((count, args))
            if len(args) < count <= 4:
                missing = [regs.get(ARGREG[i]) for i in range(len(args), count)]
                if any(v is None for v in missing):
                    add = None
                elif add is not None:
                    add.append((closing - 1, ''.join((', ' if (args or k) else '') + _number(v)
                                                     for k, v in enumerate(missing))))
            elif count < len(args) <= 4 and add == []:
                drop.append((paren + 1 + _offset(inner, count), closing - 1))
        # Integer register setup alone cannot disprove a declared floating parameter: its value can arrive in an
        # FPU register or remain live from earlier. In particular, never turn a float-taking callee into void.
        float_params = _float_parameters(clean, callee, opening)
        if any(any(index >= count for index in float_params if index < len(args)) for count, args in call_shapes):
            drop = []
        mixed_drop = _mixed_drop_safe(clean, call_shapes, len(drop), _plain_locals(clean[opening:end]))
        for edits, change in ((add, 'add'), (drop if len(drop) == len(parens) or mixed_drop else None, 'drop')):
            if not edits:
                continue
            text = source
            for a, b_or_text in sorted(edits, reverse=True, key=lambda e: e[0]):
                if change == 'add':
                    text = text[:a] + b_or_text + text[a:]
                else:
                    text = text[:a] + text[b_or_text:]
            text = _prototype(text, callee, name, change, edits, clean, parens)
            if text and text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
                # (an added global the target reads through a register holding its address: alone it scored worse
                # than the draft, 471 against 461, and only with the symbol held in a local too was it exact; offer
                # both steps at once, since a pass keeps only steps that improve)
                held = set(re.findall(r'\baddiu\s+\$(\w+)\s*,\s*\$\1\s*,\s*%lo\(\s*(\w+)\s*\)', asm))
                symbols = {sym for _, sym in held}
                if change == 'add' and any(sym in text_add for _, text_add in edits for sym in symbols):
                    from . import symbol_base_repairs
                    for _, both in symbol_base_repairs.variants(text, name)[:3]:
                        if both not in [t for _, t in result]:
                            result.append((FAMILY, both))
    return result



def _float_parameters(clean, callee, opening):
    """Positions explicitly declared as floating values, not pointers, in a prototype before the function."""
    proto = re.search(r'(?m)^[^\n;{}]*\b' + re.escape(callee) + r'\s*\(([^()]*)\)\s*;', clean[:opening])
    if not proto:
        return set()
    return {i for i, param in enumerate(proto[1].split(','))
            if '*' not in param and re.search(r'\b(?:float|double|f32|f64)\b', param)}

def _plain_locals(body):
    """The function body's non-volatile scalar locals: reading one has no effect, so dropping it as an argument is safe."""
    found = set()
    for m in re.finditer(r'(?m)^[ \t]*((?:(?:unsigned|signed|struct|const|volatile|register)\s+)*' + IDENT
                         + r')[ \t]+\**[ \t]*(' + IDENT + r')\s*;', body):
        if m[1] not in ('return', 'goto', 'else') and not m[1].startswith('volatile') and ' volatile' not in m[1]:
            found.add(m[2])
    return found


def _mixed_drop_safe(clean, shapes, dropped, plain=()):
    """Some calls already have the measured arity; at the others only drop one plain local, or one nonvolatile global
    pointer."""
    counts = {count for count, _ in shapes}
    if len(counts) != 1 or not dropped or dropped == len(shapes):
        return False
    count = counts.pop()
    if not count or any(len(args) < count or len(args) > count + 1 for _, args in shapes):
        return False
    for _, args in shapes:
        if len(args) == count:
            continue
        extra = args[-1].strip()
        if extra in plain:
            continue
        if (not re.fullmatch(IDENT, extra)
                or not re.search(rf'\bextern\s+void\s*\*\s*{re.escape(extra)}\s*;', clean)
                or re.search(rf'\bvolatile\b[^;]*\b{re.escape(extra)}\b', clean)
                or re.search(rf'(?m)^\s*#\s*define\s+{re.escape(extra)}\b', clean)):
            return False
    return True


def _number(value):
    if isinstance(value, str):
        return value
    return f'0x{value:X}' if value > 9 else str(value)


def _offset(inner, count):
    """Where the argument after the first `count` ends in `inner` (the comma before it included)."""
    depth = 0
    seen = 0
    for i, ch in enumerate(inner):
        depth += (ch in '([{') - (ch in ')]}')
        if depth == 0 and ch == ',':
            seen += 1
            if seen == count:
                return i if count else 0
    return 0 if count == 0 else len(inner)


def _prototype(text, callee, name, change, edits, clean, parens):
    """The callee's prototype changed to match, when it lists parameters; unchanged for `()` or none."""
    clean = _blank(text)
    span = find(text, name)
    outside_end = span[0] if span else len(text)
    proto = re.search(r'(?m)^[^\n;{}]*\b' + re.escape(callee) + r'\s*\(([^()]*)\)\s*;', clean[:outside_end])
    if not proto or not proto[1].strip() or proto[1].strip() == '...' or '...' in proto[1]:
        return text
    params = [p.strip() for p in proto[1].split(',')] if proto[1].strip() != 'void' else []
    call = re.search(r'\b' + re.escape(callee) + r'\s*\(', clean[span[0]:] if span else '')
    if not call:
        return text
    at = span[0] + call.end() - 1
    inner = clean[at + 1:close(clean, at) - 1]
    count = len(m2cfix._split_top_level(inner)) if inner.strip() else 0
    if change == 'add':
        params = params + ['s32'] * (count - len(params))
    else:
        params = params[:count]
    new = ', '.join(params) if params else 'void'
    return text[:proto.start(1)] + new + text[proto.end(1):]


def measured_variants(source, name, asm, rows, header=""):
    """Try dropping side-effect-free arguments absent from the measured call setup."""
    target = calls(asm, consumed=True)
    candidate = calls('\n'.join(row[2] for row in rows if row[2]), consumed=True)
    if len(target) != len(candidate) or not target:
        return []
    clean = _blank(source)
    span = find(source, name)
    if not span:
        return []
    opening = clean.find('{', span[0], span[1])
    body = clean[opening:span[1]]
    wanted = {}
    for (callee, target_regs), (other, candidate_regs) in zip(target, candidate):
        if callee != other:
            return []
        count = max((ARGREG.index(r) + 1 for r in target_regs), default=0)
        actual = max((ARGREG.index(r) + 1 for r in candidate_regs), default=0)
        if count and actual > count:
            wanted.setdefault(callee, set()).add(count)
    if not wanted:
        return []
    safe = {}
    for callee, counts in wanted.items():
        if len(counts) != 1:
            continue
        count = next(iter(counts))
        sites = list(re.finditer(r'\b' + re.escape(callee) + r'\s*\(', body))
        if not sites:
            continue
        shapes = []
        for site in sites:
            start = site.end() - 1
            end = close(body, start)
            args = m2cfix._split_top_level(body[start + 1:end - 1]) if end else []
            if len(args) < count:
                break
            shapes.append((count, args))
        else:
            extras = [arg.strip() for _, args in shapes for arg in args[count:]]
            literal = lambda arg: re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*', arg)
            if extras and all(literal(arg) for arg in extras):
                safe[callee] = count
            elif _mixed_drop_safe(_blank(header + '\n' + source), shapes,
                                  sum(len(args) > count for _, args in shapes)):
                # A local with the same name could hide the nonvolatile global.
                if not any(re.search(r'\b' + IDENT + r'\s+\**\s*' + re.escape(arg)
                                     + r'\s*(?:[;,=)\[])', clean[span[0]:span[1]]) for arg in extras):
                    safe[callee] = count
    if not safe:
        return []
    result = []
    for family, proposed in variants(source, name, asm):
        clean_proposed = _blank(proposed)
        new_span = find(proposed, name)
        if not new_span:
            continue
        new_body = clean_proposed[clean_proposed.find('{', new_span[0], new_span[1]):new_span[1]]
        for callee, count in safe.items():
            sites = list(re.finditer(r'\b' + re.escape(callee) + r'\s*\(', new_body))
            if sites and all((end := close(new_body, site.end() - 1)) and
                             len(m2cfix._split_top_level(new_body[site.end():end - 1])) == count for site in sites):
                result.append((family, proposed))
                break
    return result
