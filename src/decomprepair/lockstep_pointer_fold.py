"""A second pointer that walks a loop in lockstep with the first, written as an offset from the first.

m2c keeps a record's field address as a pointer of its own, set once before the loop and stepped by the same
amount as the record pointer:

    var_s0 = var_s1 + 2;                       /* (sometimes in both arms of an `if`: identical_arm_collapse) */
    do {
        ... *(u16 *)((char *) var_s0 + 0) ... *(s32 *)((char *) var_s0 + 2) ...
        var_s1 += 0x1C;
        var_s0 += 0x1C;
    } while (var_a0 != 0xFFFF);

A user variable for the second pointer is a pointer of its own, so its set sits before the loop in source order. The
game's record pointer was one variable and the compiler made the second register itself, as a derived address (a
"giv") of the record pointer: the loop pass emits a giv's start value after the constants it hoists
(`ori $s5,$zero,0xFFFF` then `addiu $s0,$s1,2`), where the variable's own set comes before them. A KMC GCC 2.7.2
function whose other rows were right differed in exactly that order (60 -> 20 with the fold, measured in the
isolated judge, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`). `derived_pointer_fold` does this for m2c's
`M2C_FIELD(var, T, off)` reads with the set at the loop's tail; this one reads the cast spelling a saved best
has, `((char *) var_s0) + off`, and a set before the loop.

When `q` is assigned only `q = P + K;` (before the loop) and `q += S;` (once, in the do-while that also holds
`P += S;` with the same step), `P` is not assigned between the set and the loop, nothing reads `q` between the two
steps or outside the loop, and both point at objects of the same size (so the same step is the same distance), every
use of `q` in the loop becomes `(P + K)` (cast to `q`'s type when that differs) and the set and the step go. A
variant that also drops the `if (c) { } else { }` an identical-arm set leaves empty is offered beside it, when `c`
is a plain name. A candidate for the exact judge, never an equivalence claim; the compiler's reason (the giv's start
is emitted after the hoisted constants) is a hypothesis read from one function's dumps."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'lockstep_pointer_fold'
FAMILIES = (FAMILY,)

SIZES = {'u8': 1, 's8': 1, 'char': 1, 'void': 1, 'u16': 2, 's16': 2, 'short': 2,
         'u32': 4, 's32': 4, 'int': 4, 'f32': 4, 'float': 4}
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_EMPTIED_IF = re.compile(r'(?m)^[ \t]*if[ \t]*\([ \t]*' + IDENT + r'[ \t]*\)[ \t]*\n[ \t]*\{[ \t\n]*\}[ \t]*\n[ \t]*else[ \t]*\n[ \t]*\{[ \t\n]*\}[ \t]*\n')


def _pointer(clean, base, end, name):
    """(pointee word, declared type text) of a one-star local `T *name;`, or None."""
    hit = re.search(rf'(?m)^[ \t]*((?:unsigned\s+)?{IDENT})[ \t]*\*[ \t]*{re.escape(name)}[ \t]*;', clean[base:end])
    return (hit[1].split()[-1], re.sub(r'\s+', ' ', hit[1]) + ' *') if hit else None


def _loops(clean, base, end):
    """(open brace, close brace) of every `do { } while (...);` in the body."""
    found = []
    for hit in re.finditer(r'\bdo\s*\{', clean[base:end]):
        opening = base + hit.end() - 1
        stop = close(clean, opening, '{', '}')
        if stop and re.match(r'\s*while\s*\([^;]*\)\s*;', clean[stop:end]):
            found.append((opening, stop))
    return found


def _line(clean, start, stop):
    """A statement's span widened over the blanks before it and the newline after it when it fills its line."""
    line_start = clean.rfind('\n', 0, start) + 1
    if not clean[line_start:start].strip():
        tail = re.match(r'[ \t]*\n', clean[stop:])
        if tail:
            return line_start, stop + tail.end()
    return start, stop


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, base, end = part.clean, part.opening + 1, part.end
    result = []
    done = set()
    for opening, stop in _loops(clean, base, end):
        steps = [(m[1], m[2], m.start() + opening, m.end() + opening)
                 for m in re.finditer(rf'(?<![\w.>*])({IDENT})[ \t]*\+=[ \t]*({NUMBER})[ \t]*;', clean[opening:stop])]
        for q, amount, q_start, q_end in steps:
            if q in done:
                continue
            for walk, walk_amount, w_start, w_end in steps:
                if walk == q or walk_amount != amount:
                    continue
                edits = _fold(source, clean, base, end, opening, stop, q, walk, amount, (q_start, q_end), (w_start, w_end))
                if edits:
                    done.add(q)
                    plain = edit(source, edits)
                    result.append((FAMILY, plain))
                    emptied = _EMPTIED_IF.sub('', plain)
                    if emptied != plain:
                        result.append((FAMILY, emptied))
                    break
    return result


def _fold(source, clean, base, end, opening, stop, q, walk, amount, q_step, w_step):
    q_kind, w_kind = _pointer(clean, base, end, q), _pointer(clean, base, end, walk)
    if not q_kind or not w_kind or SIZES.get(q_kind[0]) is None or SIZES.get(q_kind[0]) != SIZES.get(w_kind[0]):
        return None
    sets = list(re.finditer(rf'(?<![\w.>*]){re.escape(q)}[ \t]*=(?!=)[ \t]*([^;]*);', clean[base:end]))
    sets = [(base + s.start(), base + s.end(), s[1]) for s in sets]
    if not sets:
        return None
    offsets = set()
    for start, stop_set, rest in sets:
        derived = re.fullmatch(rf'{re.escape(walk)}[ \t]*\+[ \t]*({NUMBER})[ \t]*', rest)
        if not derived or start > opening:
            return None
        offsets.add(derived[1])
    if len(offsets) != 1:
        return None
    offset = offsets.pop()
    # the walking pointer is not written between the last set and the loop
    if re.search(rf'(?<![\w.>*]){re.escape(walk)}[ \t]*(?:[-+*/|&^]|<<|>>)?=(?!=)', clean[sets[-1][1]:opening]):
        return None
    # nothing reads q between its step and the walking pointer's
    low, high = sorted((q_step, w_step))
    if re.search(rf'\b{re.escape(q)}\b', clean[low[1]:high[0]]):
        return None
    # every other mention of q is a read inside the loop or its declaration
    spans = [(s, e) for s, e, _ in sets] + [q_step]
    reads = []
    for hit in re.finditer(rf'\b{re.escape(q)}\b', clean[base:end]):
        position = base + hit.start()
        if any(s <= position < e for s, e in spans):
            continue
        if opening < position < stop:
            reads.append(position)
        elif not (re.match(r'[ \t]*;', clean[base + hit.end():base + hit.end() + 4])
                  and re.fullmatch(rf'[ \t]*(?:unsigned\s+)?{IDENT}[ \t]*\*[ \t]*', clean[clean.rfind('\n', 0, position) + 1:position])):
            return None
    replacement = f'({walk} + {offset})'
    if q_kind[0] != w_kind[0]:
        replacement = f'(({q_kind[1]}) {replacement})'
    edits = [(position, position + len(q), replacement) for position in reads]
    edits += [(*_line(clean, s, e), '') for s, e in spans]
    return edits
