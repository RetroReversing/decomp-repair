"""A result chosen by a ladder of bit tests, written as the `else if` chain it came from, with the byte it was stored in.

m2c writes a function's `if (a) x = 2; else if (b) x = 3; ...` chain as a nest of defaults: `x = 2; if (!(a)) { x = 3;
if (!(b)) { ... } }`, the last level sometimes inside a `do { } while (0)` scope an earlier search left behind, with the
result `x` an `s32` that a later call takes as its last argument, and a function that returns the constant 0 declared
to return `unsigned long long`. Three edits, found by hand on a 90-point KMC (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32
-O2`) audio-setup function (89 instructions, the three of them taken together reached 0; each alone scored worse):

1. the nest is the `else if` chain, so `x = 2` is made *after* the test instead of before it, where the value shares the
   test's register instead of living across it;
2. `x` is a `u8`, because every value it holds is a small constant: its copy into the call's argument register is then a
   subreg copy with no copy preference, which lets the allocator take `$v0` (the register of the last test's `sltiu`)
   instead of `$a3` (read from global.c's `find_reg` and `set_preference`: a plain copy to a hard register is recorded as
   a *copy* preference and wins, a `subreg` source is not; a hypothesis from the dump, the exact judge decides);
3. the function's `unsigned long long` return becomes `s32` when every `return` returns an integer literal: the 64-bit
   return was clearing `$v1` as well, which the target never does.

The family offers the three as one child first (they pay off only together: the return type alone scored 180 from 90,
the chain and `u8` with the 64-bit return 100), then the chain with the byte, then the chain alone, then the return type
alone. Nothing is offered unless the nest has the exact shape (a constant assigned, then an `if (!(test))` whose block
is the next level), every other use of `x` is one read as a call argument and every assignment to it is a constant."""
import re

from .csource import find
from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'ladder_result_narrow'
FAMILIES = (FAMILY,)
WIDE = r'(?:unsigned\s+long\s+long|signed\s+long\s+long|long\s+long|s64|u64)'
NARROWABLE = ('s32', 'u32', 'int', 'unsigned int', 's16', 'u16', 'short', 'unsigned short')


def _skip(text, at):
    while at < len(text) and text[at].isspace():
        at += 1
    return at


def _statement(clean, at, var):
    """`var = N;` at `at`: (value, end) or None."""
    hit = re.compile(rf'{re.escape(var)}\s*=\s*({NUMBER})\s*;').match(clean, at)
    return (hit[1], hit.end()) if hit else None


def _test(clean, at):
    """`if (!(X)) {` at `at`: (X, position after the `{`, position of that `{`) or None."""
    hit = re.compile(r'if\s*\(').match(clean, at)
    if not hit:
        return None
    opened = hit.end() - 1
    shut = close(clean, opened)
    if not shut:
        return None
    condition = clean[opened + 1:shut - 1].strip()
    if not condition.startswith('!'):
        return None
    positive = condition[1:].strip()
    if positive.startswith('(') and close(positive, 0) == len(positive):
        positive = positive[1:-1].strip()
    brace = _skip(clean, shut)
    if not positive or clean[brace:brace + 1] != '{':
        return None
    return opened + 1 + condition.find(positive), len(positive), brace


def _block(clean, start, end, var):
    """The arms of one level inside clean[start:end] and the value left when none holds: ([(test span, value)], value)."""
    at = _skip(clean, start)
    first = _statement(clean, at, var)
    if not first:
        return None
    value, at = first
    rest = _skip(clean, at)
    if rest >= end:
        return [], value
    scope = re.compile(r'do\s*\{').match(clean, rest)
    inner_end = end
    if scope:
        opened = scope.end() - 1
        shut = close(clean, opened, '{', '}')
        tail = re.compile(r'\s*while\s*\(\s*0\s*\)\s*;').match(clean, shut or 0)
        if not shut or not tail or _skip(clean, tail.end()) < end:
            return None
        rest, inner_end = _skip(clean, opened + 1), shut - 1
    test = _test(clean, rest)
    if not test:
        return None
    where, length, brace = test
    shut = close(clean, brace, '{', '}')
    if not shut or _skip(clean, shut) < inner_end:
        return None
    below = _block(clean, brace + 1, shut - 1, var)
    if not below:
        return None
    return [((where, where + length), value)] + below[0], below[1]


