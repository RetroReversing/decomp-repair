"""A body adapted from another game's twin, brought to this target: its globals, its calls and what it never had.

A candidate copied from a matched look-alike in another game keeps what the copy could not translate. Seen on a KMC/SN
N64 command-polling loop with a jump-table switch (140 instructions, saved best 3260, exact after the edits below and one
statement move):

* **globals still carrying the donor's address names** (`D_8016A3B8`) that this target never touches. The target reaches
  its own through a `lui` held in a saved register (`lw $v0, -0x5C98($s5)`), so no `%lo(symbol)` names them and nothing
  that reads relocation names can pair them. The address is the held upper half plus the offset
  (`stale_global_refresh`);
* **two callees collapsed into one**: `f(2); .. f(1);` where the target passes 2 and 1 to another function `g` and calls
  `f` once, with no argument (`constant_call_retarget`), the call that is the switch's missing last case (`case N + 1:
  f(); break;`, read from the `sltiu` bound);
* **a call after the last loop** that the donor did not make (`missing_exit_call`: the constants set up between the last
  backward branch and the epilogue).

`adapted_body_refresh` offers all of them at once, with `renamed_callee_refresh`'s pairing, because each alone can leave
the score unchanged; the single edits follow. Every child is a hypothesis about which symbol or call the target has; the
judge decides it.
"""
import re

from . import renamed_callee_refresh
from .csource import _blank
from .integer_repair_support import view
from .pattern_repairs import close

FAMILY = 'adapted_body_refresh'
FAMILY_GLOBAL = 'stale_global_refresh'
FAMILY_CALL = 'constant_call_retarget'
FAMILY_EXIT = 'missing_exit_call'
FAMILIES = (FAMILY, FAMILY_GLOBAL, FAMILY_CALL, FAMILY_EXIT)

_WIDTHS = {'lb': 1, 'lbu': 1, 'sb': 1, 'lh': 2, 'lhu': 2, 'sh': 2, 'lw': 4, 'sw': 4, 'lwc1': 4, 'swc1': 4}
_TYPES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4, 'float': 4}
_REGISTER = r'\$\w+'
_NUMBER = r'-?(?:0x[0-9A-Fa-f]+|\d+)'
_ARGUMENTS = ('$a0', '$a1', '$a2', '$a3')
_BRANCH = re.compile(r'(?:b|beq|bne|blez|bgtz|bltz|bgez|beqz|bnez|beql|bnel|beqzl|bnezl|j)$')


def _instructions(asm):
    """[(mnemonic, [operands])] and {label: index of the instruction it precedes}."""
    found, labels = [], {}
    for line in asm.splitlines():
        text = re.sub(r'/\*.*?\*/', '', line).split('#', 1)[0].strip()
        if not text:
            continue
        label = re.fullmatch(r'(?:alabel\s+|dlabel\s+)?([.\w$]+):|(?:alabel|dlabel)\s+([.\w$]+)', text)
        if label:
            labels[label[1] or label[2]] = len(found)
            continue
        if text.split()[0] in ('glabel', 'endlabel', 'nonmatching', 'enddlabel') or text.startswith('.'):
            continue
        parts = text.split(None, 1)
        found.append((parts[0], [item.strip() for item in parts[1].split(',')] if len(parts) > 1 else []))
    return found, labels


def _number(text):
    return int(text, 0)


def _upper(operand):
    """The upper half a `lui` operand loads, or None."""
    if hit := re.fullmatch(r'\(\s*(0x[0-9A-Fa-f]+)\s*>>\s*16\s*\)', operand):
        return _number(hit[1]) >> 16
    if hit := re.fullmatch(r'%hi\(D_([0-9A-F]{8})\)', operand):
        return (int(hit[1], 16) + 0x8000) >> 16
    return _number(operand) if re.fullmatch(r'0x[0-9A-Fa-f]+|\d+', operand) else None


