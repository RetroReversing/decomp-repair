"""An entry guard that reads a pointer parameter, its loop set-up copies and its loop-head load, written the way the
target's prologue and first block show them (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`, a 108-instruction record
walk over a large frame; one function, 240 -> 0 with the three edits together, 60 with the first two).

The target's first instruction is the guard's halfword load, above the `addiu $sp` and every callee-saved store, and its
first block holds only the argument copies the prologue interleaves; the loop's pointer copies (`move $s2,$a0`, an
`addiu $s7,$sp,..` for a local array's address, `move $s5,$s4`) come after the guard's branch. Three source facts decide
that, read in the GCC 2.7.2 source (sched.c `sched_analyze`, rtlanal.c `true_dependence`) and seen in the second
scheduler's order (`passes.py`):

1. `true_dependence` returns 0 for an unchanging (read-only) read after a changing store, and a load through `$a0` that
   is not unchanging depends on every `sw $sN, off($sp)` of the register-save prologue (the frame store's address
   counts as varying: `rtx_varies_p` exempts only the frame and argument pointers, not `$sp`), so it cannot rise above
   them. Reading the guard through a `const`-qualified pointer (`*(const s16 *) arg0`) makes the load unchanging and the
   second scheduler hoists it to the top, as in the target. The skill's note that a `const` pointer parameter changes
   the prologue's load order is the same fact.
2. The pointer copies (`var = param;`, `T *base = local.array;`) written before the guard are scheduled into the guard's
   own block, ahead of its branch, where they take the slots the target fills with the saves; written as the first
   statements of the guard's body they follow the branch, as the target's do.
3. A declaration with a memory-read initialiser right before the loop (`s32 index = *p; do { .. } while (0);`) is
   scheduled with the block before the loop; assigned inside the `do` it sits with the loop body's own loads, and the
   first scheduler then orders it after the call argument's address set-up, as the target does.

In the measured function the const read and the copy sink brought 240 to 60 together (the copy sink alone made it worse,
650, and the const read alone 350: each needs the other), and the loop-head load the last two rows to 0, so `variants`
offers every combination of the three, the whole set last. The explanations of 2 and 3 are hypotheses; 1 is confirmed
in the compiler source.

`variants` takes the first `if (*p CMP n) { .. }` (or `p->f CMP n`) of the body where `p` is a pointer parameter and
nothing before it loops, jumps or calls; the copy sink moves `x = y;` / `T *x = y;` (y a name, `&name` or `name.member`)
that only the guard's body uses; the loop-head load is the first `T x = <read>; do {` of the guard's body."""
import itertools
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'entry_guard_sink'
CONST_FAMILY = 'entry_guard_const_read'
COPY_FAMILY = 'entry_guard_copy_sink'
LOAD_FAMILY = 'loop_head_load_sink'
FAMILIES = (FAMILY, CONST_FAMILY, COPY_FAMILY, LOAD_FAMILY)

_COMPARE = r'(?:>=|<=|==|!=|>|<)'
_OPERAND = r'-?\s*(?:0[xX][0-9a-fA-F]+|\d+|' + IDENT + r')'
_TAIL = rf'(?=\s*\)?\s*{_COMPARE}\s*{_OPERAND}\s*\)\s*{{)'
_READ_DEREF = re.compile(rf'(?P<read>\*\s*(?P<p>{IDENT})){_TAIL}')
_READ_FIELD = re.compile(rf'(?P<read>(?P<p>{IDENT})\s*->\s*{IDENT}){_TAIL}')
_COPY = re.compile(rf'(?m)(?:^|(?<=[;{{}}]))(?P<indent>[ \t]*)(?P<decl>(?:{IDENT}[ \t]+)+\*[ \t]*)?(?P<x>{IDENT})[ \t]*=(?!=)[ \t]*'
                   rf'(?P<e>&?[ \t]*{IDENT}(?:\.{IDENT})*)[ \t]*;[ \t]*\n?')
_LOAD = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>(?:{IDENT}[ \t]+)*{IDENT})[ \t]+(?P<x>{IDENT})[ \t]*=(?!=)[ \t]*'
                   rf'(?P<e>[^;{{}}\n]*(?:\*|\[|->)[^;{{}}\n]*);[ \t]*\n(?P<gap>\s*)do[ \t]*{{')
_FLOW = re.compile(r'\b(?:do|while|for|goto|switch|return)\b|\b\w+\s*\(|(?<![?\w]):(?!:)')


def _python_close(clean, opening):
    depth = 0
    for index in range(opening, len(clean)):
        if clean[index] == '{':
            depth += 1
        elif clean[index] == '}':
            depth -= 1
            if depth == 0:
                return index
    return -1


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    pass
else:
    def _close(clean, opening):
        found = _scan.close_if(clean, opening, '{', '}', -1)
        return _python_close(clean, opening) if found is NotImplemented else found


