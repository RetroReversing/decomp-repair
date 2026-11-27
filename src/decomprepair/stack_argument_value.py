"""A fifth (and later) argument m2c left in an `spNN` local: passed in the call, with the callee's prototype widened.

The o32 convention passes arguments past the fourth word at `0x10($sp)`, `0x14($sp)`, ... m2c, writing a prototype of
four parameters, shows such a store as an assignment to a frame local instead and drops it from the call:

    M2C_UNK g(s32, void *, f32, f32);            M2C_UNK g(s32, void *, f32, f32, f32);
    sp10 = -p->z * 0.2f;                  ->     g(i, p, x, y, -p->z * 0.2f);
    g(i, p, x, y);

The local then takes a frame slot of its own and, being read nowhere, is the wrong code. Where the local is also one of
the register arguments (`sp10 = 0.0f; g(i, p, sp10, 0.001f);`, a `lw $a2, 0x10($sp)` after the store) and its value is
a literal, the literal is written there too. A 146-instruction KMC GCC 2.7.2 `-O1` function went 10120 -> 8896 on its
m2c draft with this alone, and 6048 -> 4505 after its tables were one record array.

The evidence is the target: a `sw`/`swc1` into each word the call lacks, in the block of its `jal` (or its delay
slot). `spNN` is taken only when every use of it is such an assignment directly before the call (no braces between) or
an argument of that call. `stack_argument_tail` appends the zero words a draft lacks without a local."""
import re

from .integer_repair_support import IDENT, edit, split_args, view

FAMILY = 'stack_argument_value'
FAMILIES = (FAMILY,)
_CALL = re.compile(rf'\bjal\s+({IDENT})')
_BRANCH = re.compile(r'\b(?:jalr?|jr|j|b[a-z0-9]*)\s')
_STORE = re.compile(r'\b(?:sw|swc1)\s+\$\w+\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)')
_LITERAL = re.compile(r'-?(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)[fFuUlL]*')


def stored_offsets(asm):
    """{callee: [the stack offsets each of its calls stores]} from the block of each `jal` and its delay slot."""
    lines = [line for line in asm.splitlines() if line.strip() and not line.rstrip().endswith(':')]
    found = {}
    for index, line in enumerate(lines):
        call = _CALL.search(line)
        if not call:
            continue
        block = lines[index + 1:index + 2]
        for earlier in reversed(lines[:index]):
            if _BRANCH.search(earlier):
                break
            block.append(earlier)
        offsets = {int(hit[1], 0) for hit in map(_STORE.search, block) if hit}
        found.setdefault(call[1], []).append(offsets)
    return found


def _closing(clean, opening):
    depth = 0
    for at in range(opening, len(clean)):
        depth += (clean[at] in '([{') - (clean[at] in ')]}')
        if not depth:
            return at
    return None


def variants(source, name, asm):
    part = view(source, name)
    if not part or not asm:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    base = part.opening
    edits, used, widened, consumed = [], {}, {}, set()
    for callee, calls in stored_offsets(asm).items():
        for call in re.finditer(rf'(?<![\w.>]){callee}\s*\(', body):
            opening = base + call.end() - 1
            closing = _closing(clean, opening)
            if closing is None:
                continue
            text = source[opening + 1:closing]
            arguments = [text[a:b].strip() for a, b in split_args(clean[opening + 1:closing])]
            count = len(arguments)
            if count < 4:
                continue
            # the statements directly before the call, back to a brace
            block = max(clean.rfind('{', 0, opening), clean.rfind('}', 0, opening)) + 1
            values, at = [], count
            while True:
                local = f'sp{at * 4:X}'
                if not any(at * 4 in offsets for offsets in calls):
                    break
                assigned = list(re.finditer(rf'(?<![\w.>]){local}\s*=(?!=)\s*([^;]+);[ \t]*\n?', clean[block:opening]))
                if not assigned:
                    break
                last = assigned[-1]
                start, stop = block + last.start(), block + last.end()
                value = source[block + last.start(1):block + last.end(1)].strip()
                line = clean.rfind('\n', 0, start) + 1
                if not clean[line:start].strip():
                    start = line
                values.append((local, value, start, stop))
                at += 1
            if not values:
                continue
            added = ''.join(f', {value}' for _, value, _, _ in values)
            replaced = list(arguments)
            for local, value, start, stop in values:
                if (start, stop) in consumed:
                    return []
                consumed.add((start, stop))
                edits.append((start, stop, ''))
                used[local] = used.get(local, 0) + 1
                for index, argument in enumerate(arguments):
                    if argument == local and _LITERAL.fullmatch(value):
                        replaced[index] = value
                        used[local] += 1
            if replaced != arguments:
                edits.append((opening + 1, closing, ', '.join(replaced) + added))
            else:
                edits.append((closing, closing, added))
            widened.setdefault(callee, (count, [local for local, _, _, _ in values]))
    if not edits:
        return []
    types = {}
    for local, times in used.items():
        declared = re.search(rf'(?m)^[ \t]*([A-Za-z_]\w*)[ \t]+{local}[ \t]*;[ \t]*\n', body)
        if not declared or len(re.findall(rf'(?<![\w.>]){local}\b', body)) != times + 1:
            return []
        types[local] = declared[1]
        edits.append((base + declared.start(), base + declared.end(), ''))
    for callee, (count, locals_) in widened.items():
        for prototype in re.finditer(rf'(?m)^[ \t]*(?:extern[ \t]+)?[A-Za-z_][\w \t*]*?\b{callee}[ \t]*\(([^()]*)\)[ \t]*;',
                                     clean[:part.opening]):
            if len(split_args(prototype[1])) == count:
                edits.append((prototype.end(1), prototype.end(1), ''.join(f', {types[local]}' for local in locals_)))
    return [(FAMILY, edit(source, edits))]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
