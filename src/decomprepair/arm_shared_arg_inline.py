"""A local derived from one pointer before a two-arm `if`, read as an argument by both arms, written inline in each arm.

`temp_a0 = temp_s4 - 0x28; if (flag) { f(temp_a0, temp_s4, ..); } else { g(temp_a0, temp_s4, ..); }` is what m2c
writes when both arms start with the same `addiu $a0, $s4, -0x28`: the compiler's delay-slot pass moved that one
instruction into the branch's slot, so the decompiler saw a value set before the branch. The game wrote
`f(p - 0x28, p, ..)` in each arm and let the compiler share it. Kept as one local, the value is a pseudo of its own
that the first scheduler hoists above the branch's condition load and the delay-slot filler then takes from
*before* the branch (reorg.c `fill_simple_delay_slots`, which leaves a `USE` of the moved instruction at its old place);
a later forward scan for the registers live at another branch's target (`mark_target_live_regs`) reads that `USE` as
"`$a0` is live here" and refuses to put an `$a0` setter in the delay slot of an earlier branch, so the earlier branch
keeps a `nop` and the instruction the other arm should have shared stays in the arm. Written in each arm the setter is
the arm's own first instruction and the slot is filled from the arm (a hypothesis read from a `cc1` built with prints
in reorg.c, not a statement of the compiler's documentation). Counting references changes too: a pointer used twice
inline is two references where the shared local made it one (`floor_log2(refs) * refs / live length` ranks the
pseudos, global.c), which is why the registers of the pointers a function guards can come out as the target's only
with the inline form.

A KMC GCC 2.7.2 N64 menu function (`-G0 -mips3 -mgp32 -mfp32 -O2`, 335 instructions) had two such locals (the pointer
minus 0x28 shared by a `gSaveKeyRelaxed` branch's two calls, and another by a slot-count branch's): with the address
spelling fixed, writing the first inline took the score 920 -> 860 and the second then 860 -> 0, the second alone 920 -> 920
(`tests` here keep the shape, not the game).

`variants` finds each plain assignment `x = e;` of a pointer or word-sized local whose expression names only locals,
parameters and numbers (no memory read, no call), set once, followed at once by an `if (..) {..} else {..}` whose
condition does not read `x` and whose two arms read it and nothing else does, with none of the expression's names written
in the condition or an arm. It offers each such local inlined on its own and, when there are two or more, all of them
in one child (they only pay off together: the first scan above needs both branches' setters out of the way)."""
import re

from .integer_repair_support import IDENT, edit, view
from .local_weight_ladder import split_declarations

FAMILY = 'arm_shared_arg_inline'
FAMILIES = (FAMILY,)
LIMIT = 8
_WORD_TYPES = {'s32', 'u32', 'int', 'long', 'unsigned', 'signed'}
_CASTS = {'u8', 'u16', 'u32', 's8', 's16', 's32', 'int', 'char', 'short', 'long', 'unsigned', 'signed', 'void', 'u64', 's64'}
_ASSIGN = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<x>{IDENT})[ \t]*=(?!=)[ \t]*(?P<e>[^;{{}}=]+);[ \t]*\n')


def _close(clean, opening):
    depth = 0
    for index in range(opening, len(clean)):
        depth += (clean[index] == '{') - (clean[index] == '}')
        if depth == 0:
            return index
    return -1


def _two_arm_if(clean, at, limit):
    """(then_open, then_close, else_open, else_close, cond_start, cond_end) of the `if` that starts at `at`, or None."""
    match = re.compile(r'[ \t\r\n]*if\s*\(').match(clean, at)
    if not match:
        return None
    paren = match.end() - 1
    level = 0
    for k in range(paren, limit):
        level += (clean[k] == '(') - (clean[k] == ')')
        if level == 0:
            break
    else:
        return None
    then_open = clean.find('{', k)
    if then_open < 0 or clean[k + 1:then_open].strip():
        return None
    then_close = _close(clean, then_open)
    between = re.compile(r'\s*else\s*{').match(clean, then_close + 1)
    if then_close < 0 or not between:
        return None
    else_open = between.end() - 1
    else_close = _close(clean, else_open)
    return (then_open, then_close, else_open, else_close, paren, k) if else_close > 0 else None


