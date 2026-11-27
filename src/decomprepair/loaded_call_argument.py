"""A trailing argument m2c dropped that the target loads from memory beside another argument's load.

A callee that only hands its argument on (`s32 wrap(void) { s32 r = start(); ..; return r; }`) can be byte-exact with
no parameter, so its callers' drafts call it with nothing, and the families that trust the callee's definition or only
pass a local, a constant or a global add nothing. The caller's own bytes still say what it passed:

    lh $v0, %lo(index)($s1); sll $v0, $v0, 4; addu $v0, $v0, $s0; lw $a0, 0($v0); jal show         show(*(s32 *)(A));
    lh $v0, %lo(index)($s1); sll $v0, $v0, 4; addu $v0, $v0, $s0; lw $a0, 4($v0); jal wrap         wrap();

Both loads read through the same computed address, at offsets 0 and 4. The C already spells that address in the first
call's argument, so the second call gets `*(s32 *)((u8 *)(A) + 4)`. An N64 function (SN GCC 2.8.1 `-G0 -mips3 -O2`, 38
instructions) went 430 -> 35 with it, and `symbol_address_local` then reached 0.

The target's assembly is followed along straight-line code (a label or an unconditional jump forgets everything, a call
forgets the caller-saved registers). A register's value is a tree of symbol addresses, constants, shifts, sums and
loads. For each callee whose calls the C makes as often as the target (paired in order), a call with n arguments gets
more when the target loads `$a<n>` after the previous call, reads it nowhere else, and the load's address is the one
some call argument written `*(T *)(E)` or `M2C_FIELD(E, T *, k)` loads from, at some constant offset. MIPS only; the
judge decides each child."""
import re

from .integer_repair_support import edit, split_args, view
from .missing_call_argument_local import _calls, _declared_count
from .pattern_repairs import close

FAMILY = 'loaded_call_argument'
FAMILIES = (FAMILY,)

LIMIT = 4
ARGREG = ('a0', 'a1', 'a2', 'a3')
TYPES = {'lw': 's32', 'lh': 's16', 'lhu': 'u16', 'lb': 's8', 'lbu': 'u8'}
SAVED = {'s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7', 's8', 'fp', 'gp', 'sp', 'zero', '0'}
NO_WRITE = {'sb', 'sh', 'sw', 'sd', 'swl', 'swr', 'swc1', 'sdc1', 'mult', 'multu', 'div', 'divu', 'mtc1', 'nop'}
LINE = re.compile(r'^\s*(?:/\*.*?\*/)?\s*(?P<op>[a-z][\w.]*)\s*(?P<args>[^\n#]*)')
LABEL = re.compile(r'^\s*(?:glabel\s+\S+|[.\w$]+:)\s*$')
MEMORY = re.compile(r'^(?P<offset>%lo\([^)]*\)|-?(?:0x[0-9A-Fa-f]+|\d+))?\(\$(?P<base>\w+)\)$')
HIGH = re.compile(r'^%hi\((.*)\)$')
LOW = re.compile(r'^%lo\((.*)\)$')
CAST = re.compile(r'^\*\s*\(\s*[\w ]+?\*\s*\)\s*(?=\()')
FIELD = re.compile(r'^M2C_FIELD\s*\(')


def _number(text):
    try:
        return int(text, 0)
    except ValueError:
        return None


def _split(value):
    """(core, constant offset) of an address tree."""
    if value[0] == 'add':
        for part, other in ((value[1], value[2]), (value[2], value[1])):
            if part[0] == 'const':
                core, offset = _split(other)
                return core, offset + part[1]
    return value, 0


def _add(left, right):
    return ('add', *sorted((left, right), key=repr))


def _value(op, args, registers, unknown):
    """The tree an instruction leaves in its first register."""
    def read(text):
        name = text.lstrip('$')
        return ('const', 0) if name in ('zero', '0') else registers.get(name, ('entry', name))

    if op == 'lui' and len(args) == 2:
        hit = HIGH.match(args[1])
        number = _number(args[1])
        return ('high', hit[1]) if hit else ('const', number << 16) if number is not None else unknown
    if op in TYPES and len(args) == 2:
        hit = MEMORY.match(args[1])
        if not hit:
            return unknown
        low = LOW.match(hit['offset'] or '')
        base = read(hit['base'])
        if low:
            address = ('symbol', low[1])
            if base != ('high', low[1]):
                if base[0] != 'add' or ('high', low[1]) not in base[1:]:
                    return unknown
                address = _add(address, base[2] if base[1] == ('high', low[1]) else base[1])
            core, offset = _split(address)
        else:
            core, offset = _split(base)
            offset += _number(hit['offset'] or '0') or 0
        return ('load', op, core, offset)
    if op == 'addiu' and len(args) == 3:
        low = LOW.match(args[2])
        if low:
            return ('symbol', low[1]) if read(args[1]) == ('high', low[1]) else unknown
        number = _number(args[2])
        if number is None:
            return unknown
        base = read(args[1])
        return ('const', base[1] + number) if base[0] == 'const' else _add(base, ('const', number))
    if op == 'sll' and len(args) == 3 and _number(args[2]) is not None:
        return ('shift', read(args[1]), _number(args[2]))
    if op == 'move' and len(args) == 2:
        return read(args[1])
    if op in ('addu', 'or', 'daddu') and len(args) == 3:
        left, right = read(args[1]), read(args[2])
        if right == ('const', 0):
            return left
        if left == ('const', 0):
            return right
        return _add(left, right) if op != 'or' else unknown
    return unknown