def _ladders(part, var):
    """(start, end, arms, otherwise) of each nest of defaults for `var` in the function body."""
    clean = part.clean
    found = []
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(var)}\s*=\s*{NUMBER}\s*;', clean[part.opening:part.end]):
        start = part.opening + hit.start()
        test = _test(clean, _skip(clean, part.opening + hit.end()))
        if not test:
            continue
        shut = close(clean, test[2], '{', '}')
        if not shut:
            continue
        arms = _block(clean, start, shut, var)
        if arms and len(arms[0]) >= 2:
            found.append((start, shut, *arms))
    return [one for one in found if not any(other[0] < one[0] and one[1] <= other[1] for other in found)]


def _chain(source, indent, var, arms, otherwise):
    lines = [f'{indent}{"else " if at else ""}if ({source[a:b]}) {var} = {value};' for at, ((a, b), value) in enumerate(arms)]
    return '\n'.join(lines + [f'{indent}else {var} = {otherwise};'])


def _return_edit(source, clean, part, name):
    """The edit that declares the function `s32` when it returns only integer literals, else None."""
    head = find(source, name)
    definition = re.search(rf'(?<![\w])({WIDE})(\s+)(?:\w+::)*{re.escape(name)}\s*\(', clean[head[0]:part.opening])
    if not definition:
        return None
    returns = re.findall(r'\breturn\b\s*([^;]*);', part.clean[part.opening:part.end])
    if not returns or any(not re.fullmatch(NUMBER, r.strip()) for r in returns):
        return None
    word = 's32' if re.search(r'\bs32\b', source) else 'int'
    return head[0] + definition.start(1), head[0] + definition.end(1), word


def _only_call_reads(clean, var, opening, end, spans, declared):
    """True when `var` outside its ladder is only read as one call argument, and only assigned constants inside it."""
    reads = 0
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', clean[opening:end]):
        at = opening + hit.start()
        if at == declared or any(a <= at < b for a, b in spans):
            continue
        before, after = clean[:at].rstrip()[-1:], clean[opening + hit.end():end].lstrip()[:1]
        if before not in ',(' or after not in ',)' or re.match(r'\s*=(?!=)', clean[opening + hit.end():]):
            return False
        reads += 1
    return reads > 0


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, opening, end = part.clean, part.opening, part.end
    ret = _return_edit(source, clean, part, name)
    out = []
    names = '|'.join(map(re.escape, NARROWABLE))
    for decl in re.finditer(rf'(?m)^[ \t]*({names})\s+({IDENT})\s*;[ \t]*$', clean[opening:end]):
        kind, var, declared = decl[1], decl[2], opening + decl.start(2)
        found = _ladders(part, var)
        if len(found) != 1:
            continue
        start, stop, arms, otherwise = found[0]
        if not _only_call_reads(clean, var, opening, end, [(start, stop)], declared):
            continue
        values = [int(v.rstrip('uUlL'), 0) for _, v in arms] + [int(otherwise.rstrip('uUlL'), 0)]
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:start])[0]
        chain = (start, stop, _chain(source, indent, var, arms, otherwise).lstrip())
        byte = (opening + decl.start(1), opening + decl.end(1), 'u8' if re.search(r'\b[su](?:8|16|32)\b', source) else 'unsigned char')
        narrow = 0 <= min(values) and max(values) <= 255
        pieces = [([ret] if ret else []) + ([byte] if narrow else []) + [chain], ([byte] if narrow else []) + [chain], [chain]]
        if ret:
            pieces.append([ret])
        for edits in pieces:
            text = edit(source, edits)
            if text != source and (FAMILY, text) not in out:
                out.append((FAMILY, text))
        break
    return out
