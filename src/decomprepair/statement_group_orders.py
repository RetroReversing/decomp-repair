"""Every order of a small group of neighbouring statements, as one child each, kept to orders that respect their
dependencies.

GCC 2.7.2's first scheduler breaks equal priorities by insn order, loop.c emits what it hoists after the statements
before a loop, and local allocation numbers pseudos as they first appear; so which of a few independent loads or
assignments the C writes first can decide a register or a schedule that no single swap reaches. A greedy descent over
pair swaps stalls there, because the intermediate orders tie (a spilled-parameter function, `gcc-2.7.2-kmc -G0 -mips3
-mgp32 -mfp32 -O2`: the three assignments before its loop score 60 in five orders and 0 in one; a swap of two of them
from most wrong orders is another 60, so the descent never sees the exact order).

For each run of consecutive one-line statements in one block (an assignment or a store, no call, no `++`/`--`, no
`volatile`), each window of two to four of them is offered in every other order in which no statement moves past one
it depends on: a name one writes and another reads or writes, or memory (a store through a pointer, an array or a
field, or a write to a name that is not a local) against any other memory access. A candidate for the exact judge,
never a verdict.

Two additions from a display-list function (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`, 4900 -> 0):

- A cursor advance (`G = p + K`, a global written from a local `p` that was read from `G`) does not alias a store
  through `p`: the list the cursor points into is not the variable holding it. Memory dependence between the two is
  dropped, so the advance may sink past the words stored after it. (HYPOTHESIS, not read in sched.c: the order of the
  stores decides how long each hoisted constant lives, and local-alloc.c ranks equal-refs quantities by live length, so
  moving the advance one store later swapped two constants' registers.)
- Single-statement moves that tie alone but pay off together are offered as one child: every pair of disjoint moves
  (a statement moved one to three places in its run) is one candidate. In that function sinking the third advance one
  store down and sinking a scalar's `var = 2;` init past the last loads each scored the same 270 alone and 0 together,
  so a descent that keeps only improving children never took either.
"""
import itertools
import re

from .integer_repair_support import edit, view
from .line_scan import KEYWORDS, lines

FAMILY = 'statement_group_order'
FAMILIES = (FAMILY,)
WINDOW = 4
LIMIT = 64
MOVE = 3
PAIR_LIMIT = 96

_ASSIGN = re.compile(r'^(?P<lhs>[^=;{}]+?)\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)\s*(?P<rhs>[^;{}]+);$')
_CALL = re.compile(r'\b(?!sizeof\b)[A-Za-z_]\w*\s*\(')
_IDENT = re.compile(r'[A-Za-z_]\w*')
_TYPES = frozenset('s8 u8 s16 u16 s32 u32 s64 u64 f32 f64 char short int long float double unsigned signed void '
                   'const volatile struct union enum register static extern'.split())
_DECL = re.compile(r'^\s*(?:(?:const|volatile|register|unsigned|signed|struct|union|enum)\s+)*[A-Za-z_]\w*'
                   r'[\s*]+(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:=[^;]*)?;\s*$')


def _names(text):
    return {w for w in _IDENT.findall(text) if w not in KEYWORDS and w not in _TYPES}


def _locals(part, body):
    found = set()
    head = part.clean[:part.opening]
    for argument in head[head.rfind('(') + 1:head.rfind(')')].split(','):
        words = _IDENT.findall(argument)
        if words and words[-1] != 'void':
            found.add(words[-1])
    for line in body:
        m = _DECL.match(line.text)
        if m and '(' not in line.text:
            found.add(m['name'])
    return found


def _cursor_pointers(body, local):
    """{global: [locals read from it]}: `p = G;` with p a local and G a plain name that is not."""
    found = {}
    for line in body:
        m = re.match(r'^\s*([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*;\s*$', line.text)
        if m and m[1] in local and m[2] not in local and m[2] not in _TYPES:
            found.setdefault(m[2], set()).add(m[1])
    return found


def _statement(text, local, cursors=None):
    """(writes, reads, memory write, memory read, advance, through) for a plain one-line statement, or None.

    `advance` is (G, p) for `G = p + K;` where p was read from the global G; `through` is the local pointer a store
    writes through (`((T *) p)->m = v;`, `*(T *)((char *) p + K) = v;`, `M2C_FIELD(p, T, K) = v;`), else None."""
    text = text.strip()
    if 'volatile' in text or '++' in text or '--' in text or _CALL.search(text) or _DECL.match(text):
        return None
    m = _ASSIGN.match(text)
    if not m:
        return None
    lhs, rhs = m['lhs'].strip(), m['rhs']
    compound = re.match(r'\s*(?:[-+*/%&|^]|<<|>>)=', text[len(m['lhs']):]) is not None
    plain = re.fullmatch(r'[A-Za-z_]\w*', lhs)
    if plain and lhs in local:
        writes, mem_write = {lhs}, False
        reads = _names(rhs) | ({lhs} if compound else set())
    else:
        writes, mem_write = set(), True
        reads = _names(rhs) | _names(lhs)
    mem_read = bool(re.search(r'\*|\[|->|\.', rhs.replace('*)', ')'))) or any(n not in local for n in reads)
    if mem_write and re.search(r'\*|\[|->|\.', lhs.replace('*)', ')')):
        mem_read = True
    advance = through = None
    if cursors:
        m2 = re.fullmatch(r'([A-Za-z_]\w*)\s*\+\s*(?:0[xX][0-9a-fA-F]+|\d+)', rhs.strip())
        if plain and m2 and m2[1] in cursors.get(lhs, ()):
            advance = (lhs, m2[1])
        elif not plain:
            targets = {n for n in _names(lhs) if n in local}
            if len(targets) == 1 and re.match(r'^\s*(?:\*|\(|M2C_FIELD)', lhs):
                through = next(iter(targets))
    return writes, reads, mem_write, mem_read, advance, through


