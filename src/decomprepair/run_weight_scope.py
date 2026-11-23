"""A whole `if` block, or a run of statements, wrapped in one one-shot scope so the locals it names outweigh a rival.

GCC 2.x hands the saved registers to pseudos in order of `floor_log2(refs) * refs / live length` (global.c), and flow.c
counts a reference once more for every loop it sits in. `do { ... } while (0);` is one loop more round everything inside
it, at no instruction or run-time cost, so every reference to every local in the scope weighs one more. The existing
ladders wrap a call (`call_weight_ladder`), a loop step (`loop_weight_set`) or the single statements that name one local
and not its rival (`local_weight_ladder`); none of them wraps a *block*: the `if (...) { ... }` that holds forty of a
pointer's references, or the three stores that read one float constant, are the units that move a priority far enough.

A 874-instruction KMC N64 object spawner (`-G0 -mips3 -mgp32 -mfp32 -O2`; the first arm's record pointer and the
parameter's copy were in each other's saved registers, 111 differing rows) went 3786 -> 3711 with the one `if (...) { ... }`
block that holds the record pointer's stores and calls wrapped once; the same scope round the run of its allocation
and field stores inside that block took the pointer from 23 weighted references to 47 over its 311 live instructions
and it outranked the parameter (3711 -> 3521: the saved registers `$s4`, `$s5` and `$s6` then fell on the target's); the three
stores that multiply a float by one constant, wrapped once, moved the constant ahead of the 1.0f flag in the float
registers (3521 -> 3501), and one call wrapped alone put a pointer's copy ahead of a later one (3576 -> 3436). Each
wrapper alone is a plain plateau-free step, but no family offered a block or a run: the greedy chain's best children
stayed at the source's score. Those numbers are the allocation table's (`-dl -dg`), the compiler's reasons are hypotheses
read from it, not confirmed in its source. The scopes are scaffolding no developer wrote; polishing removes them once the
function is recorded as matched.

`units` reads the function's statements block by block: every compound statement (`if`, `else`, `for`, `while`, `do`, a
bare block) as one unit, every run of two to `MAX_RUN` consecutive simple statements, and every simple statement that
names a local, each with the declared locals it names. A unit that holds a `break`, `continue`, `goto`, a label or a
`case` (a wrapper would change what they bind to), a declaration, an `asm` or a `volatile`, or that already is a one-shot
scope, is left out. `variants` wraps one unit once per child, the compound units first (they weigh the most), then the
runs, then the single statements, up to `LIMIT` children. The judge decides, and no child is a verdict."""
import re

from .integer_repair_support import IDENT, edit, view
from .loop_weight_set_repairs import _declarations_end

FAMILY = 'run_weight_scope'
FAMILIES = (FAMILY,)
LIMIT = 800
MAX_RUN = 10
_CONTROL = re.compile(r'\b(?:break|continue|goto|case|default|asm|__asm__|volatile|setjmp|longjmp)\b')
_LABEL = re.compile(rf'(?<![\w:?])(?:{IDENT})\s*:(?!:)')
_HEAD = re.compile(r'(?P<kw>if|while|for|switch)\s*\(')
_SCOPE = re.compile(r'do\s*{[^{}]*}\s*while\s*\(\s*0\s*\)\s*;?$')
_INITIALISED = re.compile(rf'(?:(?:unsigned|signed|const|volatile|static|register)\s+)*(?:{IDENT}\s+)+\**\s*{IDENT}\s*'
                          rf'(?:\[[^\]]*\])?\s*(?:=[^;{{}}]*)?;$')


def _match(clean, at, opening, closing):
    """The index just past the bracket that closes the one opened at `at`, or -1."""
    depth = 0
    for i in range(at, len(clean)):
        if clean[i] == opening:
            depth += 1
        elif clean[i] == closing:
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _statement_end(clean, at, limit):
    """The end of the statement that starts at `at` (compound statements with their `else` chain), or -1."""
    while at < limit and clean[at].isspace():
        at += 1
    if at >= limit:
        return -1
    if clean[at] == '{':
        return _match(clean, at, '{', '}')
    head = _HEAD.match(clean, at)
    if head:
        close = _match(clean, head.end() - 1, '(', ')')
        if close < 0:
            return -1
        end = _statement_end(clean, close, limit)
        if end < 0 or head['kw'] != 'if':
            return end
        tail = re.match(r'\s*else\b', clean[end:limit])
        if tail:
            return _statement_end(clean, end + tail.end(), limit)
        return end
    if re.match(r'do\b', clean[at:limit]):
        body = _statement_end(clean, at + 2, limit)
        loop = re.compile(r'\s*while\s*\(').match(clean, body) if body > 0 else None
        if not loop:
            return -1
        close = _match(clean, loop.end() - 1, '(', ')')
        semicolon = re.compile(r'\s*;').match(clean, close) if close > 0 else None
        return semicolon.end() if semicolon else -1
    semicolon = clean.find(';', at, limit)
    return semicolon + 1 if semicolon >= 0 else -1


