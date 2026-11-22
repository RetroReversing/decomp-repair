"""The statements that open a function wrapped in a `do { } while (0)`, so the first scheduler keeps the spills in order.

GCC 2.7.2's first scheduler (before register allocation) treats the loop notes a `do { } while (0)` leaves behind as
barriers and nothing else of it survives. At the head of a function the parameter copies (`p = $a0`, `p = $a2`, ...)
are scheduled with the first statements: with the copies' consumers' chains of different lengths it moved one copy down
to its first use, so the stores that spill the parameters came out as `sw a0; sw a3; ...; sw a2` where the target of an
851-instruction N64 ray test (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) has them first, in parameter order, and
the loads of the narrow stack parameter, the float copy and the multiplies behind them in another order. The
original's first statements sat in such a block: the run of nine straight-line statements ahead of the function's first
`if` wrapped in one gave 565 -> 250 and every parameter store in place, with nothing else moved. A narrow stack parameter
(a `u8` flag) read from a local that the run assigns after its first statement, the local declared ahead of the others
(its spill slot follows the parameters', in declaration order), put its load after the barrier too, as the target has it:
250 -> 155 (the copy first in the run: 459 on the first try). The explanation is read from the compiler's output with and
without `-fno-schedule-insns` (the stores come first, in order, without the first scheduler), a hypothesis, not confirmed
in the compiler's source.

`entry_scheduling_scope` offers, for a function whose body opens, after its declarations, with a run of at least three
plain assignments (no call, branch, label or declaration among them), the function with that run wrapped in
`do { ... } while (0);`, and children that also read each narrow stack parameter the function uses later through a new
local assigned first in the run, or after its first statement. The judge decides.
"""
import re

from .declaration_scope_sink_repairs import DECLARATION
from .integer_repair_support import IDENT, edit, view
from .line_scan import lines

FAMILY = 'entry_scheduling_scope'
FAMILIES = (FAMILY,)
MIN_RUN = 3
NARROW = re.compile(rf'\b(?P<type>u8|s8|u16|s16|char|short|unsigned char|unsigned short)\s+(?P<name>{IDENT})\s*$')
CALL = re.compile(r'\b(?!M2C_FIELD\b|sizeof\b)[A-Za-z_]\w*\s*\(')
ASSIGNMENT = re.compile(r'^[^;{}=!<>]*[\w\]\)]\s*=(?!=)[^;{}]*;\s*$')
COMPOUND = re.compile(r'^\s*(?:if|else|for|while|do|switch|case|default|return|goto|break|continue|asm|__asm__)\b|^\s*\w+\s*:(?!:)|[{}]')


def _parameters(clean, part, name):
    opening = clean.find('(', clean.rfind(name, 0, part.opening))
    depth, start, found = 0, opening + 1, []
    for index in range(opening, part.opening):
        char = clean[index]
        depth += char == '('
        depth -= char == ')'
        if (char == ',' and depth == 1) or (char == ')' and depth == 0):
            found.append(clean[start:index].strip())
            start = index + 1
            if depth == 0:
                break
    return found


def _run(body):
    """(index of the first statement line, the run of plain assignment lines from it): the declarations come first,
    a record declared with braces counting as one of them."""
    depth = 0
    for index, line in enumerate(body):
        text = line.stripped
        opened = depth
        depth += text.count('{') - text.count('}')
        if opened or depth or not text:
            continue
        if ASSIGNMENT.match(text) and not CALL.search(text) and not DECLARATION.fullmatch(' ' + text):
            run = []
            for later in body[index:]:
                if not ASSIGNMENT.match(later.stripped) or CALL.search(later.stripped):
                    break
                run.append(later)
            return index, run
        if COMPOUND.search(text):
            return None, []
    return None, []


STAGED = re.compile(rf'\(\s*\*\s*(?P<ptr>{IDENT})\s*\*\s*(?P<copy>{IDENT})\s*\)|\(\s*(?P<copy2>{IDENT})\s*\*\s*\*\s*(?P<ptr2>{IDENT})\s*\)')


