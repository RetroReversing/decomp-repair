"""m2c's `goto` form of a compare of two runs, written as the indexed `for` loop with a `break` it came from.

A name or key compare (`for (i = 0; i < 16; i++) if (a[i] != b[i]) { fail = 1; break; }`) comes back from m2c as a
label, one stepped pointer per side and a counter:

    var_a0 = 0;
    var_a2 = arg3;
    var_a1 = &sp20;
    loop_9:
    var_a2 += 1;                       (the branch's delay slot: m2c writes it ahead of the compare)
    if (*var_a1 == *var_a2) {
        var_a0 += 1;
        var_a1 += 1;
        if (var_a0 < 0x10) { goto loop_9; }
    } else {
        var_a3 = 1;
    }

The same compare may already index both sides (`a[i] == b[i]`) and still loop by `goto`, and a search may have written
the unequal arm first. A game wrote the `for`: the loop pass makes the two pointers itself and puts one step in the
mismatch branch's delay slot. A pointer stepped ahead of the compare in the draft is read here as not yet stepped (the
step is the delay slot's; a hypothesis from the target's instructions, so the judge decides). On a 104-instruction N64
directory search under KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`), the one compare left by `goto` in otherwise exact
C scored 3190; the best earlier rewrite of it (a `for (;;)` with `continue`) reached 560, this form 0.

`compare_run_shared_counter` also gives every rewritten compare of the function the first one's counter: a function that
reused `i` keeps one pseudo for both loops (1040 against 0 on the same function). Proposals only.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'compare_run_for_break'
SHARED = 'compare_run_shared_counter'
FAMILIES = (FAMILY, SHARED)

_LABEL = re.compile(rf'(?<![\w.?:])(?P<label>{IDENT})[ \t]*:(?![:=])\s*')
_STEP = re.compile(rf'\s*(?:(?P<a>{IDENT})\s*(?:\+\+|\+=\s*1)|\+\+\s*(?P<b>{IDENT}))\s*;')
_IF = re.compile(r'\s*if\s*\(')
_OPEN = re.compile(r'\s*\{')
_ELSE = re.compile(r'\s*else\s*\{')
_SET = rf'{IDENT}\s*=(?!=)\s*[^;{{}}=]+;'
_LAST_SET = re.compile(rf'(?<![\w.>*\]])(?P<name>{IDENT})\s*=(?!=)\s*(?P<value>[^;{{}}=]+);\s*$')
_LAST_FENCE = re.compile(rf'\bdo\s*\{{(?P<body>(?:\s*{_SET})+)\s*\}}\s*while\s*\(\s*0\s*\)\s*;\s*$')
_BASE = re.compile(rf'&?{IDENT}(?:(?:\.|->){IDENT})*')


def _name(hit):
    return hit['a'] or hit['b']


def _block(clean, pattern, at):
    """(start, end) inside the braces of the block `pattern` opens at `at`, and the offset past its `}`; or None."""
    opened = pattern.match(clean, at)
    past = close(clean, opened.end() - 1, '{', '}') if opened else None
    return (opened.end(), past - 1, past) if past else None


def _compare(clean, source, start, end):
    """(left span, operator, right span) of a condition that is one `==` or `!=`."""
    depth, found = 0, []
    for at in range(start, end):
        depth += (clean[at] in '([') - (clean[at] in ')]')
        if depth == 0 and clean[at:at + 2] in ('==', '!=') and clean[at - 1] not in '<>!=':
            found.append(at)
        if depth == 0 and clean[at:at + 2] in ('&&', '||'):
            return None
    if len(found) != 1:
        return None
    at = found[0]
    return source[start:at].strip(), clean[at:at + 2], source[at + 2:end].strip()


def _latch(clean, start, end, label):
    """(steps, counter, limit) of the continuing arm `i++; p++; if (i < N) { goto label; }`."""
    steps, at = [], start
    while True:
        hit = _STEP.match(clean, at, end)
        if not hit:
            break
        steps.append(_name(hit))
        at = hit.end()
    tail = re.compile(rf'\s*if\s*\(\s*(?P<counter>{IDENT})\s*<\s*(?P<limit>{NUMBER})\s*\)\s*'
                      rf'(?:\{{\s*goto\s+{label}\s*;\s*\}}|goto\s+{label}\s*;)\s*$').match(clean, at, end)
    if not tail or int(re.sub(r'[uUlL]+$', '', tail['limit']), 0) <= 0:
        return None
    return steps, tail['counter'], tail['limit']


def _inits(clean, floor, label_at, wanted):
    """The `v = value;` statements (possibly in a `do { } while (0);`) just above the label that set every name in
    `wanted`: ({name: value span}, [spans to delete]), or None."""
    values, cuts, end = {}, [], label_at
    while wanted - set(values):
        text = clean[floor:end]
        fence = _LAST_FENCE.search(text)
        if fence:
            sets = list(re.finditer(rf'(?P<name>{IDENT})\s*=\s*(?P<value>[^;{{}}=]+);', fence['body']))
            base = floor + fence.start('body')
            names = [s['name'] for s in sets]
            if set(names) - wanted or len(set(names)) != len(names) or set(names) & set(values):
                return None
            for s in sets:
                values[s['name']] = (base + s.start('value'), base + s.end('value'))
            cuts.append((floor + fence.start(), floor + fence.end()))
            end = floor + fence.start()
            continue
        last = _LAST_SET.search(text)
        if not last or last['name'] not in wanted or last['name'] in values:
            return None
        values[last['name']] = (floor + last.start('value'), floor + last.end('value'))
        cuts.append((floor + last.start(), floor + last.end()))
        end = floor + last.start()
    return values, cuts


def _pointed(part, pointer):
    """The element type of a local pointer, from its declaration."""
    hit = re.search(rf'(?<![\w])((?:unsigned\s+|signed\s+|struct\s+)?{IDENT})\s*\*\s*{pointer}\s*;',
                    part.clean[part.opening:part.end])
    return ' '.join(hit[1].split()) if hit else None


def _element(part, name, pointer, base, counter):
    """`base[counter]` for what `pointer` walked from `base`, cast when `base` is not already the pointer's type."""
    kind = _pointed(part, pointer)
    base = base.strip()
    if not kind or not _BASE.fullmatch(base):
        cast = re.fullmatch(rf'\(\s*{re.escape(kind or "")}\s*\*\s*\)\s*({_BASE.pattern})', base) if kind else None
        if not cast:
            return None
        base = cast[1]
    head = part.clean[:part.opening]
    if base.startswith('&'):
        local = base[1:]
        same = re.search(rf'(?<![\w]){kind}\s+{local}\s*[;\[]', part.clean[part.opening:part.end])
        return f'({base})[{counter}]' if same else f'(({kind} *) {base})[{counter}]'
    same = (re.search(rf'(?<![\w]){kind}\s*\*\s*{re.escape(base)}\s*[,)]', head[head.rfind(name):])
            or re.search(rf'(?<![\w]){kind}\s*(?:\*\s*{re.escape(base)}\s*;|\s{re.escape(base)}\s*\[)',
                         part.clean[part.opening:part.end]))
    return f'{base}[{counter}]' if same else f'(({kind} *) {base})[{counter}]'


