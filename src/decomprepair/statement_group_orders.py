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
"""
import itertools
import re

from .integer_repair_support import edit, view
from .line_scan import KEYWORDS, lines

FAMILY = 'statement_group_order'
FAMILIES = (FAMILY,)
WINDOW = 4
LIMIT = 64

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


def _statement(text, local):
    """(writes, reads, memory write, memory read) for a plain one-line statement, or None."""
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
    return writes, reads, mem_write, mem_read


def _depends(a, b):
    wa, ra, mwa, mra = a
    wb, rb, mwb, mrb = b
    if wa & (rb | wb) or wb & ra:
        return True
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
    runs, run = [], []
    for line in body:
        facts = _statement(line.text, local) if line.text.strip() else None
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
                        return out
    return out
