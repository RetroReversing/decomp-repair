"""A compare against a literal, written through a local that is assigned something else right after the compare.

GCC 2.7 on MIPS has no compare-with-immediate for `beq`/`bne`, so `if (x == 4)` loads the 4 into a register. That
register is a one-instruction pseudo the local allocator places first, in `$v0` when nothing holds it. When a *local*
of the function is set to the literal just before the compare and assigned its real value right after (`result = 4;
if (index == result) ...; result = load;`), the literal and the later value are one multi-set pseudo that lives across
basic blocks: the global allocator takes it, beside the other long-lived values, and it lands in `$v1` (the target's
`addiu $v1,$zero,4; beq $a0,$v1`) where the lone constant took `$v0`.

Measured (one KMC GCC 2.7.2 `-G0 -mips3 -mgp32 -mfp32 -O2` function, an N64 table-entry predicate of 21
instructions, 10 -> 0): the compare constant going through `result`, which the next statement reloads, was the one
change left; no other spelling of the constant (a fresh local set at entry, a local set at the top, `four` folded back
to the literal by cse) moved the register. That the lone constant is a local-allocator quantity and the shared one is
a global-allocator pseudo is a hypothesis read from local-alloc.c and global.c; the score is the evidence.

Offered for an `if` whose condition compares a positive literal with `==`/`!=`, in a function with no loop and no
backward `goto`, when an ordinary integer local's next mention after the condition is a plain assignment at the same
brace depth that does not read the local, and no `goto` between the two lands (after that assignment) where the local
is read before a `return`. The local is then dead at the compare, so setting it to the literal first changes no value
the program computes: `L = K;` goes before the `if` and the condition names `L`. A candidate; the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, locals_for, refs, view
from .pattern_repairs import close
from .sentinel_local_repairs import COMPARE, _value

FAMILY = 'dead_local_constant_compare'
FAMILIES = (FAMILY,)
LIMIT = 8
IF = re.compile(r'\bif\s*\(')


def _limit(kind):
    bits = 8 if re.search(r'char|8$', kind) else 16 if re.search(r'short|16$', kind) else 32
    return (1 << (bits - 1)) - 1


def _depths(clean, start, end):
    """Brace depth before each position of `clean[start:end]`, as a list indexed from `start`."""
    depth, found = 0, []
    for char in clean[start:end]:
        found.append(depth)
        depth += (char == '{') - (char == '}')
    return found


def _dead_after(part, decl, stop, assign):
    """No path from the end of the compare's condition (`stop`) reads the local before `assign` rewrites it."""
    clean = part.clean
    name = decl['name']
    for jump in re.finditer(rf'\bgoto\s+({IDENT})\s*;', clean[stop:assign]):
        label = re.search(rf'(?<![\w.]){re.escape(jump[1])}\s*:(?!:)', clean[part.opening:part.end])
        if not label:
            return False
        where = part.opening + label.end()
        if where < stop:
            return False
        if where <= assign:
            continue
        tail = clean[where:part.end]
        ret = re.search(r'\breturn\b', tail)
        if not ret or re.search(rf'\b{re.escape(name)}\b', tail[:ret.start()]):
            return False
    return True


def _statement_start(clean, pos, opening):
    before = clean[opening+1:pos].rstrip()
    return not before or before[-1] in ';{}'


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:for|while|do|asm|__asm__)\b', part.body):
        return []
    clean = part.clean
    # a backward goto lets a value flow around the compare the other way
    for jump in re.finditer(rf'\bgoto\s+({IDENT})\s*;', clean[part.opening:part.end]):
        label = re.search(rf'(?<![\w.]){re.escape(jump[1])}\s*:(?!:)', clean[part.opening:part.end])
        if not label or label.start() < jump.start():
            return []
    depths = _depths(clean, part.opening, part.end)
    decls = [decl for decl in locals_for(part) if _limit(decl['type']) > 0]
    result = []
    for start in IF.finditer(clean, part.opening, part.end):
        paren = start.end() - 1
        stop = close(clean, paren)
        if not stop or not _statement_start(clean, start.start(), part.opening):
            continue
        condition = clean[paren:stop]
        site = None
        for found in COMPARE.finditer(condition):
            group = 'lit' if found['lit'] is not None else 'lit2'
            value = _value(found[group])
            if value > 0:
                site = (paren + found.start(group), paren + found.end(group), value)
                break
        if not site:
            continue
        for decl in decls:
            name_re = rf'\b{re.escape(decl["name"])}\b'
            if site[2] > _limit(decl['type']) or re.search(name_re, condition):
                continue
            later = [hit for hit in refs(part, decl) if hit.start() >= stop]
            if not later:
                continue
            first = later[0]
            tail = re.match(r'\s*=(?!=)([^;{}]*);', clean[first.end():])
            if (not tail or re.search(name_re, tail[1]) or not _statement_start(clean, first.start(), part.opening)
                    or depths[first.start() - part.opening] != depths[start.start() - part.opening]
                    or not _dead_after(part, decl, stop, first.start())):
                continue
            line = source.rfind('\n', 0, start.start()) + 1
            indent = re.match(r'[ \t]*', source[line:start.start()])[0] if not source[line:start.start()].strip() else '  '
            literal = source[site[0]:site[1]]
            assign = f'{decl["name"]} = {literal};\n{indent}'
            result.append((FAMILY, edit(source, [(start.start(), start.start(), assign),
                                                 (site[0], site[1], decl['name'])])))
            if len(result) >= LIMIT:
                return result
    return result