def _run(part, name, label):
    """One compare run at `label:` as a dict (span, counter, parts and the spans of its init statements), or None."""
    source, clean = part.source, part.clean
    word = label['label']
    if word in ('case', 'default') or len(re.findall(rf'\bgoto\s+{word}\s*;', clean[part.opening:part.end])) != 1:
        return None
    at, early = label.end(), []
    while True:
        hit = _STEP.match(clean, at)
        if not hit:
            break
        early.append(_name(hit))
        at = hit.end()
    head = _IF.match(clean, at)
    past = close(clean, head.end() - 1) if head else None
    if not past:
        return None
    compare = _compare(clean, source, head.end(), past - 1)
    first = _block(clean, _OPEN, past)
    if not compare or not first:
        return None
    other = _block(clean, _ELSE, first[2])
    left, operator, right = compare
    if operator == '==':
        going, leaving = first, other
    else:
        going, leaving = other, first
    end = other[2] if other else first[2]
    if not going:
        return None
    latch = _latch(clean, going[0], going[1], word)
    if not latch:
        return None
    steps, counter, limit = latch
    steps = early + steps
    if steps.count(counter) != 1 or counter in early or len(set(steps)) != len(steps):
        return None
    pointers = [s for s in steps if s != counter]
    exit_text = source[leaving[0]:leaving[1]].strip() if leaving else ''
    exit_clean = clean[leaving[0]:leaving[1]] if leaving else ''
    if re.search(r'\b(?:goto|break|continue|case|default|switch|for|while|do)\b|(?<!\?)\b[A-Za-z_]\w*\s*:(?!:)', exit_clean):
        return None
    found = _inits(clean, part.opening + 1, label.start(), {counter, *pointers})
    if not found:
        return None
    values, cuts = found
    if source[slice(*values[counter])].strip() != '0':
        return None
    sides = [left, right]
    for pointer in pointers:
        reads = [i for i, side in enumerate(sides) if re.fullmatch(rf'\*\s*{pointer}', side)]
        if len(reads) != 1:
            return None
        element = _element(part, name, pointer, source[slice(*values[pointer])], counter)
        if not element:
            return None
        sides[reads[0]] = element
    start = min(cut[0] for cut in cuts)
    if not all(re.search(rf'\[\s*{counter}\s*\]', side) for side in sides):
        return None
    body = clean[part.opening:part.end]
    for pointer in pointers:
        outside = clean[part.opening:start] + clean[end:part.end]
        if len(re.findall(rf'(?<![\w.>]){pointer}\b', outside)) != 1 or re.search(rf'&\s*{pointer}\b', body) \
                or re.search(rf'(?<![\w.>]){pointer}\b', exit_clean):
            return None
    if re.search(rf'&\s*{counter}\b', body):
        return None
    return dict(start=start, end=end, label=label.start(), counter=counter, limit=limit, sides=sides, exit=exit_text)