def _accesses(code):
    """{address: width} of the loads and stores whose address the assembly fixes: `%lo(D_...)`, or an offset from a
    register whose only value in the function is one `lui` (the epilogue's restore aside)."""
    writes = {}
    for op, args in code:
        if not args or op.startswith('s') and op in _WIDTHS or _BRANCH.match(op) or op in ('jr', 'jal'):
            continue
        if op == 'lw' and args[-1].endswith('($sp)'):
            continue
        writes.setdefault(args[0], []).append((op, args))
    held = {}
    for register, made in writes.items():
        if len(made) == 1 and made[0][0] == 'lui' and (upper := _upper(made[0][1][1])) is not None:
            held[register] = upper
    found = {}
    for op, args in code:
        if op not in _WIDTHS or len(args) != 2:
            continue
        if hit := re.fullmatch(rf'%lo\(D_([0-9A-F]{{8}})(?:\s*\+\s*({_NUMBER}))?\)\({_REGISTER}\)', args[1]):
            address = int(hit[1], 16) + (_number(hit[2]) if hit[2] else 0)
        elif (hit := re.fullmatch(rf'({_NUMBER})\(({_REGISTER})\)', args[1])) and hit[2] in held:
            address = ((held[hit[2]] << 16) + _number(hit[1])) & 0xFFFFFFFF
        else:
            continue
        found[address] = _WIDTHS[op]
    return found


def _stale_globals(source, asm, code):
    """{stale name: the target's name}: scalar `D_` externs the target never touches paired, width by width and in
    address order, with the addresses it does touch that the source never names."""
    accessed = {address: width for address, width in _accesses(code).items() if 0x80000000 <= address < 0x80800000}
    clean = _blank(source)
    used = {int(hit, 16) for hit in re.findall(r'\bD_([0-9A-F]{8})\b', clean)}
    declared = {}
    for hit in re.finditer(r'(?m)^[ \t]*extern[ \t]+(\w+)[ \t]+(D_([0-9A-F]{8}))[ \t]*;', clean):
        address = int(hit[3], 16)
        if hit[1] in _TYPES and address not in accessed and hit[2] not in asm:
            declared[hit[2]] = _TYPES[hit[1]]
    free = {address: width for address, width in accessed.items() if address not in used}
    pairs = {}
    for width in sorted(set(declared.values())):
        old = sorted(name for name, size in declared.items() if size == width)
        new = sorted(address for address, size in free.items() if size == width)
        if len(old) == len(new):
            pairs.update((name, f'D_{address:08X}') for name, address in zip(old, new))
    return pairs


def _rename(source, pairs):
    if not pairs:
        return source
    pattern = re.compile(rf'\b(?:{"|".join(map(re.escape, pairs))})\b')
    return pattern.sub(lambda hit: pairs[hit[0]], source)


def _constant(code, index, register):
    """The constant `register` holds after the instruction `code[index]` when it sets it from nothing else, or None."""
    if not 0 <= index < len(code):
        return None
    op, args = code[index]
    if not args or args[0] != register:
        return None
    if op in ('move', 'addu', 'or') and all(item == '$zero' for item in args[1:]):
        return 0
    if op == 'li' and re.fullmatch(_NUMBER, args[1]):
        return _number(args[1])
    if op in ('addiu', 'ori') and len(args) == 3 and args[1] == '$zero' and re.fullmatch(_NUMBER, args[2]):
        return _number(args[2])
    return None


def _calls(code):
    """[(callee, the constant first argument set beside the jal, or None)]."""
    found = []
    for index, (op, args) in enumerate(code):
        if op != 'jal' or not args:
            continue
        value = _constant(code, index + 1, '$a0')
        found.append((args[0], _constant(code, index - 1, '$a0') if value is None else value))
    return found


def _site(name):
    return re.compile(rf'(?<![\w.>]){re.escape(name)}\((\s*)(0x[0-9A-Fa-f]+|\d+)(\s*)\)(?=\s*;)')