def _first_load(run, clean, part):
    """(index of the statement, pointer, its scalar type) of the first product of a dereference and a value the run copied
    from a parameter earlier, else None."""
    copies = {}
    for index, line in enumerate(run):
        text = line.stripped
        plain = re.fullmatch(rf'({IDENT})\s*=\s*({IDENT})\s*;', text)
        if plain:
            copies[plain[1]] = plain[2]
            continue
        for hit in STAGED.finditer(text):
            copy = hit['copy'] or hit['copy2']
            if copy in copies:
                kind = re.search(rf'\b(f32|float|f64|double)\s+{re.escape(copy)}\s*;', clean[part.opening:part.end])
                if kind:
                    return index, hit['ptr'] or hit['ptr2'], kind[1]
    return None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b|^\s*#', part.body, re.M) or 'while (0)' in part.body:
        return []
    clean = part.clean
    body = lines(part, source)
    first, run = _run(body)
    if first is None or len(run) < MIN_RUN:
        return []
    start, end, indent = run[0].start, run[-1].end, run[0].indent
    texts = [f'{line.source}\n' for line in run]
    found = [(FAMILY, edit(source, [(start, end, f'{indent}do {{\n{"".join(texts)}{indent}}} while (0);\n')]))]
    staged = _first_load(run, clean, part)
    texts_staged = None
    if staged:
        # the first product's dereference read into a local as the run's first statement, so the run's first insn is that
        # load and the value copied from a parameter comes after it (250 -> the mov.s after the lwc1 as the target has it)
        number, pointer, kind = staged
        local = f'staged_{pointer}'
        decl = next((m for m in DECLARATION.finditer(clean, part.opening + 1, part.end)), None)
        at = source.rfind('\n', 0, decl.start('type')) + 1 if decl else source.find('\n', part.opening) + 1
        changed = run[number].source
        for pattern in (rf'\(\s*\*\s*{pointer}\s*\*', rf'\*\s*{pointer}\s*\)'):
            changed = re.sub(pattern, lambda m: m[0].replace(f'*{pointer}', local).replace(f'* {pointer}', local), changed, count=1)
        texts_staged = [f'{indent}    {local} = *{pointer};\n'] + [f'{line.source}\n' if i != number else f'{changed}\n' for i, line in enumerate(run)]
        at2, decl2 = at, f'    {kind} {local};\n'
        found.append((FAMILY, edit(source, [(start, end, f'{indent}do {{\n{"".join(texts_staged)}{indent}}} while (0);\n'), (at2, at2, decl2)])))
    # a narrow stack parameter (the fifth or later) the function reads after the run, read through a new local
    narrow = []
    for number, text in enumerate(_parameters(clean, part, name)):
        hit = NARROW.search(text)
        if hit and number >= 4 and re.search(rf'(?<![\w.>]){re.escape(hit["name"])}\b', clean[end:part.end]):
            narrow.append(hit)
    if narrow:
        names = {hit['name']: f'copy_{hit["name"]}' for hit in narrow}
        copies = [f'{indent}    {names[hit["name"]]} = {hit["name"]};\n' for hit in narrow]
        later = [(end + hit.start(), end + hit.end(), names[hit[1]])
                 for hit in re.finditer(rf'(?<![\w.>])({"|".join(map(re.escape, names))})\b', clean[end:part.end])]
        decl = next((match for match in DECLARATION.finditer(clean, part.opening + 1, part.end)
                     if clean.count('{', part.opening + 1, match.start()) == clean.count('}', part.opening + 1, match.start())), None)
        at = source.rfind('\n', 0, decl.start('type')) + 1 if decl else source.find('\n', part.opening) + 1
        declared = ''.join(f'    {hit["type"]} {names[hit["name"]]};\n' for hit in narrow)
        # the copies first in the run, or after its first statement: the score depends on where (459 against 225 here)
        for base, places in ((texts, (0, 1)), (texts_staged, (1, 2))):
            if base is None:
                continue
            for place in places:
                wrapped = ''.join(base[:place]) + ''.join(copies) + ''.join(base[place:])
                found.append((FAMILY, edit(source, [(start, end, f'{indent}do {{\n{wrapped}{indent}}} while (0);\n'), *later, (at, at, declared)] + ([(at2, at2, decl2)] if base is texts_staged else []))))
    return found
