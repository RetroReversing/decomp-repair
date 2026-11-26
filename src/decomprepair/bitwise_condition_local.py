"""A `(a) & (b)` condition whose narrowed operand is a local of its own, and whose flag is tested second.

    if ((((s16) temp_v0) < 0xA0) & (D_800FFC70 != 2)) { *p = 0xA0; var_a1 = 0xA0; }  if (var_a1 == 0x1E0) ...
    var_a1 = (s16) temp_v0;
    if ((D_800FFC70 != 2) & (var_a1 < 0xA0)) { *p = 0xA0; var_a1 = 0xA0; }            if (var_a1 == 0x1E0) ...

m2c writes the phi variable it found (`var_a1`, set to 0xA0 in the body and read by the test after it) as set on ONE
path only, and tests the narrowed value inline: the value the later test reads is undefined on the other path, and the
compare is made on a cast of the sign-extended halfword in a temporary. The game kept the narrowed value in the local
on every path, set before the test, and tested the flag first: a compare on the local, then the flag, joined by `&`
because the target does not branch between the tests. A N64 counter function (KMC GCC 2.7.2, 18 instructions) stood at
225 with the cast inline and the flag second; the local alone is 70, the flag first alone 295, both together exact (0):
neither step improves alone, so a search that keeps only single improvements never sees the pair.

Children, for an `if` whose condition is two operands joined by a single `&`, one of them a comparison of a narrowing
cast of a name (`((s16) x) < K`, `(u8) x`):
- `bitwise_condition_local`: the cast value is set in a local on the line above the `if` and the condition reads the
  local, with the flag first (the combined child) and in the original order. The local is the function's own scalar
  that the body of the `if` assigns (the phi variable m2c left half-set), else a new `s32 cond_<name>`.
- `bitwise_condition_swap`: only the two operands exchanged (it scores worse alone; other repairs build on it).
A condition with a call, an assignment or an increment in it is left alone, and so is a function with `volatile`,
`asm` or a preprocessor line. Hypothesis, not confirmed in the compiler source: the front end orders the two compares by
the order of the operands, and the local is the value the join after the `if` keeps live. The exact judge decides."""
import re

from .integer_repair_support import IDENT, INTEGER, edit, view
from .store_run_order import _insert_declaration

FAMILY_LOCAL = 'bitwise_condition_local'
FAMILY_SWAP = 'bitwise_condition_swap'
FAMILIES = (FAMILY_LOCAL, FAMILY_SWAP)
_CAST = re.compile(rf'\(\s*\(\s*(?:s|u)(?:8|16)\s*\)\s*{IDENT}\s*\)|\(\s*(?:s|u)(?:8|16)\s*\)\s*{IDENT}')
_EFFECT = re.compile(rf'\+\+|--|(?<![=!<>])=(?!=)|{IDENT}\s*\(')


def _close(text, at):
    """Index of the `)` matching the `(` at `at`, or None."""
    depth = 0
    for i in range(at, len(text)):
        depth += {'(': 1, ')': -1}.get(text[i], 0)
        if depth == 0:
            return i
    return None


def _single_and(cond):
    """The offset of the one top-level `&` of `cond`, or None."""
    depth, found = 0, []
    for i, ch in enumerate(cond):
        depth += {'(': 1, ')': -1}.get(ch, 0)
        if ch == '&' and depth == 0:
            if cond[i - 1:i] == '&' or cond[i + 1:i + 2] == '&':
                return None
            found.append(i)
    return found[0] if len(found) == 1 else None


def _block_end(clean, start):
    """After the statement or `{ ... }` block that follows the condition at `start`."""
    rest = clean[start:]
    lead = len(rest) - len(rest.lstrip())
    if not rest.lstrip().startswith('{'):
        return None
    depth = 0
    for i in range(start + lead, len(clean)):
        depth += {'{': 1, '}': -1}.get(clean[i], 0)
        if depth == 0:
            return start + lead, i
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    if re.search(r'\b(?:volatile|asm|__asm__)\b|^\s*#', clean[part.opening:part.end], re.M):
        return []
    declared = {m['name'] for m in re.finditer(rf'(?m)^[ \t]*(?:{INTEGER})\s+(?P<name>{IDENT})\s*;', clean[part.opening:part.end])}
    used = set(re.findall(IDENT, clean[part.opening:part.end]))
    out = []
    for hit in re.finditer(r'\bif\s*\(', clean[part.opening:part.end]):
        open_at = part.opening + hit.end() - 1
        stop = _close(clean, open_at)
        if stop is None:
            continue
        cond = clean[open_at + 1:stop]
        amp = _single_and(cond)
        if amp is None or _EFFECT.search(re.sub(_CAST, '', cond)):
            continue
        left, right = cond[:amp], cond[amp + 1:]
        base = open_at + 1
        swapped = f'{right.strip()} & {left.strip()}'
        out.append((FAMILY_SWAP, edit(source, [(base, stop, swapped)])))
        line = source.rfind('\n', 0, hit.start() + part.opening) + 1
        lead = source[line:part.opening + hit.start()]
        if lead.strip() or clean[:line].rstrip()[-1:] not in (';', '{', '}'):
            continue
        block = _block_end(clean, stop + 1)
        assigned = []
        if block:
            assigned = [n for n in re.findall(rf'(?<![\w.>])({IDENT})\s*=(?!=)', clean[block[0]:block[1]]) if n in declared]
        for text, offset in ((left, 0), (right, amp + 1)):
            cast = _CAST.search(text)
            if not cast:
                continue
            expression = cast.group(0)
            value = expression[1:-1].strip() if re.match(r'\(\s*\(', expression) else expression
            local = assigned[0] if assigned else 'cond_' + re.findall(IDENT, value)[-1]
            if not assigned and local in used:
                continue
            edited = cond[:offset + cast.start()] + local + cond[offset + cast.end():]
            insert = (line, line, f'{lead}{local} = {value};\n')
            children = [edit(source, [(base, stop, edited), insert])]
            halves = _single_and(edited)
            if halves is not None:  # the flag first: the operands exchanged
                children.insert(0, edit(source, [(base, stop, f'{edited[halves + 1:].strip()} & {edited[:halves].strip()}'),
                                                 insert]))
            for child in children:
                moved = view(child, name)
                if moved:
                    out.append((FAMILY_LOCAL, child if assigned else _insert_declaration(child, moved, f's32 {local};')))
    return list(dict.fromkeys(out))[:12]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
