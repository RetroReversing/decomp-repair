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

`declaration_scope_sink` offers, for a scalar or pointer local declared without an initializer at the top of the
function whose every reference lies inside one inner block (not a loop body, which would change what survives an
iteration), the same function with the declaration moved to the first line of that block. Locals with a narrow type
come first (the m2c stack temporaries `spXX` that are spilled). The judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'declaration_scope_sink'
FAMILIES = (FAMILY,)
LIMIT = 8
NARROW = re.compile(r'\b(?:u8|s8|u16|s16|char|short)\b')
DECLARATION = re.compile(rf'\s*(?P<type>(?:(?:unsigned|signed|const|register)\s+)*{IDENT}(?:\s+{IDENT})?[\s*]*?)\b(?P<name>{IDENT})\s*;')
CONTROL = re.compile(r'\b(?:return|goto|break|continue|case|default|else|typedef|extern|static)\b')
KEYWORDS = {'return', 'case', 'else', 'goto', 'sizeof', 'do'}
LOOP = re.compile(r'\b(?:for|while)\s*\([^{};]*\)\s*$|\bdo\s*$|\bswitch\s*\([^{};]*\)\s*$')


def _blocks(clean, opening, end):
    """(open, close) of every `{ }` pair inside the function body, outermost first."""
    stack, found = [], []
    for index in range(opening, end):
        if clean[index] == '{':
            stack.append(index)
        elif clean[index] == '}' and stack:
            found.append((stack.pop(), index))
    return sorted(found)


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
        rank = 0 if NARROW.search(match['type']) else 1
        result.append((rank, len(result), source_edit(source, match, insert_at, text)))
    result.sort(key=lambda item: item[:2])
    return [(FAMILY, text) for _, _, text in result[:LIMIT]]


def source_edit(source, match, insert_at, text):
    return edit(source, [(match.start(), match.end(), ''), (insert_at, insert_at, text)])