def _declare(source, part, callee, header, argument):
    if re.search(rf'\b{re.escape(callee)}\s*\(', _blank(header)):
        return source
    if re.search(rf'(?m)^[^\n=]*\b{re.escape(callee)}\s*\([^;{{}}()]*\)\s*;', _blank(source)[:part.opening]):
        return source
    start = source.rfind('\n', 0, _definition(source, part)) + 1
    return source[:start] + f'void {callee}({argument});\n' + source[start:]


def _definition(source, part):
    """Where the function's definition line starts (before the comments that lead it)."""
    head = part.clean[:part.opening]
    at = max(head.rfind(';'), head.rfind('}')) + 1
    return at + len(head[at:]) - len(head[at:].lstrip())


def _retarget(source, name, code, header):
    """The source with each call passing a constant its callee is never given moved to the one callee that is given it."""
    calls = _calls(code)
    part = view(source, name)
    if not part:
        return source
    given = {(callee, value) for callee, value in calls if value is not None}
    targets = {callee for callee, _ in calls}
    body = part.clean[part.opening:part.end]
    edits, moved = [], {}
    for callee in sorted(targets):
        for hit in _site(callee).finditer(body):
            value = int(hit[2], 0)
            if (callee, value) in given:
                continue
            others = [other for other, got in given if got == value and not _site_has(body, other, value)]
            if len(others) != 1:
                continue
            start = part.opening + hit.start()
            edits.append((start, start + len(callee), others[0]))
            moved.setdefault(callee, set()).add(others[0])
    if not edits:
        return source
    result = source
    for start, end, text in sorted(edits, reverse=True):
        result = result[:start] + text + result[end:]
    for callee, others in sorted(moved.items()):
        left = view(result, name)
        remaining = re.search(rf'(?<![\w.>]){re.escape(callee)}\s*\(', left.clean[left.opening:left.end])
        bare = [value for other, value in calls if other == callee]
        if not remaining and bare and all(value is None for value in bare):
            result = re.sub(rf'(?m)^([^\n=]*\b{re.escape(callee)}\s*\()\s*[su](?:8|16|32)\s*(\)\s*;)', r'\1void\2', result)
            if len(bare) == 1:
                result = _missing_case(result, name, code, callee)
        for other in sorted(others):
            result = _declare(result, view(result, name), other, header, 's32')
    return result


def _site_has(body, callee, value):
    return any(int(hit[2], 0) == value for hit in _site(callee).finditer(body))


def _bounds(code):
    """(lowest case, number of jump-table entries) of the function's one dense switch, or None."""
    found = []
    for index, (op, args) in enumerate(code):
        if op != 'sltiu' or len(args) != 3 or not re.fullmatch(_NUMBER, args[2]):
            continue
        base = 0
        # the subtraction can sit in an earlier branch's delay slot, several instructions above the test
        for earlier, operands in reversed(code[max(0, index - 16):index]):
            if operands and operands[0] == args[1]:
                if earlier == 'addiu' and len(operands) == 3 and re.fullmatch(_NUMBER, operands[2]):
                    base = -_number(operands[2])
                break
        if any(later == 'jr' and operands != ['$ra'] for later, operands in code[index:index + 9]):
            found.append((base, _number(args[2])))
    return found[0] if len(found) == 1 else None


def _missing_case(source, name, code, callee):
    """`case N: callee(); break;` after the last case when the jump table has exactly one entry more than the cases."""
    bounds = _bounds(code)
    part = view(source, name)
    if not bounds or not part:
        return source
    body = part.clean[part.opening:part.end]
    switches = list(re.finditer(r'\bswitch\s*\([^{};]*\)\s*\{', body))
    if len(switches) != 1:
        return source
    opening = part.opening + switches[0].end() - 1
    stop = close(part.clean, opening, '{', '}')
    if stop is None:
        return source
    inside = part.clean[opening:stop]
    cases = [int(hit, 0) for hit in re.findall(r'\bcase\s+(0x[0-9A-Fa-f]+|\d+)\s*:', inside)]
    last = bounds[0] + bounds[1] - 1
    if not cases or max(cases) != last - 1 or re.search(r'\bdefault\s*:', inside):
        return source
    brace = stop - 1
    if not re.search(r'\bbreak\s*;\s*$', part.clean[opening:brace]):
        return source
    at = source.rfind('\n', 0, brace) + 1
    labels = re.findall(r'(?m)^([ \t]*)case\b', source[opening:brace])
    indent = labels[-1] if labels else '    '
    return source[:at] + f'{indent}case {last}:\n{indent}    {callee}();\n{indent}    break;\n' + source[at:]


