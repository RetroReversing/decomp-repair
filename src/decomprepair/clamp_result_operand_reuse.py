"""A clamp's result held in a local of its own, written back into the local it clamps as one conditional expression.

m2c turns a clamp into two assignments to a fresh local: `x = x + y; if (x < 0x80) { r = x & ((~x) >> 31); } else
{ r = 0x7F; } f(r & 0xFF);`. A game's source clamped the variable itself: `x = (x < 0x80) ? (x & ((~x) >> 31)) : 0x7F;`
and read it again. In KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) the conditional expression is built in a temporary
that is then moved into `x` (`and $v1,$a3,$v0; addiu $v1,$zero,0x7f; ...; move $a3,$v1`), so `x` keeps its register for the
whole value, where a separate result local makes a second pseudo that takes a register of its own, and two plain `if`/`else`
assignments of `x` store into `x` directly with no temporary (`and $a3,$a3,$v0`; 200 on the function below). On a
280-instruction sequence-event interpreter two such clamps (a velocity and a key) were 390 as m2c wrote them and 10 written
back as conditional expressions, with no other edit.

The shape: `if (X < K) { R = EXPR1; } else { R = EXPR2; }` (any of `<`, `<=`, `>`, `>=` against a number; braces optional),
`X` and `R` different plain integer locals of one declared type, `R` mentioned nowhere before the statement and assigned
by no other statement, and `X` mentioned nowhere after the statement (its first mention before it is an assignment, so
no loop carries a value of it around to a read above). Then the statement is `X = (X < K) ? (EXPR1) : (EXPR2);`, every later `R` is `X`, and `R`'s
declaration goes. One child per clamp, at most four. A hypothesis; the judge decides."""
import re

from .integer_repair_support import IDENT, edit, locals_for, refs, view

FAMILY = 'clamp_result_operand_reuse'
FAMILIES = (FAMILY,)
LIMIT = 4

_NUMBER = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*'
_CLAMP = re.compile(
    rf'if\s*\(\s*(({IDENT})\s*(?:<=|>=|<|>)\s*{_NUMBER})\s*\)\s*{{?\s*({IDENT})\s*=\s*([^;{{}}]+);\s*}}?'
    rf'\s*else\s*{{?\s*({IDENT})\s*=\s*([^;{{}}]+);\s*}}?')
_WRITE = re.compile(r'\s*(?:=(?!=)|\+\+|--|[-+*/%&|^]=|<<=|>>=)')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    decls = {d['name']: d for d in locals_for(part)}
    out = []
    for clamp in _CLAMP.finditer(part.clean, part.opening + 1, part.end):
        operand, result = clamp.group(2), clamp.group(3)
        if clamp.group(5) != result or operand == result or operand not in decls or result not in decls:
            continue
        if re.sub(r'\s+', ' ', decls[operand]['type']) != re.sub(r'\s+', ' ', decls[result]['type']):
            continue
        if re.search(rf'\b{re.escape(result)}\b', clamp.group(4) + ' ' + clamp.group(6)):
            continue
        mentions = refs(part, decls[result])
        writes = [m.start() for m in mentions if _WRITE.match(part.clean, m.end())]
        if not mentions or mentions[0].start() != clamp.start(3) or len(writes) != 2 or writes[1] != clamp.start(5):
            continue
        uses = refs(part, decls[operand])
        before = [m for m in uses if m.start() < clamp.start()]
        if not before or any(m.start() >= clamp.end() for m in uses):
            continue
        if not (re.match(r'\s*=(?!=)', part.clean[before[0].end():]) and
                re.search(r'[;{}]\s*$', part.clean[:before[0].start()])):
            continue
        sets = [source[clamp.start(g):clamp.end(g)].strip() for g in (4, 6)]
        edits = [(clamp.start(), clamp.end(), f'{operand} = ({source[clamp.start(1):clamp.end(1)]}) ? ({sets[0]}) : ({sets[1]});')]
        edits += [(m.start(), m.end(), operand) for m in mentions if m.start() > clamp.end()]
        d = decls[result]
        start = part.clean.rfind('\n', 0, d.start()) + 1
        tail = re.match(r'[ \t]*\n', part.clean[d.end():])
        whole = bool(tail) and part.clean[start:d.start()].strip() == ''
        edits.append((start if whole else d.start(), d.end() + (tail.end() if whole else 0), ''))
        out.append((FAMILY, edit(source, edits)))
        if len(out) == LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
