"""A local's last use, shifted, written as the shift in place: `t[(x >> 10) & m]` becomes `t[(x >>= 10) & m]`.

A table lookup reads a peeked bit window twice: `x & 0x3FF` for the first level and `(x >> 10) & mask` for the second.
When the second read is the window's last use, KMC GCC 2.7.2 can give the shift's result the register the window dies
in, or a fresh one, and which one depends on how the source names the result: spelled `(x >> 10)` the result is a new
temporary that local-alloc places by its own priority; spelled `(x >>= 10)` it is the window's own pseudo, so the
shift happens in that register (the target's `srl $v1,$v1,0xa` beside `srl $a0,$t1,7`) and the temporaries around it
fall where the target has them. On a 681-instruction bit-stream decoder (two canonical-code lookups) the first
lookup's shift in place was 1500 -> 1465 (and 1665 -> 1640 from another start); both lookups at once was worse, so
each site is offered alone as well as together.

Rewrites `(V >> K)` or `(V << K)` (K a literal), where `V` is a plain integer local whose next mention after the
statement, if any, is a plain assignment `V = ...` (so the shifted value is never read), and, when the statement is in a loop,
the loop body's first mention of `V` is such an assignment too. It declines for parameters, volatiles, locals whose
address is taken, and names a function-like macro's body mentions (a macro can read `V` without naming it here).
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'last_use_shift_in_place'
FAMILIES = (FAMILY,)
LIMIT = 6

_SHIFT = re.compile(r'\(\s*([A-Za-z_]\w*)\s*(>>|<<)\s*(\d+|0[xX][0-9a-fA-F]+)\s*\)')
_STATEMENT = re.compile(r'(?m)^([ \t]*)([^;{}\n][^;{}]*;)')
_LOOP = re.compile(r'\b(?:for|while)\s*\(|\bdo\s*\{')


def _python_close(clean, at, left='{', right='}'):
    depth = 0
    for i in range(at, len(clean)):
        depth += (clean[i] == left) - (clean[i] == right)
        if depth == 0:
            return i
    return None


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(clean, at, left='{', right='}'):
        found = _scan.close_every(clean, at, left, right, False, None)
        return _python_close(clean, at, left, right) if found is NotImplemented else found


def _loops(clean, lo, hi):
    """(start of body, end of body) of every loop in the function."""
    out = []
    for loop in _LOOP.finditer(clean, lo, hi):
        at = loop.end() - 1
        if clean[at] == '(':
            shut = _close(clean, at, '(', ')')
            if shut is None:
                continue
            brace = re.compile(r'\s*\{').match(clean, shut + 1)
            if not brace:
                continue  # `while (..);` of a do-loop, or a body without braces
            at = brace.end() - 1
        end = _close(clean, at)
        if end is not None:
            out.append((at, end))
    return out


def _first_mention_is_assignment(text, var):
    mention = re.search(rf'\b{var}\b', text)
    return bool(mention) and re.match(rf'{var}\s*=[^=]', text[mention.start():]) is not None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(r'\bvolatile\b', clean[lo:hi]):
        return []
    macro_names = set()
    for body in re.findall(r'(?m)^\s*#\s*define\s+\w+\(([^\n]*(?:\\\n[^\n]*)*)', source):
        macro_names |= set(re.findall(r'[A-Za-z_]\w*', body))
    loops = _loops(clean, lo, hi)
    sites = []
    for statement in _STATEMENT.finditer(clean, lo, hi):
        for shift in _SHIFT.finditer(statement.group(2)):
            var = shift.group(1)
            if var in macro_names or re.search(rf'&\s*{var}\b', clean[lo:hi]):
                continue
            if not re.search(rf'(?m)^[ \t]*(?:unsigned\s+\w+|s32|u32|int|long|u16|s16|u8|s8)\s+{var}\s*;', clean[lo:hi]):
                continue
            rest = statement.group(2)[shift.end():]
            if re.search(rf'\b{var}\b', rest) or re.search(rf'\b{var}\b', statement.group(2)[:shift.start()]):
                continue  # read again (or set) in the same statement
            later = clean[statement.end():hi]
            if re.search(rf'\b{var}\b', later) and not _first_mention_is_assignment(later, var):
                continue
            inside = [body for body in loops if body[0] < statement.start() < body[1]]
            if any(not _first_mention_is_assignment(clean[body[0]:body[1]], var) for body in inside):
                continue
            at = statement.start(2) + shift.start()
            sites.append((at, at + len(shift.group(0)), f'({var} {shift.group(2)}= {shift.group(3)})'))
    out = [(FAMILY, edit(source, [site])) for site in sites[:LIMIT]]
    if 1 < len(sites) <= LIMIT:
        out.append((FAMILY, edit(source, sites)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
