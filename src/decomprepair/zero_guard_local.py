"""An `if (0)` block (a debug print the compiler kept) guarded by a local flag set to zero.

A 618-instruction N64 display-list interpreter (SN64 GCC 2.8.1, `-mfp32`) keeps a dead debug print in one arm of its
command switch, tested on a register that holds zero:

    addu  $t3, $zero, $zero
    beqz  $t3, .L1
    lui   $a0, %hi(D_80007934)     ; "MTXLOAD\\n"
    jal   func_800899C4

m2c and the drafts write it `if (0) { func_800899C4("MTXLOAD\\n"); }`, which the front end deletes, so the block, its
string and the register the test uses are missing (the spill register reload picks then shifts too). The game tested a
local debug flag: `int debug = 0;` at the top and `if (debug)` in the loop. cse does not carry the constant across the
loop's head (a label with two predecessors), so the test stays; the pseudo is equivalent to 0 and reload rematerialises
it with the `addu` before the branch. 9751 -> 9166 in the isolated judge (`-mfp32`), the block's rows exact. That cse
stops at the loop's label is read from the dump of this one function; the judge decides each child.

Children (`zero_guard_local`, one per function): every `if (0)` / `if (0 != 0)` / `if (FALSE)` test in the function
reads a new local `int debug = 0;` (another name when `debug` is taken) declared first in the body.
"""
import re

from .csource import _blank, find

FAMILY = 'zero_guard_local'
FAMILIES = (FAMILY,)
TEST = re.compile(r'\bif\s*\(\s*(?:0|0\s*!=\s*0|FALSE|false)\s*\)')


def variants(source, name):
    text = rewrite(source, name)
    return [(FAMILY, text)] if text else []


def rewrite(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return None
    tests = list(TEST.finditer(clean, opening, end))
    if not tests:
        return None
    words = set(re.findall(r'[A-Za-z_]\w*', clean))
    flag, n = 'debug', 2
    while flag in words:
        flag, n = f'debug{n}', n + 1
    out = source
    for hit in reversed(tests):
        out = out[:hit.start()] + f'if ({flag})' + out[hit.end():]
    line_end = out.find('\n', opening)
    if line_end < 0:
        return None
    first = re.match(r'[ \t]*', out[line_end + 1:]).group() or '    '
    return out[:line_end + 1] + f'{first}int {flag} = 0;\n' + out[line_end + 1:]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
