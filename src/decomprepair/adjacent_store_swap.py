"""Two adjacent final stores of locals to unrelated globals or fields, written in the other order.

The shape (SN GCC 2.8.1, `-G0 -mips3 -O2`): a function ends with stores of two values it kept in locals

    G1 = a;  G2 = b;

The stores have no dependence, so the order in which they are written does not change what the program does, but it
does change the end of each local's live range, and the allocator ranks a pseudo by its references over its lifetime: the
local stored first dies first, takes the better-ranked saved register, and the two are exchanged when the statements are.
A function whose target has `$s1` stored before `$s0` (or the stores in the other order from the source's) is a
function whose pair was written the other way round.

The gate is the target's, as far as a target alone can give it: both stores are found in it, each of a register, the
two registers differ, and either the target stores them in the other order from the source's (a scheduler keeps the
order of stores to unrelated addresses unless the source's order is not the original's) or both are saved registers
(`$s0`-`$s7`, `$fp`) and the first one stored uses the higher-numbered register (the exchanged assignment). A target that
shows neither is not touched. That does not prove the swap is the fix, so only the stores at the very end of the function
are offered, at most LIMIT children, each judged.

`variants` takes the function's trailing run of plain stores `LVALUE = VALUE;` (a final `return` is ignored) whose values
are distinct locals or parameters, and whose lvalues are named globals (declared `extern`, or not declared in the function)
or fields of one base at offsets that do not overlap. One child swaps each adjacent pair of that run. Faithful: stores
to two different objects commute. This module reads text only and never compiles or judges."""
import re

from .hand_found_support import IDENT, RELOCATED, STORES, fields, instructions, memory, simple, stmts, store_target
from .integer_repair_support import edit, view

FAMILY = 'adjacent_store_swap'
FAMILIES = (FAMILY,)
LIMIT = 4
SAVED = re.compile(r'\$(?:s[0-7]|fp)')
FLOAT = re.compile(r'\$f(?:[vats]?\d+)')  # (a coprocessor 1 register: the stores of floats are not read)


def evidence(asm):
    """{key: (position, register)} of the last store of a register to each global symbol (`('sym', name)`) or field
    offset (`('off', offset)`) in the target."""
    found = {}
    for index, (op, args) in enumerate(instructions(asm)):
        if op not in STORES or len(args) != 2 or args[0] in ('$zero', '$at') or FLOAT.fullmatch(args[0]):
            continue
        hit = RELOCATED.search(args[1])
        if hit:
            found[('sym', hit['symbol'])] = (index, args[0])
        elif memory(args[1]) and memory(args[1])[1] != '$sp':  # (a stack slot is a spill, not a field)
            found[('off', memory(args[1])[0])] = (index, args[0])
    return found


def _key(lvalue):
    lvalue = lvalue.strip()
    if re.fullmatch(IDENT, lvalue):
        return ('sym', lvalue), None
    found = fields(lvalue)
    if found and found[0].start == 0 and found[0].end == len(lvalue):
        return ('off', found[0].offset), found[0]
    return None, None


def _number(register):
    return 30 if register == '$fp' else int(register[2:])


def variants(source, name, header='', arch='mips', asm=''):
    if arch != 'mips':
        return []
    seen = evidence(asm)
    part = view(source, name) if len(seen) >= 2 else None
    if not part:
        return []
    clean = part.clean
    spans = stmts(part, part.opening + 1, part.end - 1)
    while spans and re.match(r'\s*return\b', clean[spans[-1][0]:spans[-1][1]]):
        spans = spans[:-1]
    run = []
    for a, b in reversed(spans):  # (the trailing run of plain stores of a name or a number)
        text = clean[a:b]
        stored = store_target(text) if simple(text) else None
        key, field = _key(stored[0]) if stored else (None, None)
        if not key or not re.fullmatch(IDENT, stored[1].strip()):
            break
        run.append((a, b, key, field, stored[1].strip()))
    run.reverse()
    children = []
    for left, right in zip(run, run[1:]):
        if left[2] == right[2] or left[4] == right[4]:
            continue
        if left[3] and right[3] and (left[3].base != right[3].base or left[3].overlaps(right[3])):
            continue
        if bool(left[3]) != bool(right[3]):
            continue  # (a global and a field of a pointer may be one object)
        if left[2] not in seen or right[2] not in seen:
            continue
        (first, a), (second, b) = seen[left[2]], seen[right[2]]
        if a == b:
            continue
        reordered = first > second  # (the target stores the source's second statement first)
        exchanged = SAVED.fullmatch(a) and SAVED.fullmatch(b) and _number(a) > _number(b)
        if not (reordered or exchanged):
            continue
        text_a, text_b = source[left[0]:left[1]], source[right[0]:right[1]]
        gap = source[left[1]:right[0]]
        children.append((FAMILY, edit(source, [(left[0], right[1], text_b + gap + text_a)])))
    return list(dict.fromkeys(children))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'arch', 'asm'),
          'order': 70, 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
