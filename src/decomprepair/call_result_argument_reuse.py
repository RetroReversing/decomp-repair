"""A call's result held in a local of its own, written back into the local that carried the call's first argument.

m2c names every value it meets: `temp_a0 = table[i]; ... temp_v0 = f(temp_a0, 2); if (temp_v0 != -1) { ... }`. The
argument is in `$a0` for the call and its result in `$v0` after it, so the draft has two pseudos where a game's source
often had one variable (`id = f(id, 2)`). In KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) the two are different
allocation problems. The result local is a plain copy of `$v0` that cse folds into the register itself, so it never
needs a register of its own and the stores that read it go straight to `$v0`; the target keeps the result in the
argument's register (`move $a0,$v0; beq $a0,$s5,...; sw $a0,8($s0)`) because it is the argument's pseudo, assigned a
second time, that the compare and the store read (`global.c`: one pseudo, one register for all its webs; hypothesis for
why the copy is kept: the call result is a second set of a multi-set pseudo that cse does not forward). Writing the
result back into the argument's local took a 280-instruction sequence-event interpreter from 335 to 225 in one step
(its remaining rows were registers elsewhere), with no instruction of the target missing any more (`move $a0,$v0`).

The shape: a statement `R = f(A, ...);` where `R` and `A` are different plain integer locals of one declared type, `R`
is assigned by no other statement and every mention of it comes after this one, and `A` is not mentioned again after the
call (and its first mention before the call is an assignment, so no loop carries a value of it around to a read above
the call). Then the call is `A = f(A, ...);`, every later `R` is `A`, and `R`'s declaration goes. One child per such
statement, at most four. A `register` hint on a scalar declaration is dropped from the child (a draft's search scaffolding hides the declaration
from the scan, and the compiler gets the same pseudo either way). A hypothesis; the judge decides."""
import re

from .integer_repair_support import IDENT, edit, locals_for, refs, view

FAMILY = 'call_result_argument_reuse'
FAMILIES = (FAMILY,)
LIMIT = 4

_CALL = re.compile(rf'(?m)^([ \t]*)({IDENT})[ \t]*=[ \t]*({IDENT})[ \t]*\([ \t]*({IDENT})[ \t]*([,)])')
_PLAIN = re.compile(rf'(?m)^([ \t]*)register[ \t]+(?=(?:s|u)(?:8|16|32)[ \t]+{IDENT}[ \t]*;)')
_WRITE = re.compile(r'\s*(?:=(?!=)|\+\+|--|[-+*/%&|^]=|<<=|>>=)')


def _kind(text, decl):
    return re.sub(r'\s+', ' ', decl['type'])


def variants(source, name):
    source = _PLAIN.sub(r'\1', source)  # a `register` hint hides a declaration from the scalar scan
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    decls = {d['name']: d for d in locals_for(part)}
    out = []
    for call in _CALL.finditer(part.clean, part.opening + 1, part.end):
        result, argument = call.group(2), call.group(4)
        if result == argument or result not in decls or argument not in decls or call.group(3) in decls:
            continue
        if _kind(source, decls[result]) != _kind(source, decls[argument]):
            continue
        end = part.clean.find(';', call.end())
        if end < 0 or part.clean.find('{', call.end(), end) >= 0:
            continue
        mentions = refs(part, decls[result])
        if not mentions or mentions[0].start() != call.start(2) or any(
                _WRITE.match(part.clean, m.end()) for m in mentions[1:]):
            continue
        before = [m for m in refs(part, decls[argument]) if m.start() < call.start(2)]
        if before and not (re.match(r'\s*=(?!=)', part.clean[before[0].end():]) and
                           re.search(r'[;{}]\s*$', part.clean[:before[0].start()])):
            continue
        if any(m.start() > end for m in refs(part, decls[argument])) or not before:
            continue
        edits = [(m.start(), m.end(), argument) for m in mentions]
        d = decls[result]
        line = re.match(r'[ \t]*\n', part.clean[d.end():])
        start = part.clean.rfind('\n', 0, d.start()) + 1
        whole = part.clean[start:d.start()].strip() == ''
        edits.append((start if whole and line else d.start(), d.end() + (line.end() if whole and line else 0), ''))
        out.append((FAMILY, edit(source, edits)))
        if len(out) == LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
