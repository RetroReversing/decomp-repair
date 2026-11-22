"""A pointer assigned on each arm of an if/else and stored through once after the join, split per arm.

m2c merges the two arms' pointers into one variable and stores the shared result after the join:

    if (c) { p = a; v = E1; } else { p = b; v = E2; }
    *(f32 *)((char *)p + 0x14) = v;

That variable is one global pseudo, and GCC 2.7.2's global allocator gives it the register of any address that dies in
a load that sets it (`-dl -dg` printed `95 preferences: 3 16`), so it took `$v1` where the game had `$v0`. The game's C
kept a pointer per arm, each used only there, with the store written on each arm; cross-jumping merged the identical
tail, so the output still has one store after a `j`. Both pointers are then block-local and local-alloc gives them the
first free register. An N64 function was 275 with the join and 245 with the split (and exact with later edits).

Offered when a store `... P ... = V;` follows an `if/else`, P is a declared pointer local assigned in both arms, V is
a declared local assigned at the top level of both arms, and neither is read after the store. The store moves to the
end of each arm in place of V's last assignment, and P is renamed per arm.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'arm_pointer_split'
FAMILIES = (FAMILY,)


def _open_of(clean, closing):
    """Index of the `{` matching the `}` at `closing`."""
    depth = 0
    for i in range(closing, -1, -1):
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            depth -= 1
            if depth == 0:
                return i
    return -1


def _top_assignments(clean, lo, hi, name):
    """Spans of `name = ...;` statements at the arm's own depth, between lo and hi."""
    out, depth, i = [], 0, lo
    pattern = re.compile(rf'(?<![\w.>])({re.escape(name)}) = ')
    while i < hi:
        ch = clean[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        elif depth == 0:
            m = pattern.match(clean, i)
            if m and (i == lo or not re.match(r'[\w.>]', clean[i - 1])):
                end = clean.find(';', i)
                if 0 <= end < hi:
                    out.append((i, end + 1))
                    i = end
        i += 1
    return out


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    pointers = {m[2]: re.sub(r'\s*(\*+)$', r' \1', m[1].strip()) for m in re.finditer(
        r'^[ \t]*((?:struct\s+)?[A-Za-z_]\w*(?:\s+volatile)?\s*\*+)\s*(\w+);', clean[opening:end], re.M)}
    scalars = {m[2] for m in re.finditer(r'^[ \t]*([A-Za-z_]\w*)\s+(\w+);', clean[opening:end], re.M)}
    for store in re.finditer(r'(?<=\})[ \t]*\n([ \t]*)([^=;{}\n]+?) = (\w+);[ \t]*$', clean[:end], re.M):
        if store.start() < opening:
            continue
        lhs, value = store[2], store[3]
        used = [p for p in pointers if re.search(rf'\b{p}\b', lhs)]
        if len(used) != 1 or value not in scalars:
            continue
        pointer = used[0]
        if re.search(rf'\b(?:{pointer}|{value})\b', clean[store.end():end]):
            continue
        at = store.start()
        arm_b_close = clean.rfind('}', 0, at)
        arm_b_open = _open_of(clean, arm_b_close)
        if arm_b_open < 0 or not re.search(r'\belse\s*$', clean[:arm_b_open]):
            continue
        else_at = clean.rfind('else', 0, arm_b_open)
        arm_a_close = clean.rfind('}', 0, else_at)
        arm_a_open = _open_of(clean, arm_a_close)
        if arm_a_open < 0 or not re.search(r'\)\s*$', clean[:arm_a_open]):
            continue
        arms = [(arm_a_open + 1, arm_a_close), (arm_b_open + 1, arm_b_close)]
        edits, ok = [], True
        for number, (lo, hi) in enumerate(arms, 1):
            writes = _top_assignments(clean, lo, hi, value)
            if not writes or not re.search(rf'(?<![\w.>]){pointer} = ', clean[lo:hi]):
                ok = False
                break
            last = writes[-1]
            if re.search(rf'\b{value}\b', clean[last[1]:hi]):
                ok = False  # the value is touched again after its last write: the store can't move above that
                break
            local = f'{pointer}_arm{number}'
            renamed = re.sub(rf'\b{pointer}\b', local, lhs)
            rhs = source[last[0]:last[1]].split(' = ', 1)[1].rstrip(';')
            arm_text = source[lo:hi]
            arm_text = (arm_text[:last[0] - lo] + f'{renamed} = {rhs};' + arm_text[last[1] - lo:])
            edits.append((lo, hi, re.sub(rf'\b{pointer}\b', local, arm_text)))
        if not ok:
            continue
        out = source[:store.start()] + source[store.end():]
        # the removed store leaves the blank line the join had; drop the line break it started with
        for lo, hi, text in sorted(edits, reverse=True):
            out = out[:lo] + text + out[hi:]
        decl = re.search(rf'^[^\n]*\*\s*{pointer};[^\n]*$', out[opening:], re.M)
        if not decl:
            continue
        at_decl = opening + decl.end()
        kind = pointers[pointer]
        out = out[:at_decl] + ''.join(f'\n  {kind}{pointer}_arm{n};' for n in (1, 2)) + out[at_decl:]
        return [(FAMILY, out)]
    return []
