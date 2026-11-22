"""join_tail_arm_inline: a join's store copied into each arm, with the arm's own temporaries folded into it.

m2c reads a three-way table choice the way the machine code reads it: each arm sets the value and the byte it will
merge, and one store after the join writes `(value & ~0xFF) | byte`:

    if (i != 0)        { row = p->cur; value = table[i];  low = g->state_byte; }
    else if (flag & 1) { row = p->cur; value = D_a;       low = row->type; }
    else               {               value = D_b;       low = row->type; }
    row->param = (value & ~0xFF) | low;

KMC GCC 2.7.2 (`-O2`) keeps those values in pseudos set in several blocks, which the global pass allocates after
every local one, with the `~0xFF` mask a local pseudo of the join taking the register the value wanted: a 180
instruction menu function sat at 110 with register rows only. The game stored in each arm. The value, the byte and
the mask are then local pseudos of one block each, allocated first, and cross-jumping after allocation merges the
identical tails again: 110 -> 60 for the first join, 20 with the second (and 0 with `local_width_group`).

What `join_tail_arm_split` (the copy with every arm-private name renamed) cannot reach: its private locals are user
variables per arm and took registers of their own, so the tails no longer matched and the score went to 1065. Here the
copy folds a temporary into the tail only when it is private to the arm (control-flow liveness, `local_flow`, the test
`arm_private_rename` uses), set once there by a pure assignment, read once, by the copy, and nothing between them
writes what it reads or stores to memory. Names that stay (the row pointer the arm also reads) stay shared.

The arms are the leaves of the `if`/`else` (an `else { if ... else ... }` and an `else if` chain too); an arm that ends
in a jump is left alone. One child per site. Hypothesis: the mechanism above (local-alloc runs before the global pass)
is read from local-alloc.c and global.c and confirmed by the match, not by the compiler's own documentation."""
import re

from .csource import _blank
from .join_tail_arm_split_repairs import _blocks, _body, _cut, _end, _falls_out, _items, _plain, _private_regions, _skip
from .pattern_repairs import close

FAMILY = 'join_tail_arm_inline'
FAMILIES = (FAMILY,)
LIMIT = 6

IDENT = r'[A-Za-z_]\w*'
_ASSIGN = re.compile(r'(?P<lhs>[^;=]+?)\s*=(?!=)\s*(?P<rhs>[^;]+?)\s*;', re.S)
_IMPURE = re.compile(rf'\b(?!sizeof\b){IDENT}\s*\(|\+\+|--')
_EQUALS = re.compile(r'(?<![=!<>])=(?!=)')


def _leaves(clean, start, end):
    """Interiors (after `{`, before `}`) of the arms of the `if`/`else` at [start, end) that nothing nests below."""
    if not re.match(r'if\b', clean[start:end]):
        return None
    stop = close(clean, clean.find('(', start))
    then = _skip(clean, stop, end) if stop else end
    then_end = _end(clean, then, end) if then < end else None
    other = _skip(clean, then_end, end) if then_end else end
    if not then_end or not re.match(r'else\b', clean[other:end]):
        return None
    follow = _skip(clean, other + 4, end)
    found = []
    for first, last in ((then, then_end), (follow, end)):
        if clean[first] == '{':
            lo, hi = first + 1, last - 1
            items = _items(clean, lo, hi)
            if items is None:
                return None
            inner = _leaves(clean, *items[-1]) if items else None
            found += inner if inner else [(lo, hi)]
        elif re.match(r'if\b', clean[first:last]):
            inner = _leaves(clean, first, last)
            if inner is None:
                return None
            found += inner
        else:
            return None
    return found


def _apply(text, edits):
    for start, stop, replacement in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        text = text[:start] + replacement + text[stop:]
    return text


def _tail_copies(source, name):
    """[(text, tail, names)]: `source` with the statement after an `if`/`else` copied to the end of each leaf arm that
    falls out (the original cut), the copied statement, and the names its right-hand side reads."""
    part, end, clean = _body(source, name)
    blocks = _blocks(clean, part.opening + 1, end - 1) if part else None
    out = []
    for lo, hi, items in blocks or []:
        for k in range(len(items) - 1):
            first, second = items[k], items[k + 1]
            if not re.match(r'if\b', clean[first[0]:first[1]]) or not _plain(clean, *second):
                continue
            tail = source[second[0]:second[1]].strip()
            assign = _ASSIGN.fullmatch(tail)
            leaves = _leaves(clean, *first)
            falling = [leaf for leaf in leaves or [] if _falls_out(clean, *leaf)]
            if not assign or len(falling) < 2:
                continue
            edits = [_cut(source, *second)]
            for a, b in falling:
                inside = _items(clean, a, b)
                line = source.rfind('\n', 0, inside[-1][0] if inside else a) + 1
                indent = re.match(r'[ \t]*', source[line:])[0] if inside else '  '
                close_line = source.rfind('\n', 0, b) + 1
                edits.append((close_line, close_line, f'{indent}{tail}\n') if not source[close_line:b].strip()
                             else (b, b, f'\n{indent}{tail}\n'))
            out.append((_apply(source, edits), tail, list(dict.fromkeys(re.findall(IDENT, assign['rhs'])))))
    return out


