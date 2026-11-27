"""A search's result variable, written as the returns it stands for.

m2c keeps the function's return register as a variable: `result = NULL;` ahead of a search, `result = found;` where
the search succeeds, and `return result;` on every way out:

    result = NULL;                                     ...
    ...                                                if (hit) {
    if (hit) {                                             ...
        result = cur;                          ->          if (other) { return cur; }
        ...                                                return cur;
        if (other) { return cur; }                     }
        return result;                                 ...
    }                                                  return NULL;
    ...
    return result;

The rewrite is made only when it keeps the meaning: the variable holds NULL (or 0) except after its one other
assignment, and the block holding that assignment always leaves through a return. The variable's own pseudo costs a
register and decides which saved register the pointers beside it take.

An N64 pool search (SN GCC 2.8.1, `-G0 -mips3 -O2`, 147 instructions): 1730 -> 1520 on the way to 0.
"""
import re

from .goto_structure_repairs import blocks, parse
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'found_value_return'
FAMILIES = (FAMILY,)
EMPTY = r'(?:NULL|0|\(\(void\s*\*\)\s*0\))'


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, body, shift = part.clean, part.body, part.opening + 1
    try:
        top = parse(clean, part.opening + 1, close(clean, part.opening, '{', '}') - 1)
    except ValueError:
        return []
    result = []
    for declaration in re.finditer(rf'(?:^|(?<=[;{{}}]))\s*{IDENT}\s*\**\s*({IDENT})\s*;', body):
        var = declaration[1]
        writes = list(re.finditer(rf'(?<![\w.>]){var}\s*=(?!=)\s*([^;]+);', body))
        empty = [w for w in writes if re.fullmatch(EMPTY, w[1].strip())]
        found = [w for w in writes if w not in empty]
        if len(found) != 1 or not empty:
            continue
        value = re.fullmatch(rf'(?:\(\s*void\s*\*\s*\)\s*)?({IDENT})', found[0][1].strip())
        if not value:
            continue
        returns = list(re.finditer(rf'\breturn\s+{var}\s*;', body))
        # every other mention of the variable must be one of these
        known = [(declaration.start(1), declaration.end())] + [w.span() for w in writes] + [r.span() for r in returns]
        if not returns or any(not any(a <= m.start() < b for a, b in known)
                              for m in re.finditer(rf'(?<![\w.>]){var}\b', body)):
            continue
        at = shift + found[0].start()
        holder = None
        for stmts in blocks(top):
            index = next((i for i, s in enumerate(stmts) if s.start <= at < s.end and s.kind == 'simple'), None)
            if index is not None:
                holder = stmts[index:]
        if not holder:
            continue
        end = holder[-1].end
        rest = clean[at:end]
        # (a global could be changed by a call: only the function's own local or parameter holds still)
        head = clean[:part.opening]
        local = re.search(rf'[\w*]\s*\b{value[1]}\s*[,)]', head[head.rfind(name):]) or re.search(
            rf'(?:^|(?<=[;{{}}]))\s*{IDENT}\s*\**\s*{value[1]}\s*;', body)
        if (not local or any(at <= shift + w.start() < end for w in empty)
                or not clean[holder[-1].start:end].startswith('return')
                or re.search(r'\b(?:goto|break|continue|case|default)\b|^\s*\w+\s*:(?!:)', rest, re.M)
                # (the value must not change between the assignment and a return of it)
                or re.search(rf'(?<![\w.>]){value[1]}\s*(?:[+\-*/&|^]?=(?!=)|\+\+|--)', rest)):
            continue
        edits = []
        for w in [*writes, declaration]:
            start, stop = (w.start(1), w.end()) if w is declaration else w.span()
            if w is declaration:
                start = w.start()
                start += len(body[start:w.start(1)]) - len(body[start:w.start(1)].lstrip())
            line = body.rfind('\n', 0, start) + 1
            newline = body.find('\n', stop)
            if not body[line:start].strip() and newline >= 0 and not body[stop:newline].strip():
                start, stop = line, newline + 1
            edits.append((shift + start, shift + stop, ''))
        for r in returns:
            inside = at <= shift + r.start() < end
            edits.append((shift + r.start(), shift + r.end(),
                          f'return {found[0][1].strip()};' if inside else 'return NULL;' if 'NULL' in source
                          else 'return 0;'))
        result.append((FAMILY, edit(source, edits)))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
