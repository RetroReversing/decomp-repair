"""A local used by one arm only, written as a variable that is idle there.

m2c splits a register that two arms use into two names: `var_s3 = 0x50;` set before the `if`, read by the other arm,
and `var_s3_2 = 0x32;` for the arm in between. The game had one variable: its value from before the `if` is dead in the
arm that sets it again. GCC colours one pseudo per source variable, so the split value takes whichever register is free
instead of the one the other arm uses. On a 261-instruction N64 score table (SN GCC 2.8.1, `-G0 -mips3 -O2`) the two
names were 405 and the one variable 0.

`disjoint_local_merge` and `merge_disjoint_temporaries` merge a later local into an earlier one only when every mention
of the first comes before the second's; here the earlier local is also read after the arm, on the path that never
enters it. `arm_variable_share` wants each local inside its own arm.

The child renames `b` to `a` and drops `b`'s declaration when:
- the two are plain locals of one type whose addresses are not taken;
- every mention of `b` lies in one braced arm of an `if` that no loop holds, and the first is `b = ...;`;
- `a` is not mentioned in that arm, and no later read of `a` can follow it: the arm ends in `return`, or what is left of
  `a` is inside the arm's own `else`, or nowhere.

Pairs m2c numbered from one register (`var_s3`, `var_s3_2`) come first. The exact judge decides.
"""
import re

from .integer_repair_support import edit, locals_for, view
from .pattern_repairs import close

FAMILY = 'idle_arm_local_merge'
FAMILIES = (FAMILY,)
LIMIT = 8


def _arms(clean, opening, end):
    """[(open, close past the brace, offset of the whole `if`/`else`)] of every braced `if` or `else` arm."""
    out = []
    for hit in re.finditer(r'\bif\s*\(', clean[opening:end]):
        at = opening + hit.start()
        shut = close(clean, opening + hit.end() - 1)
        then = re.compile(r'\s*\{').match(clean, shut) if shut else None
        stop = close(clean, then.end() - 1, '{', '}') if then else None
        if not stop:
            continue
        out.append((then.end() - 1, stop, at))
        other = re.compile(r'\s*else\s*\{').match(clean, stop)
        last = close(clean, other.end() - 1, '{', '}') if other else None
        if last:
            out.append((other.end() - 1, last, at))
    return out


def _in_loop(clean, opening, at):
    """Whether position `at` lies inside the body of a `for`, `while` or `do`, or between a label and a `goto` back
    to it."""
    for jump in re.finditer(r'\bgoto\s+([A-Za-z_]\w*)', clean[opening:]):
        label = re.search(rf'(?<![\w.>?]){jump[1]}\s*:(?!:)', clean[opening:])
        if not label or label.start() < at - opening < jump.start():
            return True
    for hit in re.finditer(r'\b(?:for|while)\s*\(|\bdo\s*\{', clean[opening:at]):
        start = opening + hit.start()
        if hit[0].startswith('do'):
            stop = close(clean, opening + hit.end() - 1, '{', '}')
        else:
            shut = close(clean, opening + hit.end() - 1)
            body = re.compile(r'\s*\{').match(clean, shut) if shut else None
            stop = close(clean, body.end() - 1, '{', '}') if body else None
        if stop and start < at < stop:
            return True
    return False


def _unread_after(clean, arm, mentions):
    later = [at for at in mentions if at >= arm[1]]
    if not later:
        return True
    if re.search(r'\breturn\b[^;{}]*;\s*\Z', clean[arm[0] + 1:arm[1] - 1]):
        return True
    other = re.compile(r'\s*else\s*\{').match(clean, arm[1])
    stop = close(clean, other.end() - 1, '{', '}') if other else None
    return bool(stop) and all(at < stop for at in later)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    decls = locals_for(part)
    if len(decls) < 2:
        return []
    uses = {d['name']: [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(d["name"])}\b', clean[:part.end])
                        if m.start() > part.opening and not d.start() <= m.start() < d.end()] for d in decls}
    arms = _arms(clean, part.opening, part.end)
    found = []
    for late in decls:
        b = late['name']
        if not uses[b]:
            continue
        holding = [arm for arm in arms if all(arm[0] < at < arm[1] for at in uses[b])]
        if not holding:
            continue
        arm = min(holding, key=lambda item: item[1] - item[0])
        first = uses[b][0]
        before = clean[:first].rstrip()
        if before[-1:] not in (';', '{', '}') or not re.match(rf'{re.escape(b)}\s*=(?!=)', clean[first:]):
            continue
        if re.search(rf'\b{re.escape(b)}\b', clean[first + len(b):clean.find(';', first)]) or _in_loop(clean, part.opening, arm[0]):
            continue
        for early in decls:
            a = early['name']
            if a == b or early['type'] != late['type'] or not uses[a]:
                continue
            if any(arm[0] < at < arm[1] for at in uses[a]) or not _unread_after(clean, arm, uses[a]):
                continue
            base = re.sub(r'_\d+$', '', a)
            numbered = base == re.sub(r'_\d+$', '', b) and bool(re.match(r'(?:var|temp)_', base))
            found.append((not numbered, early.start() > late.start(), abs(uses[a][0] - first), a, b, late))
    found.sort(key=lambda item: item[:5])
    out, done = [], set()
    for _, _, _, a, b, late in found:
        if frozenset((a, b)) in done:
            continue
        done.add(frozenset((a, b)))
        line = source.rfind('\n', 0, late.start()) + 1
        start, stop = late.start(), late.end()
        if not source[line:start].strip() and source[stop:stop + 1] == '\n':
            start, stop = line, stop + 1
        edits = [(start, stop, '')] + [(at, at + len(b), a) for at in uses[b]]
        out.append((FAMILY, edit(source, edits)))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