def _pointer_params(clean, part):
    """{name: pointee type} of the pointer parameters (`s16 *arg0`; not `void *`, not already `const`)."""
    head = clean[:part.opening]
    signature = head[head.rindex('(', 0, head.rindex(')')) + 1:head.rindex(')')]
    found = {}
    for parameter in signature.split(','):
        match = re.fullmatch(rf'\s*(?P<type>(?:{IDENT}\s+)*{IDENT})\s*\*\s*(?P<name>{IDENT})\s*', parameter)
        if match and match['type'].split()[-1] != 'void' and 'const' not in match['type'].split():
            found[match['name']] = match['type']
    return found


def _guard(clean, part, params):
    """(start, end, parameter, then_open, then_close, is_field) of the entry guard's read, or None."""
    body_start = part.opening + 1
    found = re.search(r'\bif\s*\(', clean[body_start:part.end])
    if not found:
        return None
    at = body_start + found.start()
    if _FLOW.search(clean[body_start:at]):
        return None
    paren = clean.index('(', at)
    level = 0
    for k in range(paren, part.end):
        level += (clean[k] == '(') - (clean[k] == ')')
        if level == 0:
            break
    then_open = clean.find('{', k)
    if then_open < 0 or clean[k + 1:then_open].strip():
        return None
    condition = clean[paren:then_open + 1]
    for pattern in (_READ_DEREF, _READ_FIELD):
        read = pattern.search(condition)
        if read and read['p'] in params:
            then_close = _close(clean, then_open)
            if then_close < 0 or re.match(r'\s*else\b', clean[then_close + 1:]):
                return None
            return paren + read.start('read'), paren + read.end('read'), read['p'], then_open, then_close, \
                pattern is _READ_FIELD
    return None


def _const_read(source, params, guard):
    start, end, name, _, _, field = guard
    pointee = params[name]
    if field:
        return [(start, end, f'(({"const " + pointee} *) {name}){source[start + len(name):end]}')]
    return [(start, end, f'*(const {pointee} *) {name}')]


def _copy_sink(clean, part, guard):
    """Edits that move the pointer copies set before the guard into the guard's body, or None."""
    _, _, _, then_open, then_close, _ = guard
    guard_at = clean.rfind('if', 0, then_open)
    first = part.opening + 1
    edits, assigned, declared = [], [], []
    for match in _COPY.finditer(clean[first:guard_at]):
        x, decl = match['x'], match['decl']
        start, end = first + match.start(), first + match.end()
        root = re.match(rf'&?\s*({IDENT})', match['e'])[1]
        between = clean[end:then_open]
        inside = clean[then_open:then_close]
        if re.search(rf'(?<![\w.>]){re.escape(x)}\b', between) \
                or re.search(rf'(?<![\w.>&]){re.escape(root)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', between) \
                or not re.search(rf'(?<![\w.>]){re.escape(x)}\b', inside) \
                or re.search(rf'(?<![\w.>]){re.escape(x)}\b', clean[then_close:part.end]):
            continue
        edits.append((start, end, f'{match["indent"]}{decl.rstrip()} {x};\n' if decl else ''))
        assigned.append(f'{x} = {re.sub(chr(10), " ", match["e"]).strip()};')
        declared.append(bool(decl))
    if not edits:
        return None
    # a local array's address (written with its declaration) heads the body; the parameter copies follow the body's own
    # leading copies (`var = arg;`), the order the target's moves have
    heads = ' '.join(a for a, d in zip(assigned, declared) if d)
    tails = ' '.join(a for a, d in zip(assigned, declared) if not d)
    run = re.compile(rf'\s*{IDENT}\s*=(?!=)\s*&?\s*{IDENT}(?:\.{IDENT})*\s*;')
    at = then_open + 1
    while (found := run.match(clean, at)) and found.end() < then_close:
        at = found.end()
    extra = [(then_open + 1, then_open + 1, ' ' + heads)] if heads else []
    if tails:
        extra.append((at, at, ' ' + tails))
    return edits + extra


def _load_sink(clean, guard):
    _, _, _, then_open, then_close, _ = guard
    match = _LOAD.search(clean, then_open, then_close)
    if not match:
        return None
    line_end = clean.index(';', match.start('e')) + 1
    return [(match.start(), line_end, f"{match['indent']}{match['type']} {match['x']};"),
            (match.end(), match.end(), f" {match['x']} = {match['e'].strip()};")]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    params = _pointer_params(clean, part)
    guard = _guard(clean, part, params) if params else None
    if not guard:
        return []
    groups = [(CONST_FAMILY, _const_read(source, params, guard)),
              (COPY_FAMILY, _copy_sink(clean, part, guard)),
              (LOAD_FAMILY, _load_sink(clean, guard))]
    groups = [(label, edits) for label, edits in groups if edits]
    result = []
    for size in range(1, len(groups) + 1):
        for chosen in itertools.combinations(groups, size):
            edits = [item for _, group in chosen for item in group]
            result.append((chosen[0][0] if size == 1 else FAMILY, edit(source, edits)))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