def _block_statements(clean, start, end):
    """[(start, end, compound)] of the statements directly inside clean[start:end]."""
    found, at = [], start
    while at < end:
        while at < end and (clean[at].isspace() or clean[at] == ';'):
            at += 1
        if at >= end:
            break
        stop = _statement_end(clean, at, end)
        if stop < 0:
            break
        found.append((at, stop, clean[at] == '{' or bool(_HEAD.match(clean, at)) or clean[at:at + 3] == 'do ' or clean[at:at + 3] == 'do{'))
        at = stop
    return found


def _inner(clean, start, end):
    seen = set()
    stack = [(start, end)]
    while stack:
        span = stack.pop()
        if span in seen:
            continue
        seen.add(span)
        yield span
        for first, stop, _ in _block_statements(clean, *span):
            for opening in re.finditer(r'{', clean[first:stop]):
                at = first + opening.start()
                close = _match(clean, at, '{', '}')
                if 0 < close <= stop and (at + 1, close - 1) != span:
                    stack.append((at + 1, close - 1))


_KEYWORDS = {'if', 'else', 'while', 'for', 'do', 'switch', 'return', 'goto', 'break', 'continue', 'case', 'default',
             'typedef', 'sizeof'}
_DECLARATION = re.compile(rf'^(?:(?:{IDENT})\s+)+\**\s*{IDENT}(?:\s*\[[^\]]*\])*(?:\s*,\s*\**\s*{IDENT}(?:\s*\[[^\]]*\])*)*'
                          rf'(?:\s*=[^;{{}}]*)?\s*;$')


def _declared(part):
    """The parameters and the locals of the function: its leading declaration lines (`register void *p;`, `s32 a, b;`,
    `} locals;` after a struct block, an initialised `f32 x = 1.0f;`) up to the first statement."""
    from .call_weight_ladder import _parameters
    names = set(_parameters(part))
    depth = 0
    for line in part.clean[part.opening + 1:part.end - 1].split('\n'):
        text = line.strip()
        if not text:
            continue
        if depth == 0:
            words = re.match(r'\w+', text)
            if text.startswith('}'):
                pass
            elif words and words.group(0) in _KEYWORDS:
                break
            elif re.match(r'(?:struct|union)\s*(?:\w+\s*)?{$', text):
                depth += 1
                continue
            elif not _DECLARATION.match(text):
                break
            else:
                first = text.split('=')[0] if '=' in text else text
                for piece in first.rstrip(';').split(','):
                    found = re.findall(IDENT, re.sub(r'\[[^\]]*\]', '', piece))
                    if found:
                        names.add(found[-1])
                continue
        depth += text.count('{') - text.count('}')
        if depth == 0:
            tail = re.search(rf'}}\s*(?P<n>{IDENT})\s*;', text)
            if tail:
                names.add(tail['n'])
    return names


def units(source, name):
    """[(start, end, text, {name: references}, kind)] of the units the function offers, kind 0 for a compound statement,
    1 for a run of statements and 2 for one statement."""
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile|setjmp|longjmp)\b|^\s*#', part.clean[:part.end], re.M):
        return []
    names = _declared(part)
    if not names:
        return []
    clean = part.clean
    skip = _declarations_end(clean, part)
    first = part.opening + 1 + skip
    spans = sorted(set(_inner(clean, first, part.end - 1)))
    found, seen = [], set()
    for start, end in spans:
        listed = _block_statements(clean, start, end)
        for index, (a, b, compound) in enumerate(listed):
            runs = [(a, b, 0 if compound else 2, [(a, b, compound)])]
            run = [(a, b, compound)]
            for c, d, other in listed[index + 1:index + MAX_RUN]:
                run = run + [(c, d, other)]
                runs.append((a, d, 1, run))
            for x, y, kind, members in runs:
                if (x, y) in seen:
                    continue
                text = clean[x:y]
                if _CONTROL.search(text) or _LABEL.search(text) or _SCOPE.match(text.strip()):
                    continue
                if any(_INITIALISED.match(clean[p:q].strip()) for p, q, c in members if not c):
                    continue
                counts = {n: len(re.findall(rf'(?<![\w.>]){re.escape(n)}\b', text)) for n in names}
                counts = {n: c for n, c in counts.items() if c}
                if counts:
                    seen.add((x, y))
                    found.append((x, y, source[x:y], counts, kind))
    found.sort(key=lambda u: (u[4] != 0, -sum(u[3].values()), u[0], u[1]))
    return found


def variants(source, name):
    result = []
    for start, end, text, _, _ in units(source, name)[:LIMIT]:
        wrapped = 'do { ' + text.strip() + ' } while (0);'
        result.append((FAMILY, edit(source, [(start, end, wrapped)])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
