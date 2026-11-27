"""A leading (or middle) parameter m2c left out because nothing reads it, put back, and passed on to the first callee.

m2c names a parameter after the register or stack slot it arrives in and leaves out the ones nothing reads, so a draft
whose function never reads `$a0` begins `f(void *arg1, s32 *arg2, ..)`. Compiled, `arg1` arrives in `$a0`: every
register copy at entry is one off and the stack parameters sit a word early. The numbering says which are missing. The
game's function often reads nothing from the skipped register because it only hands it on: `f` calls a helper first,
which receives `$a0` (and `$a1`, ..) untouched, and m2c drafts the call as `g()`.

    s32 f(void *arg1, s32 *arg2) { g(); ... }      ->      s32 f(s32 arg0, void *arg1, s32 *arg2) { g(arg0, arg1); ... }

Measured on one N64 function (SN GCC 2.8.1 `-G0 -mips3 -O2`, 59 instructions): the parameter alone moved the machine
draft from 1054 to 834; with the call's arguments and `later_arm_tail_else` after it the exact judge went on to 0.
Passing the arguments without the parameter does not compile, and passing one argument fewer or more than the callee
reads scored 420 and 180 where the right count was 0, so every count the target allows is offered.

Needs: every parameter of the definition an `argN` of integer or pointer type, with a number below the highest one's
(and below 4) missing. The first child only adds the missing parameters as `s32`. With the target's assembly (MIPS), more
children also pass `arg0`..`arg(K-1)` to the first call written without arguments of a callee that has no prototype with
parameters, for each K up to the argument registers that still hold the caller's own values at its `jal`s."""
import re

from .argument_passthrough_to_callees import _prototyped, incoming_sites
from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'skipped_register_parameter'
FAMILIES = (FAMILY,)
_PARAMETER = re.compile(r'\s*(?:(?:const|volatile|struct|union|unsigned|signed)\s+)*[A-Za-z_]\w*[\s*]+arg(\d{1,2})\s*')
_FLOATING = re.compile(r'\b(?:float|double|f32|f64)\b')
_KEYWORDS = ('if', 'while', 'for', 'switch', 'return', 'sizeof', 'do')


def _signature(part, name):
    """(start, end, [parameter text], [index]) of the definition's parameter list when every one is an integer or
    pointer `argN` in ascending order, else None."""
    head = part.clean[:part.opening]
    found = None
    for found in re.finditer(rf'\b{re.escape(name)}\s*\(', head):
        pass
    if not found:
        return None
    end = head.rfind(')')
    if end < found.end():
        return None
    pieces, indices = [], []
    for piece in part.source[found.end():end].split(','):
        match = _PARAMETER.fullmatch(piece)
        if not match or ('*' not in piece and _FLOATING.search(piece)):
            return None
        pieces.append(' '.join(piece.split()))
        indices.append(int(match[1]))
    if indices != sorted(set(indices)):
        return None
    return found.end(), end, pieces, indices


def variants(source, name, header='', asm=None, arch=None):
    """Proposals: the skipped parameters declared, then also passed on to the first argument-less call."""
    part = view(source, name)
    if not part or arch not in (None, 'mips'):
        return []
    signature = _signature(part, name)
    if not signature:
        return []
    start, end, pieces, indices = signature
    missing = [index for index in range(min(4, indices[-1])) if index not in indices]
    if not missing or any(re.search(rf'\barg{index}\b', part.clean) for index in missing):
        return []
    declared = dict(zip(indices, pieces))
    declared.update({index: f's32 arg{index}' for index in missing})
    parameters = (start, end, ', '.join(declared[index] for index in sorted(declared)))
    out = [edit(source, [parameters])]
    if asm:
        outside = _blank(header or '') + '\n' + part.clean[:part.opening] + part.clean[part.end:]
        sites = incoming_sites(asm)
        for hit in re.finditer(rf'(?<![\w.>])({IDENT})\s*\(', part.clean[:part.end]):
            callee, opening = hit[1], hit.end() - 1
            if opening < part.opening or callee in _KEYWORDS:
                continue
            closing = close(part.clean, opening, '(', ')')
            if (not closing or part.clean[opening + 1:closing - 1].strip() or callee not in sites
                    or _prototyped(callee, outside)):
                continue
            for count in range(1, 5):
                if count - 1 not in declared or not all(count - 1 in found for found in sites[callee]):
                    break
                names = ', '.join(f'arg{index}' for index in range(count))
                out.append(edit(source, [parameters, (opening + 1, closing - 1, names)]))
            break
    return [(FAMILY, text) for text in out]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm', 'arch'),
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