def calls_loads(asm):
    """[(callee, {argument index: (load tree, set since the previous call and read nowhere else)})] in order."""
    registers, fresh, result = {}, set(), []
    pending = None  # ('call', callee) or ('jump',): applied after the delay slot
    for index, line in enumerate((asm or '').splitlines()):
        if LABEL.match(line):
            registers, fresh = {}, set()
            continue
        hit = LINE.match(line)
        if not hit or line.strip().startswith(('.', 'nonmatching', 'endlabel')):
            continue
        op = hit['op']
        args = [a.strip() for a in hit['args'].split(',') if a.strip()]
        transfer = None
        if op == 'jal' and args:
            transfer = ('call', args[0])
        elif op in ('j', 'jr', 'b'):
            transfer = ('jump',)
        elif not op.startswith(('b', 'j')):
            written = args[0].lstrip('$') if args and args[0].startswith('$') and op not in NO_WRITE else None
            for text in args[1 if written else 0:]:
                fresh.difference_update(re.findall(r'\$(\w+)', text))
            if written:
                registers[written] = _value(op, args, registers, ('unknown', index))
                fresh.add(written)
        else:
            fresh.difference_update(name for text in args for name in re.findall(r'\$(\w+)', text))
        if pending:
            if pending[0] == 'call':
                result.append((pending[1], {k: registers[reg] for k, reg in enumerate(ARGREG)
                                            if reg in fresh and registers.get(reg, ('',))[0] == 'load'}))
                registers = {r: v for r, v in registers.items() if r in SAVED}
                fresh = set()
            else:
                registers, fresh = {}, set()
        pending = transfer
    return result


def _anchor(text):
    """(address expression, constant offset from it) of a memory read written as a whole argument, else None."""
    text = text.strip()
    cast = CAST.match(text)
    if cast:
        if close(text, cast.end()) != len(text):
            return None
        expression, offset = text[cast.end() + 1:-1], 0
    else:
        field = FIELD.match(text)
        if not field or close(text, field.end() - 1) != len(text):
            return None
        inner = text[field.end():-1]
        parts = [inner[a:b].strip() for a, b in split_args(inner)]
        if len(parts) != 3 or _number(parts[2]) is None:
            return None
        expression, offset = parts[0], _number(parts[2])
    if re.search(r'\+\+|--|(?<![=!<>])=(?!=)|(?!(?:s|u)(?:8|16|32)\b)\b[A-Za-z_]\w*\s*\(', expression):
        return None
    return expression.strip(), offset


def _read(anchors, load):
    """The C that reads what `load` reads, through the first anchor with the same computed address."""
    _, op, core, offset = load
    for expression, anchored, base in anchors:
        if anchored != core:
            continue
        delta = offset - base
        address = expression if not delta else f'(u8 *)({expression}) {"+" if delta > 0 else "-"} {abs(delta):#x}'
        return f'*({TYPES[op]} *)({address})'
    return None


def variants(source, name, asm=None, header=''):
    part = view(source, name)
    if not part or not asm:
        return []
    targets = {}
    for callee, loads in calls_loads(asm):
        targets.setdefault(callee, []).append(loads)
    sites, anchors = [], []
    for callee, wanted in targets.items():
        spans = list(_calls(part, callee))
        if callee == name or len(spans) != len(wanted):
            continue
        for (start, stop), loads in zip(spans, wanted):
            inner = source[start:stop]
            args = [inner[a:b] for a, b in split_args(inner)] if inner.strip() else []
            sites.append((start, stop, callee, args, loads))
            for k, text in enumerate(args):
                found = _anchor(text)
                if found and k in loads:
                    anchors.append((found[0], loads[k][2], loads[k][3] - found[1]))
    changes = []  # (stop, callee, added text, new argument count)
    for _, stop, callee, args, loads in sorted(sites):
        added = []
        while len(args) + len(added) in loads:
            text = _read(anchors, loads[len(args) + len(added)])
            if text is None:
                break
            added.append(text)
        if added:
            count = len(args) + len(added)
            if _declared_count(header, callee) - {count}:
                continue
            changes.append((stop, callee, (', ' if args else '') + ', '.join(added), count))
    groups = [[change] for change in changes[:LIMIT]]
    if len(changes) > 1:
        groups.insert(0, changes)
    result = []
    for group in groups:
        edits = [(stop, stop, added) for stop, _, added, _ in group]
        for callee, count in {(callee, count) for _, callee, _, count in group}:
            declaration = re.search(rf'(?m)^[^\n;{{}}#]*\b{re.escape(callee)}\s*\(([^()]*)\)\s*;',
                                    part.clean[:part.opening])
            if declaration and declaration[1].strip() and '...' not in declaration[1]:
                params = [] if declaration[1].strip() == 'void' else declaration[1].split(',')
                if len(params) < count:
                    params += [' s32' if params else 's32'] * (count - len(params))
                    edits.append((declaration.start(1), declaration.end(1), ','.join(params)))
        text = edit(source, edits)
        if text != source and text not in [t for _, t in result]:
            result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'),
          'order': 60, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
