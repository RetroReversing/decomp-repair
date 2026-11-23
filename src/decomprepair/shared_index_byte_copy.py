"""A masked index shared by the two arms of an `if`/`else`, with a byte copy of it that one arm reads, weighted by scopes.

m2c reads `idx = a & 0x7F;` in both arms of the `if (chan != 9) { m = A[idx]; ... } else { m = B[idx]; ... }` that
follows. KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) gives the index one pseudo, one register, for both lookups.
The target keeps the masked value in a halfword local and a byte copy of it that the first arm reads, so the copy is a
second pseudo of its own: `andi $a0,$a3,0x7f; ...; move $v1,$a0` in the delay slot of the arm test, the first arm adding
`$v1`, the second `$a0`. Which of the two gets the lower register is decided by `global.c`'s order: priority is
`floor_log2(refs) * refs / live length`, the references weighted by loop depth. The copy has fewer references than the
index (a set and one read against a set, a copy and one read), so the index takes the first free register and the copy
the next; the target has them the other way round. Reading the copy inside two one-shot `do { } while (0)` scopes
weights its read (two deeper loop levels) until its priority passes the index's (hypothesis from the dump: the two
priorities, 2.4 and 4.5 before, flip). The width of the index matters too: as `s32` the copy and the scopes score 20, as a
`u16` 0 (a `u8` index folds the copy away). On a 280-instruction sequence-event interpreter this took 320 to 0 with the
rest of the function as the target has it (one scope: 20; three: 0).

The shape: `X = E & K;` (a declaration with its initialiser, or an assignment to a plain integer local), K a number
from 1 to 255, and exactly two reads of `X` after it, one in each arm of the same `if`/`else`, each in a statement
that is a declaration with an initialiser or an assignment. The child declares `u8 X_copy = X;` after the assignment, gives
`X` the type `u16` (when it is a wider integer), and reads `X_copy` in one arm, the statement inside `k` nested
one-shot scopes (a declaration is split from its initialiser first). Children: each arm, with two scopes and with
three, at most four. A hypothesis; the judge decides."""
import re

from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, integer, locals_for, refs, view
from .local_web_split import _blocks, _innermost

FAMILY = 'shared_index_byte_copy'
FAMILIES = (FAMILY,)
LIMIT = 4
SCOPES = (2, 3)

_INIT = re.compile(rf'(?m)^([ \t]*)({INTEGER})[ \t]+({IDENT})[ \t]*=[ \t]*([^;{{}}]*&[ \t]*({NUMBER}))[ \t]*;[ \t]*$')
_ASSIGN = re.compile(rf'(?m)^([ \t]*)({IDENT})[ \t]*=[ \t]*([^;{{}}]*&[ \t]*({NUMBER}))[ \t]*;[ \t]*$')
_DECLARATION = re.compile(rf'\s*({INTEGER})\s+({IDENT})\s*=\s*([^;{{}}]*)')
_WIDE = {'s32', 'u32', 'int', 'unsigned int', 'signed int', 'long', 'short', 's16', 'unsigned short', 'signed short'}


def _statement(clean, at):
    start = max(clean.rfind(c, 0, at) for c in ';{}') + 1
    end = clean.find(';', at)
    return (start, end + 1) if end >= 0 else None


def _wrap(text, indent, scopes):
    return indent + 'do { ' * scopes + text.strip() + ' } while (0);' * scopes


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto)\b', part.body):
        return []
    clean = part.clean
    blocks = _blocks(clean, part.opening, part.end)
    decls = {d['name']: d for d in locals_for(part)}
    found = []
    for m in _INIT.finditer(clean, part.opening + 1, part.end):
        found.append((m.group(3), m.start(), m.end(), m.group(1), m.group(2), m.start(2), m.end(2), int(integer(m.group(5))), None))
    for m in _ASSIGN.finditer(clean, part.opening + 1, part.end):
        if m.group(2) in decls:
            d = decls[m.group(2)]
            found.append((m.group(2), m.start(), m.end(), m.group(1), d['type'], d.start('type'), d.end('type'), int(integer(m.group(4))), d))
    out = []
    for var, start, end, indent, kind, kstart, kend, mask, decl in found:
        copy = f'{var}_copy'
        if not 1 <= mask <= 255 or re.search(rf'\b{copy}\b', clean):
            continue
        if decl is None:
            reads = [m for m in re.finditer(rf'\b{re.escape(var)}\b', clean[end:part.end]) if not re.match(r'\s*=(?!=)', clean[end + m.end():])]
            reads = [end + m.start() for m in reads]
            if re.search(rf'\b{re.escape(var)}\s*(?:=(?!=)|\+\+|--)', clean[end:part.end]):
                continue
        else:
            reads = [m.start() for m in refs(part, decl) if m.start() > end]
        if len(reads) != 2:
            continue
        first, second = (_innermost(blocks, r) for r in reads)
        if not first or not second or first == second or not first[1] < second[0] or not first[0] > end \
                or clean[first[1] + 1:second[0]].strip() != 'else':
            continue
        spans = [_statement(clean, r) for r in reads]
        if not all(spans):
            continue
        for arm in (0, 1):
            span = spans[arm]
            text = clean[span[0]:span[1]]
            if text.count('{') or text.count('}') or len(re.findall(rf'\b{re.escape(var)}\b', text)) != 1:
                continue
            lead = re.match(r'\s*', source[span[0]:span[1]]).group()
            body = source[span[0]:span[1]].strip()
            inner = re.sub(rf'\b{re.escape(var)}\b', copy, body)
            declared = _DECLARATION.match(inner)
            for scopes in SCOPES:
                pad = lead.lstrip('\n') or indent
                if declared:
                    head = f'{declared.group(1)} {declared.group(2)};\n'
                    text_new = '\n' + pad + head.rstrip('\n') + '\n' + _wrap(f'{declared.group(2)} = {declared.group(3).strip()};', pad, scopes)
                else:
                    text_new = '\n' + _wrap(inner, pad, scopes)
                edits = [(span[0], span[1], text_new)]
                line = f'\n{indent}u8 {copy} = {var};' if decl is None else f'\n{indent}{copy} = {var};'
                edits.append((end, end, line))
                if decl is not None:
                    declared_at = part.clean.find(';', decl.end()) + 1
                    edits.append((declared_at, declared_at, f'\n    u8 {copy};'))
                if source[kstart:kend] in _WIDE:
                    edits.append((kstart, kend, 'u16'))
                out.append((FAMILY, edit(source, edits)))
                if len(out) == LIMIT:
                    return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