def _declaration(clean, part, x):
    """(start, end, type text) of the one-line declaration `T x;` of the local, or None when there is not exactly one."""
    found = list(re.finditer(rf'(?m)^[ \t]*(?P<type>[A-Za-z_][\w \t]*?[ \t*]+){re.escape(x)}[ \t]*;[ \t]*\n',
                             clean[part.opening:part.end]))
    if len(found) != 1:
        return None
    hit = found[0]
    return part.opening + hit.start(), part.opening + hit.end(), hit['type']


def _wrap(expr, before, after):
    """The use's replacement: bare when it is a whole call argument, in parentheses otherwise."""
    text = expr.strip()
    if re.fullmatch(rf'{IDENT}|[0-9a-fA-FxX]+', text):
        return text
    if before.rstrip().endswith(('(', ',')) and after.lstrip().startswith((',', ')')):
        return text
    return f'({text})'


def _candidates(source, name):
    part = view(source, name)
    if not part:
        return source, None, []
    clean = part.clean
    found = []
    for hit in _ASSIGN.finditer(clean, part.opening, part.end):
        x, expr = hit['x'], hit['e']
        declared = _declaration(clean, part, x)
        if not declared:
            continue
        kind = declared[2]
        words = kind.replace('*', ' * ').split()
        if not ('*' in words or (set(words) & _WORD_TYPES and not set(words) & {'volatile', 'const'})) or 'volatile' in words:
            continue
        names = set(re.findall(IDENT, expr)) - _CASTS
        if x in names or re.search(r'[\[\]]|->|\.|\+\+|--|\(\s*\)|(?<![\w)])\*|\bsizeof\b', expr):
            continue
        if len(re.findall(rf'(?<![\w.>]){re.escape(x)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', clean[part.opening:part.end])) != 1 \
                or re.search(rf'&\s*{re.escape(x)}\b', clean[part.opening:part.end]):
            continue
        arms = _two_arm_if(clean, hit.end(), part.end)
        if not arms:
            continue
        then_open, then_close, else_open, else_close, cond_start, cond_end = arms
        if re.search(rf'(?<![\w.>]){re.escape(x)}\b', clean[cond_start:cond_end]):
            continue
        uses = [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(x)}\b', clean[part.opening:part.end])]
        uses = [part.opening + u for u in uses]
        inside = [u for u in uses if then_open < u < then_close], [u for u in uses if else_open < u < else_close]
        outside = [u for u in uses if not (then_open < u < then_close or else_open < u < else_close)
                   and not hit.start('x') <= u < hit.end('x') and not declared[0] <= u < declared[1]]
        if outside or not inside[0] or not inside[1]:
            continue
        if any(re.search(rf'(?<![\w.>]){re.escape(w)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+\s*{re.escape(w)}|{re.escape(w)}\s*\+\+'
                         rf'|&\s*{re.escape(w)}\b', clean[hit.end():else_close + 1]) for w in names):
            continue
        found.append((x, expr.strip(), hit, declared, inside[0] + inside[1]))
    return part, clean, found


def _inline(source, clean, chosen):
    changes = []
    for x, expr, hit, declared, uses in chosen:
        changes.append((hit.start(), hit.end(), ''))
        changes.append((declared[0], declared[1], ''))
        for use in uses:
            end = use + len(x)
            changes.append((use, end, _wrap(expr, clean[max(0, use - 12):use], clean[end:end + 12])))
    return edit(source, changes)


def variants(source, name):
    base = split_declarations(source, name)
    part, clean, found = _candidates(base, name)
    if not part or not found:
        return []
    found = [item for item in found if all(item[0] != other[0] for other in found if other is not item)]
    result = [(FAMILY, _inline(base, clean, [item])) for item in found]
    if len(found) > 1:
        result.append((FAMILY, _inline(base, clean, found)))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
