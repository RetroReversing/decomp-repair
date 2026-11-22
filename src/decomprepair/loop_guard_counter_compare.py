"""A loop's entry guard written as the compare its own counter makes (`for (i = 0; i < n; i++)`), not as `n != 0`.

m2c turns `for (i = 0; i < n; i++) { ... }` into `if (n != 0) { do { ... i += 1; } while (i < n); }` (or `if (n > 0)`):
the guard no longer names the counter. GCC 2.7.2 (KMC, `-O2`) compiles the two differently. Written as the compare
`i < n`, the guard keeps a register operand (the counter, known to be 0 there, is replaced by whichever register
cse picked as the canonical holder of 0), `combine` then folds the compare into the branch and re-emits the zero
set at the compare's place, and the temporary that held the compare result keeps a stale reference count. `reload`
gives a pseudo that has references but no register and no equivalence a stack slot, so the frame grows by one 8-byte
slot that no instruction reads or writes. The code is unchanged, so every register and offset row matches and only
the frame size and the save/restore offsets differ (an `-0x98` frame against the target's `-0xa0`), which no spelling
of padding fixes: a named local sits *before* every spill slot and shifts all of them by eight.

Measured (one KMC GCC 2.7.2 `-G0 -mips3 -mgp32 -mfp32 -O2` function of 401 instructions, nine spilled values and a
frame 8 bytes short): `if (var_s6 != 0)` over a `do { ... } while (var_s3 < var_s6)` loop became
`if (var_s3 < var_s6)`, where `var_s3` is the counter set to 0 earlier in the same block, and the frame matched.
Controlled on small functions with the same cc1: the slot appears for `n > Z` and `Z < n` (unsigned or signed, `Z` a
register holding 0) before a loop and not for `!=`, `==`, `>=`, `<` against the same register, nor when the zero is
the literal 0. The explanation (a stale reference count on the combined compare's temporary) is read from combine.c
and reload1.c and is a hypothesis; the frame figures are the evidence.

Offered for an `if (N != 0)` or `if (N > 0)` (`N` a plain local; `!=` only when `N` is unsigned, where it is the same
test as `0 < N`) whose guarded block holds a `while (I < N)` loop test and where `I` is a local assigned `0` by an
earlier statement and not written between that statement and the guard. A candidate; the judge decides.

The guard alone moves the frame and the register allocation together (22 -> 355 in the measured function: the compare
now reads the counter, which cse maps to the longest-lived zero holder, and combine re-emits that holder's zero set at
the guard, so its priority changes). It pays off only with a second edit, so every child of `disjoint_local_merge` on
the guarded text is offered too, as one combined child: there, the second loop's `temp_s1_2` (m2c's name for the
register's third role) written as the packed-size maximum `var_s1` took the function from 355 to 0 (the merge alone
leaves 22). A greedy chain never takes the first step, so the combination has to be one child.
"""
import re

from .disjoint_local_merge_repairs import variants as merges
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'loop_guard_counter_compare'
FAMILIES = (FAMILY,)
LIMIT = 6
GUARD = re.compile(rf'\bif\s*\(\s*(?P<n>{IDENT})\s*(?P<op>!=|>)\s*0\s*\)')
KIND = r'(?:(?:unsigned|signed)\s+)?(?:(?:long|short)\s+)?' + IDENT


def _declared(part, name):
    """The type text of the function-level declaration `T name;`, or ''."""
    found = re.search(rf'(?:^|[;{{}}])\s*(?P<type>{KIND})\s+{re.escape(name)}\s*;', part.clean[part.opening + 1:part.end])
    return re.sub(r'\s+', ' ', found['type']).strip() if found else ''


def _unsigned(kind):
    return bool(re.match(r'unsigned\b|u(?:8|16|32|64)$', kind))


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto)\b', part.body):
        return []
    clean = part.clean
    result = []
    for guard in GUARD.finditer(clean, part.opening, part.end):
        count = guard['n']
        kind = _declared(part, count)
        if not kind or (guard['op'] == '!=' and not _unsigned(kind)):
            continue
        brace = guard.end()
        while clean[brace].isspace():
            brace += 1
        if clean[brace] != '{':
            continue
        stop = close(clean, brace, '{', '}')
        if not stop:
            continue
        block = clean[brace:stop]
        before = clean[part.opening:guard.start()]
        for zero in re.finditer(rf'(?<![\w.>])(?P<i>{IDENT})\s*=\s*0\s*;', before):
            counter = zero['i']
            if counter == count or not _declared(part, counter):
                continue
            if not re.search(rf'\bwhile\s*\(\s*{re.escape(counter)}\s*<\s*{re.escape(count)}\s*\)', block):
                continue
            # the zero is the counter's last write before the guard, and its address is never taken
            rest = before[zero.end():]
            if (re.search(rf'(?<![\w.>]){re.escape(counter)}\s*(?:[-+*/|&^%]|<<|>>)?=(?!=)|'
                          rf'(?:\+\+|--)\s*{re.escape(counter)}\b|(?<![\w.>]){re.escape(counter)}\s*(?:\+\+|--)', rest)
                    or re.search(rf'&\s*{re.escape(counter)}\b', clean[part.opening:part.end])):
                continue
            changed = edit(source, [(guard.start(), guard.end(), f'if ({counter} < {count})')])
            if changed not in result:
                result.append(changed)
            break
        if len(result) >= LIMIT:
            break
    combined = []
    for text in result:
        combined += [child for _, child in merges(text, name) if child != text]
    return [(FAMILY, text) for text in result + combined if text != source]
