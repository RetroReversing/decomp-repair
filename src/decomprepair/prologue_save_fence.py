"""An empty `do { } while (0);` as the function's first statement, for a target whose prologue saves stay together.

SN64 GCC 2.8.1 (`-G0 -mips3 -O2`, N64) schedules the body's first instructions in among the register saves:

    sw $s4; move $s4,$zero; lui $v0; sw $s6; addiu $s6; li $v0,-1; sw $ra; sw $fp; ...

A target that stores `$ra`, `$fp` and every saved register in one unbroken run, and only then starts the body, had
something at the head that the scheduler does not move instructions across. The notes an empty `do { } while (0);`
leaves are such a boundary: on a 115-instruction high-score insertion routine it took the exact judge from 840 to 0
with nothing else changed (the same line elsewhere in the head, around the first stores, stopped at 180). It may be
what an empty debug macro left behind; that, and the scheduler as the reason, are hypotheses read from the compiler's
output, not from its source.

`prologue_save_fence` offers one child: the empty loop after the leading declarations. Only when the target's assembly
opens with the stack adjustment followed by at least `MIN_SAVES` saves to `$sp` with no other instruction among them,
the shape the fence produces. The judge decides.
"""
import re

from .csource import _blank
from .integer_repair_support import edit, view
from .line_scan import declaration_end

FAMILY = 'prologue_save_fence'
FAMILIES = (FAMILY,)
MIN_SAVES = 3
FENCE = 'do { } while (0);'
_INSTRUCTION = re.compile(r'^(?:\s*/\*[^*]*\*/)?\s*(?P<op>[a-z][a-z0-9.]*)\s+(?P<operands>[^#\n]*)')
_DIRECTIVES = {'glabel', 'dlabel', 'jlabel', 'endlabel', 'nonmatching'}
_FRAME = re.compile(r'\$sp\s*,\s*\$sp\s*,\s*-')
_SAVE = re.compile(r'\$(?:ra|fp|s[0-8]|f\d+)\s*,\s*(?:0[xX][0-9a-fA-F]+|\d+)?\(\$sp\)')


def saves_together(asm):
    """Whether the assembly opens with the frame, then `MIN_SAVES` or more saves, then something else, with every save
    of a saved register among them."""
    instructions = [(hit['op'], hit['operands'].strip()) for hit in map(_INSTRUCTION.match, asm.splitlines())
                    if hit and hit['op'] not in _DIRECTIVES]
    if not instructions or instructions[0][0] != 'addiu' or not _FRAME.match(instructions[0][1]):
        return False
    def saves(pair):
        return pair[0] in ('sw', 'sd', 'swc1', 'sdc1') and _SAVE.match(pair[1]) is not None
    count = 0
    while count + 1 < len(instructions) and saves(instructions[count + 1]):
        count += 1
    return count >= MIN_SAVES


def variants(source, name, asm=''):
    part = view(source, name)
    if not part or not saves_together(asm or ''):
        return []
    end = declaration_end(part)
    at = part.opening + 1 if end is None else end
    if re.match(r'\s*do\s*\{\s*\}\s*while\s*\(\s*0\s*\)\s*;', _blank(source)[at:part.end]):
        return []
    following = source[at:part.end]
    indent = re.match(r'\s*?\n([ \t]*)', following)
    indent = indent[1] if indent else '    '
    return [(FAMILY, edit(source, [(at, at, f'\n{indent}{FENCE}')]))]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',),
          'order': 80}
