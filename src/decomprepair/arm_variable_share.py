"""The same role in the two arms of an `if`/`else` written as one variable: counters, and what is derived from them.

m2c names each value it recovers, so two sibling loops (a halfword index table and a byte index table, each its own
counted loop) get a counter apiece, `var_s0` and `var_s0_2`, and the index each derives from it a name apiece. The
original reused one variable for the role in both arms. gcc 2.7.2 hands out the saved registers by
`floor_log2(uses) * uses / live_length`, one pseudo per source variable, so the shared counter has the sum of the uses
and a longer range, and ranks above everything that is private to one arm: on a 851-instruction N64 ray test (KMC GCC
2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) it took `$s0` as in the target, with the mesh pointer, the strength-reduced
pointers and the index after it in the target's order (the two arms' counters and indices shared, their pointers and
reduced pointers left apart; the room section's two counters shared the same way). Merging one pair alone, or all the
pointers as well, made the registers worse (the score went 740 -> 850 for the obj arms, 1160 with everything shared)
and only the room counters on top reached 645, so the family emits every such pair at once as one child, then each
pair alone. The explanation is read from `-dl -dg` dumps, a hypothesis, not from the compiler's source.

A pair is two scalar locals of one declared type, one referenced only inside the `if` arm and the other only inside
the `else` arm, each assigned before it is read in its arm, with the same right-hand side of that first assignment
once the pairs already found are renamed (`0` for a counter, then `counter & 0xFFFF` for its index). The second name
is replaced by the first and its declaration dropped. The judge decides.
"""
import re

from .integer_repair_support import edit, locals_for, view
from .pattern_repairs import close

FAMILY = 'arm_variable_share'
FAMILIES = (FAMILY,)
LIMIT = 6


def _python_arms(clean, part):
    """(start, end) of the then-arm and else-arm bodies of every `if ... { } else { }` in the function."""
    found = []
    for hit in re.finditer(r'\}\s*else\s*\{', clean[part.opening:part.end]):
        end_then = part.opening + hit.start()
        start_else = part.opening + hit.end() - 1
        end_else = close(clean, start_else, '{', '}')
        # the then-arm's opening brace: scan back for the matching '{'
        depth, position = 0, end_then
        start_then = None
        while position > part.opening:
            char = clean[position]
            depth += char == '}'
            depth -= char == '{'
            if depth == 0:
                start_then = position
                break
            position -= 1
        if end_else and start_then is not None:
            found.append(((start_then + 1, end_then), (start_else + 1, end_else)))
    return found


_arms = _python_arms
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _arms(clean, part):
        found = []
        for hit in re.finditer(r'\}\s*else\s*\{', clean[part.opening:part.end]):
            end_then = part.opening + hit.start()
            start_else = part.opening + hit.end() - 1
            end_else = close(clean, start_else, '{', '}')
            start_then = _scan.open_every(clean, end_then, '{', '}', None)
            if start_then is NotImplemented:
                return _python_arms(clean, part)
            if start_then is not None and (end_then <= part.opening or start_then <= part.opening):
                start_then = None
            if end_else and start_then is not None:
                found.append(((start_then + 1, end_then), (start_else + 1, end_else)))
        return found


def _first_assignment(clean, name, span):
    """The text assigned to `name` by its first mention in the span, when that mention is a plain `name = ...;`."""
    mention = re.search(rf'(?<![\w.>]){re.escape(name)}\b', clean[span[0]:span[1]])
    if not mention:
        return None
    at = span[0] + mention.start()
    line = re.match(rf'{re.escape(name)}\s*=(?!=)\s*([^;{{}}]+);', clean[at:span[1]])
    return line[1].strip() if line else None


def _confined(clean, part, decl, span, before=False):
    """Is every mention of the local, its declaration aside, inside the span (or, with `before`, inside it or ahead of it,
    so its value outside is never read after the arm)?"""
    name = decl['name']
    inside = [part.opening + 1 + hit.start() for hit in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[part.opening + 1:part.end])]
    inside = [position for position in inside if not decl.start() <= position < decl.end()]
    return bool(inside) and all(span[0] <= position < span[1] or (before and position < span[0]) for position in inside)


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    decls = {decl['name']: decl for decl in locals_for(part)}
    sites = []
    for then, other in _arms(clean, part):
        merged = {}
        pairs = []
        for _ in range(3):
            progress = False
            for first, a in decls.items():
                if a['name'] in merged or not _confined(clean, part, a, then, before=True):
                    continue
                for second, b in decls.items():
                    if second in merged.values() or second == first or a['type'] != b['type'] or not _confined(clean, part, b, other):
                        continue
                    left, right = _first_assignment(clean, first, then), _first_assignment(clean, second, other)
                    if not left or not right:
                        continue
                    right = re.sub(rf'(?<![\w.>]){re.escape(second)}\b', first, right)
                    for kept, dropped in merged.items():
                        right = re.sub(rf'(?<![\w.>]){re.escape(dropped)}\b', kept, right)
                    # a counter (set to 0) or a plain conversion of one already shared (`counter & 0xFFFF`); data temporaries stay apart
                    if left == right and (left == '0' or any(re.fullmatch(rf'(?:\(\s*\w+\s*\)\s*)?\(?\s*{re.escape(kept)}\s*\)?\s*(?:&\s*0x[0-9A-Fa-f]+)?', left) for kept in merged)):
                        merged[first] = second
                        pairs.append((first, second))
                        progress = True
                        break
            if not progress:
                break
        if pairs:
            sites.append(pairs)
    if not sites:
        return []

    def rewrite(pairs):
        edits = []
        for first, second in pairs:
            decl = decls[second]
            edits.append((decl.start(), decl.end(), ''))
            for hit in re.finditer(rf'(?<![\w.>]){re.escape(second)}\b', clean[decl.end():part.end]):
                edits.append((decl.end() + hit.start(), decl.end() + hit.end(), first))
        return edit(source, edits)

    everything = [pair for site in sites for pair in site]
    found = []
    if len(everything) > 1:
        found.append((FAMILY, rewrite(everything)))
    for pair in everything[:LIMIT]:
        found.append((FAMILY, rewrite([pair])))
    return found
