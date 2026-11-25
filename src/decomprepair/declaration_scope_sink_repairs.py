"""A local declared at the top of the function, moved into the one block that uses it.

gcc 2.7.2 numbers pseudo registers in the order it expands declarations: a function-level declaration gets its pseudo
when the function starts, a block-level one when the block is entered. Reload then hands out the stack slots of the
spilled pseudos in pseudo-number order (docs/COMPILER_MATCHING_LEARNINGS.md: "spill slots are numbered by pseudo
number"), and each spilled pseudo takes eight bytes. So where a local is declared decides which pseudos sit before it,
and with them the stack offset of its slot. m2c declares every temporary at the top of the function; the game's source
declared many of them in the block that uses them.

A 374-instruction N64 effect spawner (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) differed from its target in one
thing at the end: a spilled halfword (a string length kept across calls) was at `0x146($sp)` where the target had it
at `0x14e($sp)`, eight bytes later, and no source order of the top-level declarations moved it (the score stayed 2).
Declaring that local at the start of the `if (obj != NULL) { ... }` block, the only block that touches it, gave 0.
Hypothesis, not confirmed in the compiler source: another local declared at the function level (a sign-extended copy of
a byte parameter, which cse folds away but which still counted one reference) took the slot ahead of it, and declaring
the length later in the numbering put its slot after that one.

`array_declaration_scope_sink` is the same move for the locals that keep a stack slot of their own. Hypothesis, from
one 842-instruction lit-actor drawer (same compiler and flags) and not confirmed in the compiler source: an array (or a
`volatile` scratch) takes its frame slot when its declaration is expanded, while a scalar whose address is taken
(`&sp20`) takes one when the first `&` is expanded, which is later in the code than the function's opening. So an array
declared at the top of the function sat *below* fifteen addressed byte locals, the target had it *above* them (the
byte locals at `0x20(sp)`, the vector at `0x30(sp)`, this build at `0x38` and `0x28`), and declaring it at the start of
the one `switch` body that uses it moved it after them. The same function reserves eight bytes more than its locals
use, which the agents had declared as a `volatile u64` at the top of the function; there it pushes every addressed local
up by eight, so the family also offers the array and that unused scratch moved together (the scratch right after the
array). No score is claimed beyond the frame: the offsets of the fifteen byte locals and the vector matched, the
function stayed at 10,000 for other reasons.

`declaration_scope_sink` offers, for a scalar or pointer local declared without an initializer at the top of the
function whose every reference lies inside one inner block (not a loop body, which would change what survives an
iteration), the same function with the declaration moved to the first line of that block. Locals with a narrow type
come first (the m2c stack temporaries `spXX` that are spilled), then the other scalars and pointers, then struct
locals (a `Vec3`), so a function with a dozen struct temporaries still gets its scalars within LIMIT. The judge decides.

A 920-instruction N64 segment-against-triangles test (SN GCC 2.8.1, `-G0 -mips3 -O2 -mfp32`) differed only in one
float's spill slot: `sign` at `0x15c($sp)` where the target had `0x168($sp)`, after the hoisted address of a vertex
array and an 8-byte double. Reload gives the pseudos that got no hard register their slots in pseudo-number order
(reload1.c, the `alter_reg (i, -1)` loop), and `sign`, declared with the function's locals, had a lower number than
both. Declaring it at the start of the `else` block that computes and reads it gave 0 (7 -> 0). The family had that
child, but twelve `Vec3` locals and the loop body's locals (the `for` head check never matched) used up its eight.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'declaration_scope_sink'
ARRAY_FAMILY = 'array_declaration_scope_sink'
FAMILIES = (FAMILY, ARRAY_FAMILY)
LIMIT = 8
NARROW = re.compile(r'\b(?:u8|s8|u16|s16|char|short)\b')
DECLARATION = re.compile(rf'\s*(?P<type>(?:(?:unsigned|signed|const|register)\s+)*{IDENT}(?:\s+{IDENT})?[\s*]*?)\b(?P<name>{IDENT})\s*;')
CONTROL = re.compile(r'\b(?:return|goto|break|continue|case|default|else|typedef|extern|static)\b')
KEYWORDS = {'return', 'case', 'else', 'goto', 'sizeof', 'do'}
# A loop or switch head right before a block's `{`: its parentheses may nest two deep and a `for` head holds `;`
# (`[^{};]` never matched a `for`, so a loop body's locals were offered and filled LIMIT ahead of the real candidates).
HEAD_ARGS = r'\((?:[^(){}]|\((?:[^(){}]|\([^(){}]*\))*\))*\)'
LOOP = re.compile(rf'\b(?:for|while|switch)\s*{HEAD_ARGS}\s*$|\bdo\s*$')
# Types that are one register wide; anything else declared without `*` is taken to be a struct typedef (a `Vec3`).
SCALAR = re.compile(r'\*|^\s*(?:(?:unsigned|signed|const|register)\s+)*(?:u8|s8|u16|s16|u32|s32|u64|s64|f32|f64|int|char|short|long|float|double|unsigned|signed)\b')


def _python_blocks(clean, opening, end):
    """(open, close) of every `{ }` pair inside the function body, outermost first."""
    stack, found = [], []
    for index in range(opening, end):
        if clean[index] == '{':
            stack.append(index)
        elif clean[index] == '}' and stack:
            found.append((stack.pop(), index))
    return sorted(found)


_blocks = _python_blocks
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _blocks(clean, opening, end):
        found = _scan.block_pairs(clean, opening, end)
        if found is not NotImplemented:
            return sorted(found)
        return _python_blocks(clean, opening, end)


def _innermost(blocks, positions):
    """The smallest block holding every position, or None."""
    holders = [block for block in blocks if all(block[0] < p < block[1] for p in positions)]
    return min(holders, key=lambda block: block[1] - block[0]) if holders else None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    blocks = _blocks(clean, part.opening, part.end)
    top = [block for block in blocks if block[0] == part.opening]
    if not top:
        return []
    body_start, body_end = part.opening + 1, top[0][1]
    # scalar and pointer declarations of the function's own block, wherever its leading declarations end
    declared = []
    for match in DECLARATION.finditer(clean, body_start, body_end):
        depth = clean.count('{', body_start, match.start()) - clean.count('}', body_start, match.start())
        if depth == 0 and not CONTROL.search(match['type']):
            declared.append(match)
    result = []
    for match in declared:
        local = match['name']
        references = [hit.start() for hit in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', clean[body_start:body_end])]
        references = [body_start + offset for offset in references if not match.start() <= body_start + offset < match.end()]
        if not references or re.search(rf'&\s*{re.escape(local)}\b', clean[body_start:body_end]):
            continue
        # the same name declared again inside a block would be a different object
        redeclared = [hit for hit in re.finditer(rf'\b({IDENT})[\s*]+{re.escape(local)}\s*[;,\[=](?!=)', clean[body_start:body_end])
                      if hit[1] not in KEYWORDS]
        if len(redeclared) != 1:
            continue
        holder = _innermost([block for block in blocks if block[0] > part.opening], references)
        if not holder:
            continue
        if LOOP.search(clean[max(0, holder[0] - 120):holder[0]].rstrip()[-120:]):
            continue
        line = source[match.start():match.end()]
        indent = re.search(r'[ \t]*$', line[:len(line) - len(line.lstrip())])[0]
        insert_at = holder[0] + 1
        text = f'\n{indent}  {line.strip()}'
        rank = 0 if NARROW.search(match['type']) else 1 if SCALAR.search(match['type']) else 2
        result.append((rank, len(result), source_edit(source, match, insert_at, text)))
    result.sort(key=lambda item: item[:2])
    return array_variants(source, name) + [(FAMILY, text) for _, _, text in result[:LIMIT]]


ARRAY = re.compile(rf'(?P<type>(?:(?:unsigned|signed|const|register|volatile)\s+)*{IDENT}(?:\s+{IDENT})?[\s*]*?)\b(?P<name>{IDENT})\s*(?P<dims>(?:\[[^\]\n]*\])+)\s*;')
SCRATCH = re.compile(rf'(?P<type>volatile\s+(?:{IDENT}\s+)*{IDENT}[\s*]*?)\b(?P<name>{IDENT})\s*;')
BLOCK_HEAD = re.compile(rf'\b(?:for|while)\s*{HEAD_ARGS}\s*$|\bdo\s*$')


def array_variants(source, name):
    """Arrays declared at the top of the function that only one block uses, declared at the start of that block.

    The holder may be a `switch` body (a declaration before its first label is legal C and expands when the body
    opens). An unused `volatile` scratch is offered moved along with the array, right after it, because the scratch
    only reserves frame bytes and the array's slot must come before it."""
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    blocks = _blocks(clean, part.opening, part.end)
    top = [block for block in blocks if block[0] == part.opening]
    if not top:
        return []
    body_start, body_end = part.opening + 1, top[0][1]

    def depth0(pattern):
        found = []
        for match in pattern.finditer(clean, body_start, body_end):
            depth = clean.count('{', body_start, match.start()) - clean.count('}', body_start, match.start())
            if depth == 0 and not CONTROL.search(match['type']) and match['type'].strip().split()[-1] not in KEYWORDS:
                found.append(match)
        return found

    scratches = [match for match in depth0(SCRATCH)
                 if not [hit for hit in re.finditer(rf'(?<![\w.>]){re.escape(match['name'])}\b', clean[body_start:body_end])
                         if not match.start() <= body_start + hit.start() < match.end()]]
    result = []
    for match in depth0(ARRAY):
        local = match['name']
        references = [body_start + hit.start() for hit in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', clean[body_start:body_end])]
        references = [offset for offset in references if not match.start() <= offset < match.end()]
        redeclared = [hit for hit in re.finditer(rf'\b({IDENT})[\s*]+{re.escape(local)}\s*[;,\[=](?!=)', clean[body_start:body_end])
                      if hit[1] not in KEYWORDS]
        if not references or len(redeclared) != 1:
            continue
        holder = _innermost([block for block in blocks if block[0] > part.opening], references)
        if not holder or BLOCK_HEAD.search(clean[max(0, holder[0] - 120):holder[0]].rstrip()[-120:]):
            continue
        line = source[match.start():match.end()]
        indent = re.search(r'[ \t]*$', source[:match.start()].rsplit('\n', 1)[-1])[0]
        insert_at = holder[0] + 1
        alone = source_edit(source, match, insert_at, f'\n{indent}  {line.strip()}')
        result.append(alone)
        for scratch in scratches:
            both = edit(source, [(match.start(), match.end(), ''), (scratch.start(), scratch.end(), ''),
                                 (insert_at, insert_at, f'\n{indent}  {line.strip()}\n{indent}  {source[scratch.start():scratch.end()].strip()}')])
            result.append(both)
    return [(ARRAY_FAMILY, text) for text in result[:LIMIT]]


def source_edit(source, match, insert_at, text):
    return edit(source, [(match.start(), match.end(), ''), (insert_at, insert_at, text)])
