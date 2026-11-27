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
  or are read by the statement that first sets the next one (`b = f(a);`, written `a = f(a);`),
  and no loop (`for`, `while`, a `do` that is not a fence, a backward `goto`) holds mentions of both: in a loop a later
  assignment reaches an earlier read on the next round.
m2c's second allocation is often exactly that shape: `temp_v0 = alloc(); ...; temp_v0_2 = alloc(temp_v0);`, a stray
argument or a real one. On an 82-instruction N64 function (SN64 GCC 2.8.1 `-G0 -mips3 -O2`) one variable for both
puts both pointers in `$a0`, as the target does (75 -> 0, the last of five edits).

A `s16` or `s8` temporary whose every assignment is a signed read of that width (`M2C_FIELD(p, s16 *, 8)`,
`*(s16 *) p`, `(s16) (..)`) joins an `s32` group of its base name: the value is the same once sign-extended, and m2c
types the load's temporary by the load, so one register's `x` reads came out as two types. A 149-instruction N64 triangle
test (SN GCC 2.8.1 `-O2`) went 30 -> 0 when the third edge's `lh` temporary became the one `s32` the other reads use (one
function). It never names the merged variable: the run keeps an `s32` one. When several runs are of one register file
(`temp_a1` and `temp_a2`), a child merges those runs together and leaves the others: on that function all four runs at
once scored 30 where the two `temp_a` runs were exact.

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


_WIDE = {'s16': 's32', 's8': 's32'}


def _whole(text, opening):
    """Whether the group opening at `opening` closes at the end of `text`."""
    return opening < len(text) and text[opening] == '(' and close(text, opening, '(', ')') == len(text) - 1


def _signed_read(value, kind):
    """Whether `value` is one signed read of the type `kind` and nothing else."""
    value = value.strip()
    field = re.match(r'M2C_FIELD\s*(?=\()', value)
    if field:
        return _whole(value, field.end()) and re.search(rf',\s*{kind}\s*\*\s*,[^,]*\)$', value) is not None
    cast = re.match(rf'(?:\*\s*\(\s*{kind}\s*\*\s*\)|\(\s*{kind}\s*\))\s*', value)
    if not cast:
        return False
    rest = value[cast.end():]
    return re.fullmatch(r'[A-Za-z_]\w*', rest) is not None or _whole(rest, 0)


def _widens(clean, kind, spots):
    """Whether the narrow temporary at `spots` only ever holds signed reads of its own width."""
    for _, end in spots:
        after = clean[end:].lstrip()
        if re.match(r'(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)=)', after) or re.search(r'(?:\+\+|--)\s*$', clean[:end].rstrip()):
            return False
        write = re.match(r'=(?!=)\s*([^;{}]*);', after)
        if write and not _signed_read(write[1], kind):
            return False
    return True


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
    narrow = set()
    wide_bases = {_NAME.fullmatch(name)['base'] for name, found in declared.items()
                  if len(found) == 1 and found[0][1] == 's32' and _NAME.fullmatch(name)}
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
        if kind in _WIDE and match['base'] in wide_bases and _widens(clean, kind, spots):
            narrow.add(name)
            kind = _WIDE[kind]
        groups.setdefault((match['base'], kind), []).append((name, first[0], spots[-1][1], spots, hit.span()))
    runs = []
    for members in groups.values():
        members.sort(key=lambda member: member[1])
        run = []
        for member in members:
            if run:
                previous = run[-1]
                together = any(any(a <= x < b for x, _ in previous[3]) and any(a <= x < b for x, _ in member[3])
                               for a, b in loops)
                if (previous[2] <= member[1] or _passed_on(clean, previous, member)) and not together:
                    run.append(member)
                    continue
                if len(run) > 1:
                    runs.append(run)
            run = [] if member[0] in narrow else [member]  # the run's name is an `s32` one
        if len(run) > 1:
            runs.append(run)
    return sorted(runs, key=lambda run: run[0][1])


def _passed_on(clean, previous, member):
    """Whether the only mentions of `previous` after `member`'s first are plain reads inside the statement that first
    sets `member` (`temp_v0_2 = f(temp_v0);`): the right side is evaluated before the assignment, and nothing reads
    the earlier value after it, so the two can be one variable (`temp_v0 = f(temp_v0);`)."""
    end = clean.find(';', member[1])
    if end < 0 or re.search(r'[{}?]', clean[member[1]:end]):
        return False
    for start, stop in previous[3]:
        if stop <= member[1]:
            continue
        if not (member[1] < start and stop <= end):
            return False
        if re.search(r'(?:\+\+|--|(?<!&)&)\s*$', clean[:start]) or re.match(r'\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))',
                                                                          clean[stop:end + 1]):
            return False
    return True


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
    # the runs of one register file at once (`temp_a1` with `temp_a2`): merging every run can undo the gain, since the
    # `temp_v*` values the compiler would have named anyway take other registers once they share a variable
    files = {}
    for run in runs:
        files.setdefault(re.sub(r'\d+$', '', _NAME.fullmatch(run[0][0])['base']), []).append(run)
    plans += [group for group in files.values() if 1 < len(group) < len(runs)]
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