def _loop(source, run, counter):
    """The `for` text that replaces one run, indented as its first deleted statement was."""
    line = source.rfind('\n', 0, run['start']) + 1
    indent = re.match(r'[ \t]*', source[line:]).group()
    sides = [re.sub(rf'\[{run["counter"]}\]', f'[{counter}]', side) for side in run['sides']]
    exit_text = re.sub(rf'(?<![\w.>]){run["counter"]}\b', counter, run['exit'])
    inner = ''.join(f'{indent}        {row.strip()}\n' for row in exit_text.splitlines() if row.strip())
    return (f'for ({counter} = 0; {counter} < {run["limit"]}; {counter}++) {{\n'
            f'{indent}    if ({sides[0]} != {sides[1]}) {{\n{inner}{indent}        break;\n'
            f'{indent}    }}\n{indent}}}')


def _owned(part, run):
    """Whether the counter is mentioned only by its declaration outside the run."""
    outside = part.clean[part.opening:run['start']] + part.clean[run['end']:part.end]
    return len(re.findall(rf'(?<![\w.>]){run["counter"]}\b', outside)) == 1


def _declaration(part, local):
    return re.search(rf'(?m)^[ \t]*(?:unsigned\s+|signed\s+)?{IDENT}\s+{local}\s*;[ \t]*\n',
                     part.clean[part.opening:part.end])


def _write(part, runs, shared):
    edits = [(run['start'], run['end'], _loop(part.source, run, shared or run['counter'])) for run in runs]
    if shared:
        for other in {run['counter'] for run in runs} - {shared}:
            declared = _declaration(part, other)
            if declared:
                edits.append((part.opening + declared.start(), part.opening + declared.end(), ''))
    return edit(part.source, edits)


def variants(source, name):
    part = view(source, name)
    if not part or 'goto' not in part.body:
        return []
    runs = []
    for label in _LABEL.finditer(part.clean, part.opening, part.end):
        run = _run(part, name, label)
        if run and (not runs or runs[-1]['end'] <= run['start']):
            runs.append(run)
    if not runs:
        return []
    out = []
    if len(runs) > 1 and len({run['counter'] for run in runs}) > 1 and all(_owned(part, run) for run in runs):
        out.append((SHARED, _write(part, runs, runs[0]['counter'])))
    out.append((FAMILY, _write(part, runs, None)))
    if len(runs) > 1:
        out += [(FAMILY, _write(part, [run], None)) for run in runs[:4]]
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
