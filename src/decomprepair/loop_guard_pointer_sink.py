"""A pointer to a global set before a `for` loop that reads through it, set inside the loop's entry guard instead.

SN64 GCC 2.8.1 (`-G0 -mips3 -O2 ... -mfp64`), a 108-instruction N64 cheat-code checker: a loop over a table of
codes compares each entry with the pressed-buttons word, `*key != c->codes[in->pos]`, which the target reloads every
iteration (`lw $v1, 0($a2)`) from a full address in `$a2` that it builds after the table-empty test, in the loop's
preheader (`beqz $v1, ...; addiu $s0, ...` then `addiu $a2, $a0, %lo(D_801070A0)`, `$a0` the `%hi` of the outer test's
read). The saved best set `key = &D_801070A0;` before the `if` that tests the word, and sat at 220 through a dozen
sessions: every placement before the loop puts the `addiu` above the table test (it becomes that branch's delay-slot
filler), and every placement inside the loop lets cse fold `*key` back into `%lo(D_801070A0)($hi)`. The loop written as
the guarded `do` loop it compiles to, with the pointer set inside the guard, is exact (220 -> 0):

    c = D_800AA388;
    if (c->codes != NULL) {
        key = &D_801070A0;
        do {
            ...
            c++;
        } while (c->codes != NULL);
    }

Read from the cse and loop dumps (one function; the reason is from the dumps, not the compiler's source): the set is
after the guard's jump, the reads are past the loop's top label, so cse never sees the two in one extended block and
leaves `(mem key)` alone, and the set lands where loop.c would have put a hoisted address.

`loop_guard_pointer_sink`: a statement `p = &G;` or `p = G;` (a global's address) in a block, followed later in that
block (at any depth: the saved best had it inside an `if`) by `for (INIT; COND; INCR) { BODY }` that is the only
place `p` is mentioned after it (not before the loop, not after it), becomes `INIT; if (COND) { p = ...; do { BODY INCR; } while (COND); }`; a second child keeps the `for`
inside the guard. Only when BODY has no `continue` (it would skip INCR in the `do`), INIT, COND and INCR are
non-empty, and COND makes no call and changes nothing (it is evaluated once more at the guard).
"""
import re

from . import c_scan
from .integer_repair_support import edit, view

FAMILY = 'loop_guard_pointer_sink'
FAMILIES = (FAMILY,)

SET = re.compile(r'(?m)^([ \t]*)([A-Za-z_]\w*)\s*=\s*(&\s*[A-Za-z_]\w*|[A-Za-z_]\w*)\s*;[ \t]*\n')
FOR = re.compile(r'(?m)^([ \t]*)for\s*\(')


def _python_parts(header):
    """INIT, COND, INCR of a `for` header's parenthesised text, or None."""
    depth, cuts = 0, []
    for index, char in enumerate(header):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif char == ';' and depth == 0:
            cuts.append(index)
    if len(cuts) != 2:
        return None
    parts = header[:cuts[0]].strip(), header[cuts[0] + 1:cuts[1]].strip(), header[cuts[1] + 1:].strip()
    return parts if all(parts) else None


_parts = _python_parts
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _parts(header):
        cuts = _scan.top_offsets(header, ';', 2)
        if len(cuts) != 2:
            return None
        parts = header[:cuts[0]].strip(), header[cuts[0] + 1:cuts[1]].strip(), header[cuts[1] + 1:].strip()
        return parts if all(parts) else None


def _indent(text, by='    '):
    return ''.join(by + line if line.strip() else line for line in text.splitlines(True))


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    end = part.end - 1
    found = []
    for hit in SET.finditer(clean, part.opening + 1, end):
        pointer, value = hit[2], hit[3]
        if pointer == value.lstrip('&').strip():
            continue
        block = c_scan.enclosing_block(clean, hit.start(), part.opening)
        block_end = c_scan.close(clean, block) if block >= 0 else -1
        if block < 0 or block_end < 0:
            continue
        mention = re.compile(r'(?<![\w.>])' + re.escape(pointer) + r'\b')
        for loop in FOR.finditer(clean, hit.end(), block_end):
            paren = loop.end() - 1
            paren_end = c_scan.close(clean, paren, '(', ')')
            if paren_end < 0:
                break
            brace = paren_end + 1
            while brace < len(clean) and clean[brace].isspace():
                brace += 1
            if brace >= len(clean) or clean[brace] != '{':
                break
            brace_end = c_scan.close(clean, brace)
            parts = _parts(clean[paren + 1:paren_end])
            body = clean[brace + 1:brace_end]
            if (brace_end < 0 or not parts or mention.search(clean, hit.end(), loop.start())
                    or mention.search(clean, brace_end + 1, end) or not mention.search(body)
                    or re.search(r'\bcontinue\b', body) or re.search(r'\w\s*\(|\+\+|--|[^=!<>]=[^=]', parts[1])):
                break
            init, cond, incr = parts
            indent = loop[1]
            text = source[brace + 1:brace_end]
            inner = text.rstrip(' \t')
            set_line = f'{indent}    {pointer} = {value};\n'
            as_do = (f'{indent}{init};\n{indent}if ({cond}) {{\n{set_line}{indent}    do {{'
                     + _indent(inner) + f'{indent}        {incr};\n{indent}    }} while ({cond});\n{indent}}}')
            as_for = (f'{indent}{init};\n{indent}if ({cond}) {{\n{set_line}{indent}    for (; {cond}; {incr}) {{'
                      + _indent(inner) + f'{indent}    }}\n{indent}}}')
            for replacement in (as_do, as_for):
                found.append((FAMILY, edit(source, [(hit.start(), hit.end(), ''),
                                                    (loop.start(), brace_end + 1, replacement)])))
            break
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
