"""The arguments a call lacks when the target copies them from the caller's records to the stack.

m2c, with no prototype for a callee, stops at the four register arguments. The rest go to `0x10($sp)` and above, and
when each is a word copied straight from memory (`lwc1 $f0, 4($a1); swc1 $f0, 0x14($sp)`) no local appears either, so
the draft's call is simply short, and the float words the other registers carry are typed as integers:

    lwc1 $f0, 0($a2); swc1 $f0, 0x10($sp)             f(&m, M2C_FIELD(arg0, s32 *, 0), ..4, ..8);
    lwc1 $f0, 0($a1); swc1 $f0, 0x14($sp)      ->     f(&m, *(float *)((char *)arg0 + 0), ..4, ..8,
    ...                                                 *(float *)((char *)arg2 + 0), *(float *)((char *)arg1 + 0), ..);
    lw $a1, 0($a0); lw $a2, 4($a0); jal f

`stack_argument_tail` appends only zeros and constants, `stack_argument_value` only words m2c kept in an `spNN` local
and `loaded_call_argument` one register argument. An N64 function of 37 instructions (SN GCC 2.8.1 `-G0 -mips3 -O2`)
that sets a matrix from three records scored 1614 as its machine draft and was exact with the second child here.

The evidence is the target: in the block of the call's `jal` (with its delay slot), each stack word is stored from a
register last loaded through an argument register nothing had written yet. Two children are offered: the missing words
appended and the callee's prototype widened; and, when a stack word travelled through a float register, the register
arguments loaded from the caller's records typed `float` as well (after a pointer, o32 carries floats in `$a1`-`$a3`)."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, calls, edit, split_args, view
from .stack_argument_tail import _BRANCH, _calls

FAMILY = 'loaded_stack_arguments'
FAMILIES = (FAMILY,)
MAXIMUM = 16  # words
_ARGUMENTS = ('a0', 'a1', 'a2', 'a3')
_LOAD = re.compile(r'\b(lw|lwc1)\s+\$(\w+)\s*,\s*(-?(?:0x[0-9a-fA-F]+|\d+))?\s*\(\$(\w+)\)')
_STORE = re.compile(r'\b(?:sw|swc1)\s+\$(\w+)\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)')
_WRITE = re.compile(r'\b(?!(?:sw|sb|sh|swl|swr|sd|swc1|sdc1|jal|jr|j|nop)\b)(?!b)[a-z][\w.]*\s+\$(\w+)\s*,')
_UNCONDITIONAL = re.compile(r'\b(?:jr|j|b)\s')
_FLOATING = re.compile(r'\b(?:float|double|f32|f64)\b')


def _written(line):
    hit = _WRITE.search(line)
    return hit[1] if hit else None


def target_loads(asm):
    """{callee: {argument index: (argument register number, offset, in a float register)}}: the words each call's block
    loads through the caller's own argument registers, in `$a1`-`$a3` and at 0x10($sp) and above (those only while
    contiguous)."""
    found = {}
    for callee, block, saves, lines, start in _calls(asm):
        if any(re.search(r'\bjalr?\s', line) for line in lines[:start]):
            continue
        entry = next((at for at, line in enumerate(lines) if _BRANCH.search(line)), len(lines))
        clobbered = {_written(line) for line in lines[:min(entry + 2, start)]}
        if start and _UNCONDITIONAL.search(lines[start - 1]):
            block = block[1:]  # the delay slot of the jump that ends the other path
        values, stores, registers = {}, {}, {}
        for text in block:
            store = _STORE.search(text)
            if store and (store[1], int(store[2], 0)) not in saves:
                stores[int(store[2], 0)] = values.get(store[1])
                continue
            written = _written(text)
            if not written:
                continue
            load = _LOAD.search(text)
            value = None
            if load and load[4] in _ARGUMENTS and load[4] not in clobbered:
                value = (_ARGUMENTS.index(load[4]), int(load[3] or '0', 0), load[1] == 'lwc1')
            values[written] = value
            clobbered.add(written)
            if written in _ARGUMENTS:
                registers[_ARGUMENTS.index(written)] = value
        words = {index: value for index, value in registers.items() if index and value}
        offset = 0x10
        while stores.get(offset) and offset // 4 < MAXIMUM:
            words[offset // 4] = stores[offset]
            offset += 4
        if 4 in words and len(words) > len(found.get(callee, {})):
            found[callee] = words
    return found


def _parameters(part, name):
    """The caller's parameter names by argument register, up to the first that is not a plain word."""
    head = None
    for head in re.finditer(rf'\b{re.escape(name)}\s*\(([^(){{}};]*)\)\s*$', part.clean[:part.opening]):
        pass
    names = []
    for start, end in split_args(head[1]) if head else []:
        text = head[1][start:end].strip()
        ident = re.search(rf'({IDENT})\s*$', text)
        if not ident or text == 'void' or ('*' not in text and (_FLOATING.search(text) or 'long long' in text)):
            break
        names.append(ident[1])
    return names[:4]