def _apart(a, b):
    """A cursor advance and a store through the pointer it advances touch different memory."""
    return (a[4] is not None and b[5] == a[4][1] and a[4][0] not in b[1]) or \
           (b[4] is not None and a[5] == b[4][1] and b[4][0] not in a[1])


def _depends(a, b):
    wa, ra, mwa, mra = a[:4]
    wb, rb, mwb, mrb = b[:4]
    if wa & (rb | wb) or wb & ra:
        return True
    if _apart(a, b):
        return False
    return (mwa and (mwb or mrb)) or (mwb and mra)


def _orders(facts):
    n = len(facts)
    edges = {(i, j) for i in range(n) for j in range(i + 1, n) if _depends(facts[i], facts[j])}
    for order in itertools.permutations(range(n)):
        if order == tuple(range(n)):
            continue
        place = {k: p for p, k in enumerate(order)}
        if all(place[i] < place[j] for i, j in edges):
            yield order


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    local = _locals(part, body)
    cursors = _cursor_pointers(body, local)
    runs, run = [], []
    for line in body:
        facts = _statement(line.text, local, cursors) if line.text.strip() else None
        if facts is not None and (not run or line.indent == run[-1][0].indent):
            run.append((line, facts))
            continue
        if len(run) > 1:
            runs.append(run)
        run = [(line, facts)] if facts is not None else []
    if len(run) > 1:
        runs.append(run)
    out, seen = [], set()
    for size in range(2, WINDOW + 1):
        for run in runs:
            for first in range(len(run) - size + 1):
                window = run[first:first + size]
                start, end = window[0][0].start, window[-1][0].end
                texts = [source[line.start:line.end] for line, _ in window]
                texts = [t if t.endswith('\n') else t + '\n' for t in texts]
                for order in _orders([facts for _, facts in window]):
                    replacement = ''.join(texts[k] for k in order)
                    if not source[start:end].endswith('\n'):
                        replacement = replacement[:-1]
                    child = edit(source, [(start, end, replacement)])
                    if child not in seen and child != source:
                        seen.add(child)
                        out.append((FAMILY, child))
                    if len(out) >= LIMIT:
                        return out + _pairs(source, runs, seen)
    return out + _pairs(source, runs, seen)


def _moves(run):
    """(span first, span last, replacement order) for each statement moved one to MOVE places along its run, past
    only statements it does not depend on."""
    out = []
    for i in range(len(run)):
        for step in range(1, MOVE + 1):
            for target in (i + step, i - step):
                if not 0 <= target < len(run):
                    continue
                low, high = min(i, target), max(i, target)
                others = [k for k in range(low, high + 1) if k != i]
                if any(_depends(run[i][1], run[k][1]) for k in others):
                    continue
                order = [k for k in range(low, high + 1) if k != i]
                order.insert(target - low, i)
                out.append((low, high, order, step))
    return out


def _pairs(source, runs, seen):
    """Two disjoint moves as one child: edits that tie alone and win together are invisible to a greedy descent."""
    found = []
    for run in runs:
        moves = _moves(run)
        for a, b in itertools.combinations(moves, 2):
            if a[1] < b[0] or b[1] < a[0]:
                found.append((a[3] + b[3], run, a, b))
    found.sort(key=lambda item: item[0])
    out = []
    for _, run, a, b in found:
        edits = []
        for low, high, order, _step in (a, b):
            window = run[low:high + 1]
            start, end = window[0][0].start, window[-1][0].end
            texts = [source[line.start:line.end] for line, _ in window]
            texts = [t if t.endswith('\n') else t + '\n' for t in texts]
            replacement = ''.join(texts[k - low] for k in order)
            if not source[start:end].endswith('\n'):
                replacement = replacement[:-1]
            edits.append((start, end, replacement))
        child = edit(source, edits)
        if child not in seen and child != source:
            seen.add(child)
            out.append((FAMILY, child))
        if len(out) >= PAIR_LIMIT:
            break
    return out
