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
NOT_CALLS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'M2C_FIELD', 'M2C_ERROR', 'M2C_BITWISE', 'do'}


def _instructions(asm):
    for line in (asm or '').splitlines():
        m = LINE.match(line)
        if m and not line.strip().startswith(('.', 'glabel', 'endlabel')) and not m['op'].endswith(':'):
            yield m['op'], m['args'].strip()


def calls(asm, consumed=False, through=False):
    """[(callee, {register: constant or None})] for each `jal`, in order: the argument registers written since the
    previous call or branch target, and in the delay slot.

    With `consumed`, an argument register whose value was stored (`sb $a0, D`) or compared by a branch (`beq $a0,
    $v0`) before the call counts as not set up for it: a value m2c saw left in `$a0` and passed on. Three N64
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
        if dest and not op.startswith(('s', 'b', 'j')) or op == 'jal':
            held = re.fullmatch(r'\$(\w+)\s*,\s*\$\1\s*,\s*%lo\(\s*(\w+)\s*\)', args) if op == 'addiu' else None
            if held:
                bases[held[1]] = held[2]
            elif dest and op != 'lui':
                bases.pop(dest[1], None)
        if pending is not None:  # the delay slot
            if dest and dest[1] in ARGREG and not op.startswith(('s', 'b', 'j')):
                written[dest[1]] = _constant(op, args, bases)
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
            written[dest[1]] = _constant(op, args, bases)
    return found


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
        mixed_drop = _mixed_drop_safe(clean, call_shapes, len(drop))
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


def _mixed_drop_safe(clean, shapes, dropped):
    """Some calls already have the measured arity; only drop a plain nonvolatile global pointer at the others."""
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