def _spelled(parameter, offset, floating):
    return f'*({"float" if floating else "int"} *)((char *){parameter} + {offset:#x})'


def _child(part, source, name, callee, words, names, header, retype):
    total = max(words) + 1
    floating = any(value[2] for index, value in words.items() if index >= 4)
    spans, counts, first = [], set(), []
    for start, end in calls(part, callee):
        arguments = [(start + a, start + b) for a, b in split_args(part.clean[start:end])]
        count = len(arguments)
        if not 1 <= count < total or not all(index in words for index in range(count, total)):
            return None
        counts.add(count)
        first = first or [source[a:b].strip() for a, b in arguments]
        added = [_spelled(names[words[i][0]], words[i][1], words[i][2]) for i in range(count, total)]
        spans.append((end, end, ''.join(f', {text}' for text in added)))
        for index in range(1, min(count, 4)):
            if retype and index in words:
                a, b = arguments[index]
                lead = len(source[a:b]) - len(source[a:b].lstrip())
                spans.append((a + lead, b, _spelled(names[words[index][0]], words[index][1], True)))
    if len(counts) != 1:
        return None
    count = counts.pop()

    def kind(index, old):
        if index in words and (index >= count or (retype and index < 4)):
            return 'float' if words[index][2] or (retype and floating) else 'int'
        return old

    prototype = None
    for prototype in re.finditer(
            rf'(?m)^[ \t]*(?:{IDENT}[ \t*]+)+{re.escape(callee)}\s*\(([^(){{}};]*)\)\s*;', part.clean[:part.opening]):
        break
    if prototype:
        text = prototype[1]
        old = [text[a:b].strip() for a, b in split_args(text)]
        if '...' in text:
            return None
        if not old or old == ['void']:
            old = ['void *' if value.startswith('&') else 'int' for value in first]
        if len(old) != count:
            return None
        types = [kind(index, old[index] if index < count else None) for index in range(total)]
        spans.append((prototype.start(1), prototype.end(1), ', '.join(types)))
    elif re.search(rf'\b{re.escape(callee)}\b', _blank(header)):
        return None
    else:
        types = [kind(index, 'void *' if index < count and first[index].startswith('&') else 'int')
                 for index in range(total)]
        at = part.clean.rfind('\n', 0, part.clean.rfind(name, 0, part.opening)) + 1
        spans.append((at, at, f'void {callee}({", ".join(types)});\n'))
    return edit(source, spans)


def variants(source, name, asm, header=''):
    part = view(source, name)
    if not part or not asm:
        return []
    names = _parameters(part, name)
    result = []
    for callee, words in target_loads(asm).items():
        if any(value[0] >= len(names) for value in words.values()):
            continue
        floating = any(value[2] for index, value in words.items() if index >= 4)
        for retype in [False, True] if floating else [False]:
            child = _child(part, source, name, callee, words, names, header, retype)
            if child and (FAMILY, child) not in result:
                result.append((FAMILY, child))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}