def _exit_call(code, labels):
    """(callee, [constant arguments]) of the one call between the last backward branch and the epilogue."""
    back = [index for index, (op, args) in enumerate(code)
            if _BRANCH.match(op) and args and labels.get(args[-1], len(code)) <= index]
    if not back:
        return None
    values, call, finished = {}, None, False
    index = back[-1] + 1
    while index < len(code):
        op, args = code[index]
        if op == 'jr' or (op == 'lw' and args and args[0] == '$ra'):
            break
        if op == 'jal':
            if call or index + 1 >= len(code):
                return None
            call = args[0]
            slot = code[index + 1]
            if slot[1] and slot[1][0] in _ARGUMENTS:
                value = _constant(code, index + 1, slot[1][0])
                if value is None:
                    return None
                values[slot[1][0]] = value
            index += 2
            finished = True
            continue
        if finished or not args:
            if op != 'nop':
                return None
        elif args[0] in _ARGUMENTS:
            if op == 'lui' and (upper := _upper(args[1])) is not None:
                values[args[0]] = upper << 16
            elif op in ('ori', 'addiu') and args[1] == args[0] and args[0] in values:
                low = re.fullmatch(r'\(\s*(0x[0-9A-Fa-f]+)\s*&\s*0xFFFF\s*\)', args[2])
                if low:
                    values[args[0]] |= _number(low[1]) & 0xFFFF
                elif re.fullmatch(_NUMBER, args[2]):
                    values[args[0]] += _number(args[2])
                else:
                    return None
            elif (value := _constant(code, index, args[0])) is not None:
                values[args[0]] = value
            else:
                return None
        index += 1
    if not call or sorted(values) != list(_ARGUMENTS[:len(values)]):
        return None
    return call, [values[register] for register in _ARGUMENTS[:len(values)]]


def _append_exit_call(source, name, code, labels):
    found = _exit_call(code, labels)
    part = view(source, name)
    if not found or not part or not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(', part.clean[:part.opening]):
        return source
    callee, values = found
    brace = part.clean.rindex('}', part.opening, part.end)
    tail = part.clean[part.opening:brace].rstrip()
    # only after a loop that ends the function: any other ending may already be the call, spelled differently
    if not re.search(r'(?:\}\s*while\s*\(.*\)\s*;|\})$', tail):
        return source
    if re.search(r'\breturn\b', tail):
        return source
    arguments = ', '.join(f'0x{value:08X}' if value > 0xFFFF else str(value) for value in values)
    indent = re.search(r'\n([ \t]+)\S', source[part.opening:brace])
    indent = indent[1] if indent else '    '
    at = part.opening + len(tail)
    return source[:at] + f'\n{indent}{callee}({arguments});' + source[at:]


def variants(source, name, asm='', header=''):
    part = view(source, name)
    if not part or not asm:
        return []
    code, labels = _instructions(asm)
    if not code or len(code) > 4096:
        return []
    singles = [(FAMILY_GLOBAL, _rename(source, _stale_globals(source, asm, code))),
               (FAMILY_CALL, _retarget(source, name, code, header)),
               (FAMILY_EXIT, _append_exit_call(source, name, code, labels))]
    singles = [(family, child) for family, child in singles if child != source]
    if not singles:
        return []
    whole = _retarget(source, name, code, header)
    for _, child in renamed_callee_refresh.variants(whole, name, asm):
        whole = child
    whole = _rename(whole, _stale_globals(whole, asm, code))
    whole = _append_exit_call(whole, name, code, labels)
    combined = [(FAMILY, whole)] if whole not in [child for _, child in singles] else []
    return combined + singles


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',),
          'order': 20}
