"""The locals m2c names for a function's first loads, written where they are used.

m2c names every value the first statements load, then reuses those names later in the function:

    stateDest = *(void **)(arg0 + 0x68);
    temp_a0 = stateDest;
    temp_s1 = (*(s8 *)(temp_a0 + 0xE)) * 0xE8;
    var_s4 = (*(s8 *)(temp_a0 + 0x10)) * 0xE8;
    switch (...) { case 0: temp_a0 = *(void **)(arg0 + 0x68); ... }

GCC 2.7.2 only hands a pseudo that lives in one basic block to its local allocator, which allocates before the global
one and so gives it the low argument registers; a *named* variable (`reg/v` in its dump) that the later arms assign
again is a global pseudo, allocated afterwards in what is left. The target's `lw $a0, 0x68($s3)` / `lui $a1` pair
(the pointer first, the table base after it) came out reversed, and the argument move for `$a1` then had to wait for
the load: the function's entry block was 90 points off until the pointer was written out at both of its uses
(1245 -> 1140), after which the entry matched except for the scheduler's statement order.

Offered for the straight-line statements at the top of the function (assignments of a local from a pure memory
expression, no calls or stores): a local whose first mention after them is an assignment (so the value it holds here is
dead after the prelude) is replaced by its expression at each use, and its own assignment dropped. One variant per such
local used twice or more, and one that does every such local, following the copies m2c chains (`temp_a0 = stateDest;`).
"""
import re

from .csource import _blank, find
from .local_inline_repairs import _plain
from .pattern_repairs import close

FAMILY = 'prelude_pointer_inline'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
LIMIT = 6


def _statements(clean, start, end):
    """(begin, stop) of each `;`-ended statement from `start`, by nesting depth (blank text only)."""
    depth, begin = 0, start
    for at in range(start, end):
        ch = clean[at]
        if ch in '({[':
            depth += 1
        elif ch in ')}]':
            depth -= 1
            if depth < 0:
                return
        elif ch == ';' and depth == 0:
            yield begin, at + 1
            begin = at + 1


def _mentions(text, name):
    return [m for m in re.finditer(r'(?<![\w.>])' + re.escape(name) + r'\b', text)]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    text = source[span[0]:span[1]]
    clean = _blank(text)
    sig_end = clean.find('{')
    if sig_end < 0:
        return []
    close_at = close(clean, sig_end, '{', '}')
    if not close_at:
        return []
    prelude = []  # (begin, stop, local, expression)
    declared = set(re.findall(r'(?m)^[ \t]*(?:register\s+)?[A-Za-z_][\w \t*]*?[ \t*](' + IDENT + r')[ \t]*;', clean[:close_at]))
    end_of_prelude = sig_end + 1
    for begin, stop in _statements(clean, sig_end + 1, close_at):
        statement = clean[begin:stop].strip()
        if not re.search(r'[=()]', statement) and not re.match(r'(?:return|goto|break|continue|case|default)\b', statement):
            end_of_prelude = stop
            continue
        hit = re.fullmatch(r'(?P<local>' + IDENT + r')\s*=(?!=)\s*(?P<rhs>[^;{}]*);', statement)
        if not hit or hit['local'] not in declared or not _plain(hit['rhs']):
            break
        at = begin + clean[begin:stop].index(hit['local'])
        rhs_at = clean.index('=', at) + 1
        prelude.append((begin, stop, hit['local'], rhs_at, stop - 1))
        end_of_prelude = stop
    if not prelude:
        return []
    rest = clean[end_of_prelude:close_at]
    names = [p[2] for p in prelude]
    if len(set(names)) != len(names):
        names = [n for n in names if names.count(n) == 1]

    def dead_after(local):
        """The value the prelude gives `local` is never read after it."""
        found = _mentions(rest, local)
        seen_write = False
        for m in found:
            if re.match(r'\s*=(?!=)', rest[m.end():]):
                seen_write = True
            elif not seen_write:
                return False
        return True

    candidates = [p for p in prelude if p[2] in names and dead_after(p[2])]
    if not candidates:
        return []

    def inline(chosen):
        """The function with `chosen` locals (their assignment tuples) replaced by their expressions."""
        locals_ = {p[2]: p for p in chosen}
        # substitute from the last statement of the prelude backwards so offsets in `text` stay valid
        pieces, drop = [], set()
        replaced = {}
        for begin, stop, local, rhs_at, rhs_end in prelude:
            expr = text[rhs_at:rhs_end].strip()
            # expressions of chosen locals that this one uses are written out first
            for other, tup in replaced.items():
                expr = re.sub(r'(?<![\w.>])' + re.escape(other) + r'\b', '(' + tup + ')', expr)
            if local in locals_:
                replaced[local] = expr
                drop.add((begin, stop))
            pieces.append((begin, stop, local, expr))
        out, last = [], 0
        for begin, stop, local, expr in pieces:
            if (begin, stop) in drop:
                out.append(text[last:begin])
                # keep the line break structure: the statement disappears with its own line if it has one
                last = stop
                if text[last:last + 1] == '\n':
                    last += 1
                continue
            statement = text[begin:stop]
            for other, tup in replaced.items():
                if other == local:
                    continue
                statement = re.sub(r'(?<![\w.>])' + re.escape(other) + r'\b', '(' + tup + ')', statement)
            out.append(text[last:begin])
            out.append(statement)
            last = stop
        out.append(text[last:])
        return ''.join(out)

    result = []
    used_by = {}
    for begin, stop, local, *_ in candidates:
        later = clean[stop:end_of_prelude]
        used_by[local] = len(_mentions(later, local))
    for tup in candidates:
        if used_by[tup[2]] >= 2:
            result.append((FAMILY, source[:span[0]] + inline([tup]) + source[span[1]:]))
    everything = [tup for tup in candidates if used_by[tup[2]] >= 1]
    if len(everything) > 1:
        result.append((FAMILY, source[:span[0]] + inline(everything) + source[span[1]:]))
    seen, unique = set(), []
    for family, fixed in result:
        if fixed != source and fixed not in seen:
            seen.add(fixed)
            unique.append((family, fixed))
    return unique[:LIMIT]
