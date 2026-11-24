"""A copy followed by a compare of its source: the copy in a `do { } while (0)`, the compare as a flag before the branch.

The shape (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`; a 1133-instruction N64 effect spawner's fade-in clamp,
35 -> 0): `a = v; ...; if (v >= 0x100) a = 0xFF;`, with `v` still read by the compare after the copy. The target
compares the original (`slti $a0,$a0,0x100` with `v` in `$a0` and the copy `move $a1,$a0` kept); every plain spelling
compares the copy (`slti $v0,$a1,0x100`). Two compiler rules decide it, both read in the compiler's source:

- local-alloc.c `optimize_reg_copy_1`: for a register copy `dest = src` whose source dies later in the same block, it
  rewrites the reads of `src` between the copy and that death into reads of `dest`. Its forward scan stops at a
  CODE_LABEL, a JUMP_INSN or a NOTE_INSN_LOOP_BEG/LOOP_END note, and `do { dest = src; } while (0);` leaves exactly
  such notes around the copy, so the compare keeps reading `src`.
- local-alloc gives block-local quantities their registers before global.c sees the rest: the compare's result takes
  the first register no other local holds across it. Computed into a flag *before* the last statements of the block
  (the target's `and` of a clamp below zero), the values those statements still need are live across the compare and
  it lands where the target has it. That position is a search, so each statement boundary between the copy and the
  `if` is a child (the measured one was the boundary before the block's last statement).

Each is worse alone on the measured function (the fence alone 5, the flag alone 275), so the family offers the fence
alone and the fence with each flag position as single children. `v` and `a` are plain identifiers, the bound is an
integer literal, and the statements between are straight-line (no braces, no labels, no other write to `v` or `a`).
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'copy_compare_fence'
FAMILIES = (FAMILY,)
LIMIT = 12
WINDOW = 400

COPY = re.compile(r'(?m)^([ \t]*)([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*;')
INVERSE = {'>=': '<', '>': '<=', '<': '>=', '<=': '>', '==': '!=', '!=': '=='}


def _flag_name(body):
    name, index = 'cmpFlag', 1
    while re.search(rf'\b{name}\b', body):
        index += 1
        name = f'cmpFlag{index}'
    return name


def _boundaries(text):
    """Offsets in `text` just after each top-level `;` (statement ends), followed by spaces."""
    depth, ends = 0, []
    for index, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if char == ';' and depth == 0:
            end = index + 1
            while end < len(text) and text[end] in ' \t':
                end += 1
            ends.append(end)
    return ends


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    clean, base = part.clean, part.opening + 1
    body = clean[base:part.end]
    declaration = re.search(r'(?m)^([ \t]*)(?:(?:unsigned|signed|const|register|static)\s+)*[A-Za-z_]\w*[\s*]+[A-Za-z_]\w*\s*(?:\[[^\]]*\]\s*)?;[ \t]*\n', body)
    if not declaration:
        return []
    flag = _flag_name(clean)
    found = []
    for copy in COPY.finditer(clean, base, part.end):
        dest, src = copy[2], copy[3]
        if dest == src or re.search(r'\bdo\s*{\s*$', clean[max(base, copy.start() - 8):copy.start()]):
            continue
        branch = re.compile(rf'\bif\s*\(\s*{re.escape(src)}\s*(>=|<=|==|!=|<|>)\s*(-?(?:0[xX][0-9a-fA-F]+|\d+)[uU]?)\s*\)')
        hit = branch.search(clean, copy.end(), min(part.end, copy.end() + WINDOW))
        if not hit:
            continue
        between = clean[copy.end():hit.start()]
        if (re.search(r'[{}]|\b(?:if|else|for|while|do|switch|case|goto|return)\b|^\s*\w+\s*:', between, re.M)
                or re.search(rf'(?<![\w.>]){re.escape(dest)}\b', between)
                or re.search(rf'(?<![\w.>]){re.escape(src)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(src)}\b|\b{re.escape(src)}\s*(?:\+\+|--)', between)
                or re.search(r'\b[A-Za-z_]\w*\s*\(', between)):
            continue
        fenced = (copy.start(2), copy.end(), f'do {{ {dest} = {src}; }} while (0);')
        found.append((FAMILY, edit(source, [fenced])))
        op, bound = hit[1], hit[2]
        cond = (hit.start(), hit.end())
        decl_at = base + declaration.end()
        indent = declaration[1]
        for offset in [0] + _boundaries(between):
            at = copy.end() + offset
            for test, use in ((f'{src} {INVERSE[op]} {bound}', f'if (!{flag})'), (f'{src} {op} {bound}', f'if ({flag})')):
                edits = [(decl_at, decl_at, f'{indent}s32 {flag};\n'), fenced, (at, at, f'{flag} = {test}; '),
                         (cond[0], cond[1], use)]
                found.append((FAMILY, edit(source, edits)))
        if len(found) >= LIMIT:
            break
    unique = []
    for child in found:
        if child not in unique:
            unique.append(child)
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 600}  # the registry: no caller wiring (registry.py)
