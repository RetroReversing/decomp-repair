"""A parameter's first call in a one-shot scope, with the address-holding pointer local written out: priority swaps.

GCC 2.x hands the saved registers to pseudos in order of `floor_log2(refs) * refs / live length` (global.c), and flow.c
counts a reference once per loop it sits in, so `do { f(p, ...); } while (0);` is one reference more for `p` at no
instruction cost (`loop_weight_scope` and `call_one_shot_scope` do that for counters and one call). A function whose
saved registers come out swapped between a parameter and the address of a global table is decided by two things at
once, and neither edit alone is visible to a one-edit-at-a-time search:

- a pointer local that holds the table's address (`u8 *t; do { t = gOptionChoice; } while (0); ... t[0] ... t[0]`, the
  shape `scoped_byte_read_call` writes to lift that pseudo) is the address pseudo of the table and, with the scope, one
  reference too many: it outranks the parameter and takes the register the target gives the parameter. Written out
  (`gOptionChoice[0]`) alone it scores worse (35 -> 85), because the parameter then loses to the first parameter;
- the call that takes the parameter first (`f(arg1, arg2, &sp);`) wrapped in the one-shot scope raises the parameter
  above that one (4 references against 3 over a live range of 9 instructions: 0.89 against 0.34).

A KMC GCC 2.7.2 N64 sound-pan function (`-G0 -mips3 -mgp32 -mfp32 -O2`, 110 instructions, the registers `$s0` and `$s2`
exchanged between the magnitude and the option-table address on seven rows, 35 -> 0 in the isolated judge) matched with
both edits together; alone: 85 (the pointer written out) and 35 (the wrapper, the old pointer kept). The explanation
(the priority table read from `-dl -dg`) is a hypothesis, not confirmed in the compiler source.

`variants` offers, for each call statement that names a parameter (one that is used elsewhere too), the call wrapped, and
the same with every single-assignment pointer local that holds a symbol's address replaced by the symbol. The judge
decides."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'argument_weight_scope'
FAMILIES = (FAMILY,)
LIMIT = 6
_CALL = re.compile(rf'(?<=[;{{}}])(?P<lead>[ \t\r\n]*)(?P<call>{IDENT}\s*\([^;{{}}]*\))\s*;')
_SET = re.compile(rf'(?:\bdo\s*\{{\s*)?(?<![\w.>])(?P<p>{IDENT})\s*=\s*(?P<sym>{IDENT})\s*;(?:\s*\}}\s*while\s*\(\s*0\s*\)\s*;)?')
_KEYWORD = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'do', 'else'}


def _parameters(part):
    head = part.clean[:part.opening]
    signature = head[head.rindex('(') + 1:head.rindex(')')] if '(' in head and ')' in head else ''
    return [m[1] for m in (re.search(rf'({IDENT})\s*(?:\[[^\]]*\])?\s*$', piece) for piece in signature.split(',')) if m]


def _pointer_inline(source, part, parameters):
    """The edits that write out one `T *p;` local holding a symbol's address, or None."""
    clean = part.clean
    for decl in re.finditer(rf'(?m)^[ \t]*(?:{IDENT}[ \t]+)+\*[ \t]*(?P<p>{IDENT})[ \t]*;', clean[part.opening:part.end]):
        start = part.opening + decl.start()
        local = decl['p']
        uses = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', clean[part.opening:part.end])]
        sets = [m for m in _SET.finditer(clean, part.opening, part.end) if m['p'] == local]
        if len(sets) != 1 or sets[0]['sym'] in parameters or re.search(
                rf'(?m)^[ \t]*(?:{IDENT}[ \t]+)+\**[ \t]*{re.escape(sets[0]["sym"])}\b', clean[part.opening:part.end]):
            continue
        reads = [m for m in uses if part.opening + m.start() >= sets[0].end() and part.opening + m.start() != start]
        if not reads or any(not clean[part.opening + m.end():].startswith('[') for m in reads):
            continue
        edits = [(start, part.opening + decl.end() + 1 if clean[part.opening + decl.end():][:1] == '\n' else part.opening + decl.end(), ''),
                 (sets[0].start(), sets[0].end(), '')]
        edits += [(part.opening + m.start(), part.opening + m.end(), sets[0]['sym']) for m in reads]
        return edits
    return None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    parameters = _parameters(part)
    clean = part.clean
    wraps = []
    for hit in _CALL.finditer(clean, part.opening + 1, part.end):
        callee = hit['call'].split('(')[0].strip()
        if callee in _KEYWORD or re.search(r'\bdo\s*\{\s*$', clean[:hit.start('lead')] + hit['lead']):
            continue
        named = [p for p in parameters if re.search(rf'(?<![\w.>]){re.escape(p)}\b', hit['call'])]
        if not any(len(re.findall(rf'(?<![\w.>]){re.escape(p)}\b', clean[part.opening:part.end])) >= 2 for p in named):
            continue
        wraps.append((hit.start('call'), hit.end(), 'do { ' + source[hit.start('call'):hit.end()].strip() + ' } while (0);'))
    inline = _pointer_inline(source, part, parameters)
    result = []
    for wrap in wraps[:LIMIT]:
        if inline:
            result.append((FAMILY, edit(source, [wrap] + inline)))
        result.append((FAMILY, edit(source, [wrap])))
    return result[:LIMIT]
