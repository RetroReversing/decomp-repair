"""A byte clamp written as one conditional expression into a byte local, stored and re-read from that local.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) scroll-window update that stood at 3135: a wide `s32` local
held `total - edge`, was clamped to 0..255 by an `if` / `else if` chain, was stored into a byte field and was read
back as `(u8) local` by a later compare. The target has the arms as separate registers (`move $a0,$zero`, `addiu
$a0,$zero,0xff`, `subu $a0,$a2,$a1` in a branch delay slot), the stored byte and the later `andi` all on one register,
and no stack slot for the clamped value. Writing the clamp as the conditional expression it came from, into a `u8` local
that the store and the later compare read, gave the 8-byte frame hole, the `slti` / `bltz` pair and the raw
`subu $a0,$a2,$a1` of the third arm in one step (3135 -> 2505, the largest single step of that match).

clamp_narrow_store
    `t = E; if (t < 0) t = 0; else if (t >= 256) t = 255; dst = t;` becomes `n = E < 0 ? 0 : E >= 256 ? 255 : E;
    dst = n;` with a new `u8` local `n`, and every later `(u8) t` read of the old local reads `n`. The expression is
    repeated, so the family offers it only for an expression with no call and no side effect; the byte store of the
    third arm then narrows the subtraction itself. Hypothesis from the match, not from the compiler source: the narrow
    destination lets cse and combine narrow the arm's value, where the wide local keeps a full-width register.

A wide local that is read later in any other way (not as `(u8) t`) is left alone, so the child is the same program.
The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .integer_repair_support import IDENT, INTEGER, edit, view
from .pattern_repairs import close

FAMILY = 'clamp_narrow_store'
FAMILIES = (FAMILY,)
LIMIT = 4
_WIDE = {'s32', 'u32', 'int', 'unsigned', 'unsigned int', 'signed int', 's16', 'u16', 'short', 'unsigned short'}
_BLOCK = re.compile(
    rf'(?P<head>(?P<t>{IDENT})\s*=\s*(?P<expr>[^;{{}}=][^;{{}}]*?)\s*;)\s*'
    rf'if\s*\(\s*(?P=t)\s*<\s*0\s*\)\s*(?:\{{\s*)?(?P=t)\s*=\s*0\s*;\s*(?:\}}\s*)?'
    rf'else\s+if\s*\(\s*(?P=t)\s*(?:>=\s*256|>\s*255)\s*\)\s*(?:\{{\s*)?(?P=t)\s*=\s*255\s*;\s*(?:\}}\s*)?'
    rf'(?P<store>(?P<dst>[^;={{}}\n]+?)\s*=\s*(?P=t)\s*;)')
_CAST = r'\(\s*(?:u8|unsigned\s+char)\s*\)\s*'
_WRITE = r'\s*=(?!=)'


def _declaration(part, name):
    """(match, normalised type) of a plain `type name;` / `type name = ...;` declaration of `name`, else None."""
    found = re.search(rf'\b(?P<type>{INTEGER})\s+(?:{IDENT}\s*,\s*)*{re.escape(name)}\b(?:\s*=[^;]*)?(?:\s*,[^;]*)?;',
                      part.clean[part.opening + 1:part.end])
    if not found:
        return None
    return found, re.sub(r'\s+', ' ', found['type'])


def _names(text, name):
    """The occurrences of the local `name`, not the members that happen to be called that."""
    return [m for m in re.finditer(rf'\b{re.escape(name)}\b', text) if not re.search(r'(?:->|\.)\s*$', text[:m.start()])]


def _fresh(part):
    taken = set(re.findall(IDENT, part.clean[part.opening:part.end]))
    for candidate in ('clamped', 'clamped_byte', 'byte_clamp'):
        if candidate not in taken:
            return candidate
    return None


def _operand(expr):
    """The expression as a comparison operand: bare when it only adds, subtracts or multiplies names and numbers."""
    expr = expr.strip()
    return expr if re.fullmatch(r'[\w.>\s+*-]+', expr) else f'({expr})'


def _children(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.body):
        return []
    result = []
    start = part.opening + 1
    for hit in _BLOCK.finditer(part.clean, start, part.end):
        t, expr, dst = hit['t'], hit['expr'].strip(), hit['dst'].strip()
        declared = _declaration(part, t)
        if not declared or declared[1] not in _WIDE or '==' in dst or re.search(r'[<>!]=?', dst.replace('->', '')):
            continue
        if _names(expr, t) or re.search(IDENT + r'\s*\(|\+\+|--|[^=!<>]=[^=]', expr):
            continue
        fresh = _fresh(part)
        if not fresh:
            continue
        before = part.clean[start:hit.start()]
        after = part.clean[hit.end():part.end]
        # the wide local is not read before the clamp, and after it only as `(u8) t` or as a write target
        span = _declaration_span(part, declared[0])
        if any(not re.match(_WRITE, before[m.end():]) for m in _names(before, t) if start + m.start() not in span):
            continue
        bad = False
        casts = []
        writes = []
        for m in _names(after, t):
            prefix = after[:m.start()]
            at = hit.end() + m.start()
            cast = re.search(rf'{_CAST}$', prefix)
            if cast and not re.match(r'\s*(?:\.|->|\[)', after[m.end():]):
                casts.append((hit.end() + cast.start(), hit.end() + m.end()))
            elif re.match(_WRITE, after[m.end():]) and not re.search(r'(?:\.|->)\s*$', prefix):
                writes.append(_enclosing(part.clean, at, part.opening, part.end))
            elif not any(a <= at < b for a, b in writes):
                bad = True
                break
        if bad:
            continue
        operand = _operand(expr)
        body = (f'{fresh} = {operand} < 0 ? 0 : {operand} >= 256 ? 255 : {operand};\n'
                f'{_indent(part.source, hit.start())}{dst} = {fresh};')
        edits = [(hit.start(), hit.end(), body)]
        edits += [(a, b, fresh) for a, b in casts]
        end = start + declared[0].end()
        indent = _indent(part.source, start + declared[0].start())
        edits.append((end, end, f'\n{indent}u8 {fresh};'))
        result.append((FAMILY, edit(source, edits)))
    return result[:LIMIT]


def _enclosing(text, position, low, high):
    """(start, end) of the innermost `{ }` around `position`, or the whole function body."""
    stack = []
    for m in re.finditer(r'[{}]', text[low:position]):
        if m[0] == '{':
            stack.append(low + m.start())
        elif stack:
            stack.pop()
    if not stack:
        return low, high
    return stack[-1], close(text, stack[-1], '{', '}') or high


def _declaration_span(part, match):
    base = part.opening + 1
    return range(base + match.start(), base + match.end())


def _indent(source, position):
    line = source.rfind('\n', 0, position) + 1
    return re.match(r'[ \t]*', source[line:position])[0]


def variants(source, name):
    return _children(source, name)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
