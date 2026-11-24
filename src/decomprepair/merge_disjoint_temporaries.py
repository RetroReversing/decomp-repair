"""m2c's `temp_s0`, `temp_s0_2`, `temp_s0_3` (one value each, one after another) written as one variable set several times.

m2c gives a register that holds several unrelated values one after another a new temporary per value, numbering them
`temp_s0`, `temp_s0_2`, `temp_s0_3`, and wraps each statement it could not place in a fence, `do { temp_s0 = f(x); }
while (0);`. The compiler sees three variables, each set once. GCC 2.8's first scheduler moves a value that is set
once down to just before its first use; a variable that is assigned several times has no such move-down, and the
arguments of the calls come out in source order. The target (written by hand, with one variable) has the second
shape, so every row that depends on where a value is loaded cascades. A small N64 function with three temporaries in
one saved register, a call after each and a fence around every call, went 120 -> 0 as one variable set three times with
the fences gone. Hypothesis (not confirmed in the compiler's source): the single-set rule of sched.c's move-down, read
off the target's order of loads.

Children, for the function's temporaries that share a base name (`temp_s0` and its `_2`, `_3`, ... or `var_s0`...) and
one type, whose uses never overlap: every one of a run merged into the first (declared once, the others' declarations
removed), then each neighbouring pair, each with the fences that wrap one statement naming the merged variable
(`do { x = f(); } while (0);`) kept and with them removed.
A temporary is merged only when:
- its declaration is a plain `TYPE name;` and the types of the group are the same text;
- its first mention is an assignment (a value set before anything reads it) and its address is never taken;
- the mentions of the earlier one all come before the first mention of the next one (the live ranges are disjoint),
  and no loop (`for`, `while`, a `do` that is not a fence, a backward `goto`) holds mentions of both: in a loop a later
  assignment reaches an earlier read on the next round.
Only MIPS. The candidate is never a verdict: the judge decides."""
import re

from .c_scan import close
from .integer_repair_support import _address_taken, edit, view

FAMILY = 'merge_disjoint_temporaries'
FAMILIES = (FAMILY,)

LIMIT = 8  # children per function
_DECL = re.compile(r'(?m)^[ \t]*(?P<type>[A-Za-z_][\w \t]*\**)[ \t]*(?P<name>(?:temp|var)_\w+)[ \t]*;[ \t]*\n?')
_NAME = re.compile(r'(?P<base>(?:temp|var)_\w*?)(?:_(?P<n>\d+))?')
_FENCE = re.compile(r'do\s*\{\s*(?P<stmt>[^;{}]*;)\s*\}\s*while\s*\(\s*0\s*\)\s*;')
_FLOW = re.compile(r'\b(?:break|continue|goto|return)\b')


def _mentions(clean, name, lo, hi):
    return [m.span() for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[lo:hi])]


def _loops(clean, lo, hi):
    """The spans of what repeats inside clean[lo:hi]: loops with a block or one statement, `do` blocks whose condition
    is not 0 (a `do { } while (0)` is a fence), and what lies between a label and a `goto` back to it. None when a loop
    is not one this reads."""
    spans, tails = [], set()
    for hit in re.finditer(r'\bdo\b\s*\{', clean[lo:hi]):
        opening = lo + hit.end() - 1
        end = close(clean, opening)
        tail = re.match(r'\s*while\s*\((?P<cond>[^;]*)\)\s*;', clean[end + 1:hi]) if end >= 0 else None
        if not tail:
            return None
        tails.add(end + 1 + clean[end + 1:].index('while'))
        if tail['cond'].strip() != '0':
            spans.append((lo + hit.start(), end + 1 + tail.end()))
    for hit in re.finditer(r'\b(?:for|while)\s*\(', clean[lo:hi]):
        start = lo + hit.start()
        if start in tails:
            continue
        after = close(clean, lo + hit.end() - 1, '(', ')')
        if after < 0:
            return None
        position = hi - len(clean[after + 1:hi].lstrip())
        end = close(clean, position) if clean[position] == '{' else clean.find(';', position)
        if end < 0:
            return None
        spans.append((start, end + 1))
    for hit in re.finditer(r'\bgoto\s+(\w+)\s*;', clean[lo:hi]):
        label = re.search(rf'(?<![\w?]){re.escape(hit[1])}\s*:(?!:)', clean[lo:hi])
        if label and label.start() < hit.start():
            spans.append((lo + label.start(), lo + hit.end()))
    return spans


