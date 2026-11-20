"""Give a guarded do-loop its own sentinel when MIPS compares two materializations."""
import re

from .call_lifetime_repairs import block_path
from .compiler_phase_repairs import facts, fresh
from .integer_repair_support import edit
from .pattern_repairs import close
from .target_call_constant_repairs import _code

FAMILY = 'loop_sentinel_placement'
TEST = re.compile(r'!=\s*(0[xX][A-Fa-f0-9]+|[1-9][0-9]*)[uU]?\s*$')
LOAD = re.compile(r'(\$\w+)\s*,\s*\$zero\s*,\s*(0[xX][A-Fa-f0-9]+|[1-9][0-9]*)')


def _number(text):
    return int(text, 16 if text.lower().startswith('0x') else 10)


def _target_sentinels(asm):
    instructions, labels = _code(asm)
    exits, loops = [], []
    for i, (opcode, args) in enumerate(instructions):
        match = LOAD.fullmatch(args) if opcode in {'ori', 'addiu'} else None
        if match is None:
            continue
        reg, literal = match.groups()
        value = _number(literal)
        if not 256 <= value <= (32767 if opcode == 'addiu' else 65535):
            continue
        for j in range(i + 1, min(i + 17, len(instructions))):
            op, operands = instructions[j]
            fields = [field.strip() for field in operands.split(',')]
            if op in {'beq', 'bne'} and len(fields) == 3 and reg in fields[:2]:
                dest = labels.get(fields[2])
                if op == 'beq' and dest is not None and dest > j:
                    exits.append((value, reg, j, dest))
                elif op == 'bne' and dest is not None and i < dest < j:
                    loops.append((value, reg, i, j))
                break
            if fields[0] == reg or op in {'jal', 'jalr', 'j', 'jr'}:
                break
    return {value for value, reg, branch, end in exits for loop_value, loop_reg, load, back in loops
            if value == loop_value and reg != loop_reg and branch + 1 < load < back < end}


def variants(source, name, header, arch, asm):
    if arch != 'mips' or not asm or not (values := _target_sentinels(asm)):
        return []
    part = facts(source, name, header, arch)
    if not part:
        return []
    result = []
    base = part.opening + 1
    for guard in re.finditer(r'\bif\s*\(', part.body):
        condition = base + guard.end() - 1
        end = close(part.clean, condition)
        if not end or not (outer := TEST.search(part.clean[condition+1:end-1])):
            continue
        value = _number(outer[1])
        opening = re.match(r'\s*{', part.clean[end:])
        if value not in values or not opening:
            continue
        brace = end + opening.end() - 1
        limit = close(part.clean, brace, '{', '}')
        if not limit:
            continue
        # A jump into this scope could skip initialization.
        if re.search(r'(?:^|[;{}])\s*[A-Za-z_]\w*\s*:', part.clean[brace+1:limit-1]):
            continue
        for loop in re.finditer(r'\bdo\s*{', part.clean[brace+1:limit-1]):
            at = brace + loop.end()
            if block_path(part, at) != [*block_path(part, brace), brace]:
                continue
            tail = close(part.clean, at, '{', '}')
            test = re.match(r'\s*while\s*\(', part.clean[tail:]) if tail else None
            if not test:
                continue
            start = tail + test.end()
            close_test = close(part.clean, start - 1)
            inner = TEST.search(part.clean[start:close_test-1]) if close_test else None
            if inner and _number(inner[1]) == value:
                token = fresh(source, header, 'repair_sentinel')
                result.append((FAMILY, edit(source, [
                    (brace+1, brace+1, f'\n        unsigned {token} = {outer[1]};'),
                    (start+inner.start(1), start+inner.end(1) + int(inner[0].rstrip().endswith(('u','U'))), token),
                ])))
                if len(result) == 2:
                    return result
    return result