def _written(statement):
    """The plain local a statement assigns, or None when it stores anywhere else (or isn't an assignment)."""
    hit = _ASSIGN.fullmatch(statement.strip())
    return hit['lhs'].strip() if hit and re.fullmatch(IDENT, hit['lhs'].strip()) else None


def _fold_in(text, name, lo, hi, tail, variable):
    """(text, hi) with `variable` folded into the copy of `tail` that ends the arm [lo, hi), or None."""
    part, end, clean = _body(text, name)
    items = _items(clean, lo, hi) if part else None
    last = _ASSIGN.fullmatch(text[items[-1][0]:items[-1][1]].strip()) if items else None
    if not last or last['lhs'].strip() != _ASSIGN.fullmatch(tail)['lhs'].strip():
        return None  # (the copy, as earlier folds left it, is what ends the arm)
    tail_start, tail_stop = items[-1]
    mentions = [lo + m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(variable)}\b', clean[lo:hi])]
    inside = [at for at in mentions if tail_start <= at < tail_stop]
    equals = _EQUALS.search(clean, tail_start, tail_stop)
    if len(mentions) != 2 or len(inside) != 1 or not equals or inside[0] < equals.end():
        return None
    for index in range(len(items) - 2, -1, -1):
        start, stop = items[index]
        hit = _ASSIGN.fullmatch(text[start:stop].strip())
        if not hit or hit['lhs'].strip() != variable:
            continue
        value = hit['rhs'].strip()
        read = set(re.findall(IDENT, value))
        if _IMPURE.search(value) or variable in read or any(
                _written(text[a:b]) is None or _written(text[a:b]) in read or not _plain(clean, a, b)
                for a, b in items[index + 1:-1]):
            return None
        folded = value if re.fullmatch(rf'{IDENT}|[0-9]\w*', value) else f'({value})'
        edits = [(inside[0], inside[0] + len(variable), folded), _cut(text, start, stop)]
        new = _apply(text, edits)
        return new, hi + len(new) - len(text)
    return None


def _drop_unused(text, name, variable):
    """The declaration line of `variable` when nothing else in the function names it any more."""
    part, end, clean = _body(text, name)
    if not part:
        return text
    mentions = list(re.finditer(rf'\b{re.escape(variable)}\b', clean[part.opening:end]))
    line = re.search(rf'(?m)^[ \t]*(?:[A-Za-z_][\w ]*?\s+\**)?{re.escape(variable)}\s*;[ \t]*\n', clean[part.opening:end])
    if len(mentions) == 1 and line and line.start() <= mentions[0].start() < line.end():
        return text[:part.opening + line.start()] + text[part.opening + line.end():]
    return text


def _fold(text, name, tail, names):
    """Every foldable temporary of every copy of `tail` (the arms are found once, then worked from the last to the
    first so the earlier ones keep their positions), then the declarations nothing names any more."""
    part, end, clean = _body(text, name)
    private = _private_regions(text, name, only=set(names)) if part else None
    arms = {}
    for variable, (_, regions, _) in (private or {}).items():
        for region in regions:
            arms.setdefault(region, []).append(variable)
    folded = []
    for (lo, hi), variables in sorted(arms.items(), reverse=True):
        for variable in sorted(variables, key=names.index):
            step = _fold_in(text, name, lo, hi, tail, variable)
            if step:
                text, hi = step
                folded.append(variable)
    for variable in dict.fromkeys(folded):
        text = _drop_unused(text, name, variable)
    return text, folded


def _sites(source, name):
    out = []
    for copied, tail, names in _tail_copies(source, name):
        text, folded = _fold(copied, name, tail, names)
        if folded and text != source and text not in out:
            out.append(text)
    return out


def variants(source, name):
    """One child per site, then every site in one child: a join that follows another is each no better alone (a
    second site alone scored 430 where the first alone scored 60 and both 20)."""
    if _body(source, name)[0] is None or re.search(r'\bvolatile\b', _blank(source)):
        return []
    singles = _sites(source, name)[:LIMIT]
    out = [(FAMILY, text) for text in singles]
    if len(singles) > 1:
        text = source
        for _ in range(LIMIT):
            more = _sites(text, name)
            if not more:
                break
            text = more[0]
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 95}  # the registry: no caller wiring (registry.py)