def _runs(part):
    """[[(name, first, last, mentions, declaration span)]]: the temporaries to merge, one list per base name and type,
    each a run whose neighbours are disjoint, in order of first mention."""
    clean, lo, hi = part.clean, part.opening, part.end
    loops = _loops(clean, lo, hi)
    if loops is None:
        return []
    declared = {}
    for hit in _DECL.finditer(clean, lo, hi):
        declared.setdefault(hit['name'], []).append((hit, re.sub(r'\s+', '', hit['type'])))
    groups = {}
    for name, found in declared.items():
        match = _NAME.fullmatch(name)
        if len(found) != 1 or not match:
            continue
        hit, kind = found[0]
        spots = [(lo + a, lo + b) for a, b in _mentions(clean, name, lo, hi)
                 if not hit.start() <= lo + a < hit.end()]
        if not spots or _address_taken(clean[lo:hi], name):
            continue
        first = spots[0]
        before = clean[:first[0]].rstrip()
        if not re.match(r'=(?!=)', clean[first[1]:].lstrip()) or not (before[-1:] in ';{}' or before.endswith(('else', 'do'))):
            continue
        groups.setdefault((match['base'], kind), []).append((name, first[0], spots[-1][1], spots, hit.span()))
    runs = []
    for members in groups.values():
        members.sort(key=lambda member: member[1])
        run = [members[0]]
        for member in members[1:]:
            previous = run[-1]
            together = any(any(a <= x < b for x, _ in previous[3]) and any(a <= x < b for x, _ in member[3])
                           for a, b in loops)
            if previous[2] <= member[1] and not together:
                run.append(member)
            else:
                if len(run) > 1:
                    runs.append(run)
                run = [member]
        if len(run) > 1:
            runs.append(run)
    return sorted(runs, key=lambda run: run[0][1])


def _merged(source, chosen):
    """`source` with every temporary of `chosen` (a list of runs' members) renamed to the first of its run."""
    edits = []
    for members in chosen:
        keep = members[0][0]
        for name, _, _, spots, declaration in members[1:]:
            edits += [(a, b, keep) for a, b in spots]
            edits.append((declaration[0], declaration[1], ''))
    return edit(source, edits) if edits else source


def _unfenced(text, name, kept):
    """`text` without the fences around one statement that names one of `kept`."""
    for _ in range(8):
        part = view(text, name)
        if not part:
            return text
        for hit in _FENCE.finditer(part.clean, part.opening, part.end):
            statement = hit['stmt']
            if _FLOW.search(statement) or not any(re.search(rf'(?<![\w.>]){re.escape(one)}\b', statement) for one in kept):
                continue
            text = text[:hit.start()] + text[hit.start('stmt'):hit.end('stmt')] + text[hit.end():]
            break
        else:
            return text
    return text


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    runs = _runs(part)
    if not runs:
        return []
    plans = [[run] for run in runs]
    if len(runs) > 1:
        plans.append(runs)
    for run in runs:
        if len(run) > 2:
            plans += [[run[i:i + 2]] for i in range(len(run) - 1)]
    out = []
    for plan in plans:
        merged = _merged(source, plan)
        kept = [members[0][0] for members in plan]
        out += [(FAMILY, merged), (FAMILY, _unfenced(merged, name, kept))]
    return [item for item in dict.fromkeys(out) if item[1] != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
