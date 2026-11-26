"""Every parameter the loops read copied into a local at the top, all of them at once, with narrow ones widened.

gcc 2.7.2 copies each parameter register into a pseudo at the function's entry, in parameter order, and loads a stack
parameter it keeps in a register in the same run. A game that wrote `startX = x; step = dx; alpha = arg6;` has those
copies as statements of its own, after the run: the stack load comes first, the moves after it, and a byte argument is
read as `lbu` of the word's low byte with its `andi` before the loop. `entry_parameter_copy` copies one parameter, and
here any one or two of them leaves the score where it was or worse; the combination is what moves it.

The case (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`, N64): a 134-instruction string drawing routine with a
wrapping loop and a call with eleven arguments was at 65 with the parameters used directly, at 65 or 220 with any one
of the three copied or any pair, and at 5 with all three (the last 5 were `accumulate_separate_dest`'s). Which pass
orders the parameter loads is not read from the compiler's source.

Children: the register parameters (the first four) that a loop reads, copied (`T NAME_in` in the signature, `NAME =
NAME_in;` at the top); those plus the `u8`/`s16`-style parameters a loop reads, taken as `s32 NAME_in` and copied into
a local of the narrow type. A parameter whose address is taken is left alone. A candidate for the exact judge, never a
verdict.
"""
import re

from .integer_repair_support import IDENT, _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'loop_params_entry_copy'
FAMILIES = (FAMILY,)
NARROW = r'(?:u8|s8|u16|s16|char|short|(?:unsigned|signed)\s+(?:char|short))'
TYPE = r'(?:(?:unsigned|signed|const|struct)\s+)*[A-Za-z_]\w*(?:\s*\*+)?'


def _parameters(part):
    """(offset, length, name, type) of each parameter, or nothing for a list this does not read."""
    signature = re.search(r'\(([^()]*)\)\s*$', part.clean[:part.opening])
    if not signature or signature[1].strip() in ('', 'void'):
        return []
    found, position = [], signature.start(1)
    for piece in signature[1].split(','):
        match = re.fullmatch(rf'(\s*)({TYPE})\s*(?<=[\s*])({IDENT})(\s*)', piece)
        if not match:
            return []
        found.append((position + len(match[1]), len(piece) - len(match[1]) - len(match[4]), match[3], match[2].strip()))
        position += len(piece) + 1
    return found


def _loops(clean, opening, end):
    """The text of every loop in the body: its header and its statement."""
    spans = []
    for loop in re.finditer(r'\b(for|while|do)\b', clean[opening:end]):
        at = opening + loop.end()
        if loop[1] != 'do':
            at = clean.find('(', at, end)
            at = close(clean, at) if at >= 0 else None
            if at is None:
                continue
        rest = clean[at:end]
        stripped = len(rest) - len(rest.lstrip())
        if rest.lstrip().startswith('{'):
            stop = close(clean, at + stripped, '{', '}')
        else:
            stop = clean.find(';', at, end) + 1
        if stop:
            spans.append(clean[opening + loop.start():stop])
    return '\n'.join(spans)


def _after_declarations(clean, cursor, end):
    while True:
        match = re.match(rf'\s*(?!return\b|goto\b){TYPE}\s*(?<=[\s*]){IDENT}\s*(?:\[[^\];]*\])?\s*;', clean[cursor:end])
        if not match:
            return cursor
        cursor += match.end()


def _child(source, part, chosen):
    top = _after_declarations(part.clean, part.opening + 1, part.end)
    edits, declarations, copies = [], [], []
    for offset, length, name, kind, narrow in chosen:
        edits.append((offset, offset + length, f'{"s32" if narrow else kind} {name}_in'))
        declarations.append(f'\n    {kind} {name};')
        copies.append(f'\n    {name} = {name}_in;')
    # reads in the declarations' initialisers would see an unfilled local: decline those
    if any(re.search(rf'(?<![\w.>]){c[2]}\b', part.clean[part.opening + 1:top]) for c in chosen):
        return None
    if top == part.opening + 1:
        edits.append((top, top, ''.join(declarations + copies)))
    else:
        edits.append((part.opening + 1, part.opening + 1, ''.join(declarations)))
        edits.append((top, top, ''.join(copies)))
    return edit(source, edits)


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b', part.body):
        return []
    loops = _loops(part.clean, part.opening, part.end)
    words, narrows = [], []
    for index, (offset, length, param, kind) in enumerate(_parameters(part)):
        if (not re.search(rf'(?<![\w.>]){param}\b', loops) or _address_taken(part.body, param)
                or re.search(rf'\b{param}_in\b', part.clean)):
            continue
        if re.fullmatch(NARROW, kind):
            narrows.append((offset, length, param, kind, True))
        elif index < 4:
            words.append((offset, length, param, kind, False))
    result = []
    for chosen in (words, words + narrows if narrows else []):
        # one parameter alone is `entry_parameter_copy`'s child
        if len(chosen) > 1:
            text = _child(source, part, sorted(chosen))
            if text and text != source and text not in result:
                result.append(text)
    return [(FAMILY, text) for text in result]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 72}  # the registry: no caller wiring (registry.py)
