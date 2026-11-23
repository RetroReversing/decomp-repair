"""A loop bound read through the address of a neighbouring global, at the top of the loop (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`).

The target of a save-slot rank loop (a `do`/`while (temp < gSaveTotalSlots)`) keeps the loop bound in one load before the
loop that is addressed off a register that already holds another global's address: `lw $t0, -0xc($t0)` where `$t0`
was set by `lui`/`addiu %lo(gVisibleSaveSlotCount)` for a volatile read at the top of the function. Neither the plain
read `while (temp < gSaveTotalSlots)` (cse puts the load of the first read in a register and the bound becomes `move
$t0, $a2`) nor `count[-3]` through the pointer (cse folds the pointer back into a symbol: `lui` + `lw %lo`) gives it.
What does is a read at the top of the loop body through a constant address with a symbol and an offset,
`limit = (&gVisibleSaveSlotCount)[-3];`: cse's related-value lookup (`cse.c`, `find_best_addr`, `use_related_value`) finds a register that
already holds `&gVisibleSaveSlotCount` and prefers `-12(reg)` to the two-insn symbolic address, loop.c moves the
read to the preheader (it is the loop's first insn, so `maybe_never` is still clear and the load, which may trap, is
allowed to move), and cse's second pass leaves the register form alone. A read written elsewhere in the body stays
in the loop, and in the loop condition it is folded back (hypothesis for the folding half: the toy compile showed it, `cse.c` was not
traced through). 215 -> 60 of the final 0 in a 154-instruction function.

`sibling_symbol_offset_read` needs the target's assembly as evidence: `addiu $r, $r, %lo(H)` and a later load with a
negative displacement from that same register (`lw $x, -0xc($r)`, `lh`, `lhu`, `lb`, `lbu`), the register not written
in between. For each `do { ... } while (... G ...);` whose condition names a global `G` declared as a plain integer of
the load's width, the condition's `G` is replaced by a new local `limit`, set as the body's first statement from
`((T *) &H)[-N]`. `H` and `G` are different symbols the program links at the addresses the assembly shows, so the
judge's bytes decide whether `G` is the one.
"""
import re

from .integer_repair_support import IDENT, edit, locals_for, view
from .pattern_repairs import close

FAMILY = 'sibling_symbol_offset_read'
FAMILIES = (FAMILY,)
LIMIT = 6
WIDTH = {'lw': ('s32', 4), 'lh': ('s16', 2), 'lhu': ('u16', 2), 'lb': ('s8', 1), 'lbu': ('u8', 1)}
TYPES = {'s32': 'lw', 'u32': 'lw', 'int': 'lw', 's16': 'lh', 'u16': 'lhu', 'short': 'lh', 's8': 'lb', 'u8': 'lbu',
         'char': 'lb'}
NEGATIVE = re.compile(r'\b(lw|lhu|lh|lbu|lb)\s+\$\w+,\s*-(0x[0-9A-Fa-f]+|\d+)\((\$\w+)\)')


def _evidence(asm):
    """[(symbol, op, offset)]: loads at a negative offset from a register that `%lo(symbol)` set and nothing rewrote."""
    found = []
    for load in NEGATIVE.finditer(asm):
        register = re.escape(load[3])
        before = asm[:load.start()]
        setter = None
        for hit in re.finditer(rf'addiu\s+{register},\s*{register},\s*%lo\(({IDENT})\)', before):
            setter = hit
        if not setter:
            continue
        between = before[setter.end():]
        if re.search(rf'^\s*(?:lw|lh|lhu|lb|lbu|addiu|addu|move|or|lui|sll|sra|srl|andi|ori|slt|slti|subu|xori|mfhi|mflo)\s+{register}\b',
                     between, re.M):
            continue
        item = (setter[1], load[1], int(load[2], 0))
        if item not in found:
            found.append(item)
    return found


def _globals(source):
    """{name: type} of the plain integer externs declared in the source."""
    return {m['name']: m['type'] for m in re.finditer(rf'(?m)^[ \t]*extern\s+(?P<type>[su](?:8|16|32)|int|short|char)\s+(?P<name>{IDENT})\s*;', source)}


def _do_loops(clean, start, stop):
    """[(body_open, body_close, cond_open, cond_close)] for each braced `do { } while (...);`."""
    for hit in re.finditer(r'\bdo\s*{', clean[start:stop]):
        body = start + hit.end() - 1
        end = close(clean, body, '{', '}')
        tail = re.compile(r'\s*while\s*\(').match(clean, end or 0)
        if not end or not tail:
            continue
        after = close(clean, tail.end() - 1)
        if after and re.compile(r'\s*;').match(clean, after):
            yield body, end, tail.end() - 1, after


def variants(source, name, asm=''):
    part = view(source, name)
    if not part or not asm or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    evidence = _evidence(asm)
    if not evidence:
        return []
    externs = _globals(source)
    clean = part.clean
    declared = [d for d in locals_for(part)]
    limit = 'limit'
    while re.search(rf'\b{limit}\b', clean):
        limit += '_'
    out = []
    for symbol, op, offset in evidence:
        kind, size = WIDTH[op]
        if offset % size or symbol not in externs:
            continue
        for body, end, cond_open, cond_close in _do_loops(clean, part.opening + 1, part.end - 1):
            cond = clean[cond_open + 1:cond_close - 1]
            for global_name, type_ in externs.items():
                if global_name == symbol or TYPES.get(type_) != op or not re.search(rf'(?<![\w.>]){global_name}\b', cond):
                    continue
                if len(re.findall(rf'(?<![\w.>]){global_name}\b', cond)) != 1 or re.search(r'\+\+|--|(?<![=!<>])=(?!=)', cond):
                    continue
                if re.search(rf'(?<![\w.>]){global_name}\b', clean[body:end]):
                    continue  # the bound is also read in the body: one read would no longer stand for both
                first = re.compile(r'\s*').match(clean, body + 1).end()
                indent = re.match(r'[ \t]*', clean[clean.rfind('\n', 0, first) + 1:first])[0] if '\n' in clean[body:first] else ' '
                line = f'{limit} = (({kind} *) &{symbol})[-{offset // size}];'
                new_cond = re.sub(rf'(?<![\w.>]){global_name}\b', limit, cond, count=1)
                edits = [(cond_open + 1, cond_close - 1, new_cond), (first, first, f'{line}\n{indent}')]
                if declared:
                    where = source.index('\n', declared[-1].end()) if '\n' in source[declared[-1].end():] else declared[-1].end()
                    edits.append((where, where, f'\n  {kind} {limit};'))
                else:
                    edits.append((part.opening + 1, part.opening + 1, f'\n  {kind} {limit};'))
                out.append((FAMILY, edit(source, edits)))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
