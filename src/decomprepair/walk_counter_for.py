"""A table walk's stepped cursors and byte-stepped counter, written as the counted `for` loop over a plain index.

A saved best that came from m2c's draft (or from a search that kept its shape) walks a record's pointer array and a few
tables with cursors that step beside a counter, and switches on a byte offset that steps by the element size:

    var_s1 = 0; var_s0 = arg0;
    do {
        if (*(void **) ((char *) var_s0 + 0x3E4) == NULL) { ... }
        switch (var_s1) { case 0: case 4: ...; case 8: ... case 20: ...; }
        if (var_s0 == ((2 * 4) + arg0)) { ... }
        var_s1 += 4; var_s0 += 4;
    } while (((u32) var_s1) < 0x18);

The game wrote `for (i = 0; i < 6; i++)` with `slot[i]`, `switch (i)` and `i == 2`. The compiler's own strength
reduction makes the cursors (loop.c turns `i * 4` into the `addiu $s0,$s0,4` and the test into `sltiu $s1,0x18`) and
drops the `sll` a switch on the index would need; a switch on the byte offset has no `sll` to drop, so its table lookup
and the compare of the cursor against `arg0 + 8` came out as other instructions. (A 301-instruction KMC GCC 2.7.2
menu, 1825 -> 0, together with the slot reads written plain, the counter unsigned and each conditional value an
`if`/`else`; each part alone is no better: plain reads without the counter form are folded by cse where the target
reloads.)

Each `do { ... } while (counter < bound)` whose counter starts at 0 and whose stepped companions start at expressions
the loop never assigns is offered as a `for` loop over the counter, with
  * every companion (`v += k`) read as `(INIT + counter * k)`, its initialisation and step dropped (the initialisation
    may be anywhere before the loop in blocks that always run; the steps are top-level statements of the body, and
    nothing after the first of them reads a stepped variable);
  * a counter that steps by K bytes (`c += 4` with bound `0x18`) normalised to the unit counter: bound / K, every
    `case N:` of a `switch (c)` and every `c == N` divided by K (a `case` that is not a multiple of K can never be
    reached and goes), any other read of `c` as `(c * K)`, and a `(u32)` cast on the test kept as the counter's
    declaration (`u32`), which the range check of the switch then follows;
  * `v == (a * S) + INIT` (the companion against the address of element `a`) as `counter == a`;
  * `volatile` dropped from the pointer casts the body reads through (a hypothesis: the search that wrote it wanted the
    reload that the original's typed accesses give anyway).
The counter's own initialisation stays where it was. The `do` form (steps written as the last statements) is a second
child, since a `for` loop's entry test changes the preheader and the frame. The saved best's fences and scaffolding
are written out first, as `scaffold_strip` does, when the source has them."""
import re

from . import scaffold_strip
from .counter_companion_repairs import COUNT, STEP
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'walk_counter_for'
MERGE = 'walk_counter_merge'
FAMILIES = (FAMILY, MERGE)

IDENT = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][\da-fA-F]+|\d+)'
COND = re.compile(r'^[\s(]*(?P<cast>\(\s*u32\s*\)\s*)?(?P<counter>' + IDENT + r')[\s)]*<\s*(?P<bound>' + NUM
                  + r')(?P<u>[uU])?[\s)]*$')


def _number(text):
    return int(text.strip().rstrip('uUlL'), 0)


def _top_statements(clean, lo, hi):
    """[(start, end)] of the `;`-terminated statements of clean[lo:hi] at its own level (nested blocks skipped)."""
    out, depth, begin = [], 0, lo
    for pos in range(lo, hi):
        char = clean[pos]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                begin = pos + 1
        elif char == ';' and depth == 0:
            out.append((begin, pos + 1))
            begin = pos + 1
    return out


def _always_runs(clean, opening, at, loop_start):
    """True when the statement at `at` is reached whenever the loop is: every block that encloses it also encloses
    the loop, or is a bare block (opened after `;`, `{` or `}`)."""
    stack = []
    for pos in range(opening, at):
        if clean[pos] == '{':
            stack.append(pos)
        elif clean[pos] == '}':
            stack.pop()
    for brace in stack:
        end = close(clean, brace, '{', '}')
        bare = clean[:brace].rstrip()[-1:] in (';', '{', '}')
        if not bare and not (end and end > loop_start):
            return False
    return True


def _removal(clean, a, b):
    line = clean.rfind('\n', 0, a) + 1
    tail = re.match(r'[ \t]*(?:\n|$)', clean[b:])
    if not clean[line:a].strip() and tail:
        return line, b + tail.end()
    return a, b


def _no_volatile(text):
    return re.sub(r'\*\s*volatile\s*\*', '**', text)


def _plan(source, clean, opening, end, loop):
    """What it takes to rewrite one `do` loop, or None: the text of the new body and the spans to drop."""
    start, body_open, body_end, cond_open, cond_end = loop
    cond = COND.match(clean[cond_open + 1:cond_end - 1])
    if not cond:
        return None
    counter, cast, bound = cond['counter'], cond['cast'], _number(cond['bound'])
    suffix = 'U' if cond['u'] else ''
    lo, hi = body_open + 1, body_end - 1
    body = clean[lo:hi]
    steps = []
    for a, b in _top_statements(clean, lo, hi):
        text = clean[a:b].strip()
        count, step = COUNT.fullmatch(text), STEP.fullmatch(text)
        if count:
            steps.append((a, b, count['a'] or count['b'], 1, True))
        elif step:
            steps.append((a, b, step['name'] or step['name2'], _number(step['stride'] or step['stride2']), False))
    names = [s[2] for s in steps]
    if counter not in names or len(set(names)) != len(names):
        return None
    first = min(s[0] for s in steps)
    after = clean[first:hi]
    for a, b, *_ in steps:
        after = after[:a - first] + ' ' * (b - a) + after[b - first:]
    if any(re.search(r'(?<![\w.>])' + n + r'\b', after) for n in names):
        return None
    stride = next(s[3] for s in steps if s[2] == counter)
    if bound % stride or bound // stride < 1:
        return None
    bound //= stride
    inits = {}
    for name in names:
        hits = [h for h in re.finditer(r'(?<![\w.>])' + name + r'\s*=(?!=)\s*(?P<value>[^;{}]+);', clean[opening:start])
                if _always_runs(clean, opening, opening + h.start(), start)]
        if not hits:
            return None
        inits[name] = hits[-1]
    zero = inits[counter]['value'].strip()
    if not re.fullmatch(NUM + r'[uU]?', zero) or _number(zero) != 0:
        return None
    ahead = clean[cond_end:end]
    companions = {}
    for name in names:
        if name == counter:
            continue
        step = next(s for s in steps if s[2] == name)
        value = inits[name]['value'].strip()
        gap = clean[opening + inits[name].end():start]
        touched = gap + clean[lo:hi]
        if (re.search(r'(?<![\w.>])' + name + r'\b', ahead + gap)
                or re.search(r'&\s*' + name + r'\b', clean[opening:end])
                or re.search(r'(?<![\w.>])' + name + r'\b', clean[cond_open:cond_end])
                or any(re.search(r'(?<![\w.>])' + re.escape(i) + r'\s*(?:[-+*/&|^%]|<<|>>)?=(?!=)|(?:\+\+|--)\s*'
                                 + re.escape(i) + r'\b|\b' + re.escape(i) + r'\s*(?:\+\+|--)', touched)
                       for i in set(re.findall(IDENT, value)))):
            return None
        companions[name] = (value, step[3])
    edits = [(a - lo, b - lo, '') for a, b, *_ in steps]
    for name, (value, step) in companions.items():
        taken = []
        around = rf'\(\s*(?P<a>{NUM})\s*\*\s*{step}\s*\)'
        for pattern in (rf'(?<![\w.>]){name}\s*(?P<op>[=!]=)\s*\(\s*{around}\s*\+\s*{re.escape(value)}\s*\)',
                        rf'(?<![\w.>]){name}\s*(?P<op>[=!]=)\s*\(\s*{re.escape(value)}\s*\+\s*{around}\s*\)',
                        rf'(?<![\w.>]){name}\s*(?P<op>[=!]=)\s*\(\s*{re.escape(value)}\s*\+\s*(?P<a>{NUM})\s*\)' if step == 1
                        else r'(?!)'):
            for hit in re.finditer(pattern, body):
                if not any(t[0] < hit.end() and hit.start() < t[1] for t in taken):
                    taken.append((hit.start(), hit.end(), f'{counter} {hit["op"]} {_number(hit["a"])}'))
        edits += taken
        scaled = f'{counter} * {step}' if step != 1 else counter
        value_text = value if re.fullmatch(IDENT, value) else f'({value})'
        for use in re.finditer(r'(?<![\w.>])' + name + r'\b', body):
            if not any(t[0] <= use.start() < t[1] for t in taken) \
                    and not any(a - lo <= use.start() < b - lo for a, b, *_ in steps):
                edits.append((use.start(), use.end(), f'({value_text} + {scaled})'))
    if stride != 1:
        covered = []
        for hit in re.finditer(r'\bswitch\s*\(\s*' + counter + r'\s*\)\s*\{', body):
            switch_end = close(body, hit.end() - 1, '{', '}')
            covered.append((hit.start(), hit.end()))
            depth = 0
            for label in re.finditer(r'[{}]|\bcase\s+(?P<n>' + NUM + r')\s*:', body[hit.end() - 1:switch_end]):
                if label.group() == '{':
                    depth += 1
                elif label.group() == '}':
                    depth -= 1
                elif depth == 1:
                    n, at = _number(label['n']), hit.end() - 1 + label.start()
                    edits.append((at, hit.end() - 1 + label.end(), f'case {n // stride}:' if n % stride == 0 else ''))
        for hit in re.finditer(r'(?<![\w.>])' + counter + r'\s*(?P<op>[=!]=)\s*(?P<n>' + NUM + r')\b|\b(?P<m>' + NUM
                               + r')\s*(?P<op2>[=!]=)\s*' + counter + r'\b', body):
            n = _number(hit['n'] or hit['m'])
            if n % stride:
                return None
            covered.append((hit.start(), hit.end()))
            edits.append((hit.start(), hit.end(), f'{counter} {hit["op"] or hit["op2"]} {n // stride}'))
        for use in re.finditer(r'(?<![\w.>])' + counter + r'\b', body):
            if not any(a <= use.start() < b for a, b in covered) \
                    and not any(a - lo <= use.start() < b - lo for a, b, *_ in steps):
                edits.append((use.start(), use.end(), f'({counter} * {stride})'))
    edits.sort(key=lambda e: (e[0], -(e[1] - e[0])))
    text, kept, last = source[lo:hi], [], -1
    for a, b, v in edits:
        if a >= last:
            kept.append((a, b, v))
            last = b
    for a, b, v in sorted(kept, reverse=True):
        text = text[:a] + v + text[b:]
    drops = [(opening + inits[n].start(), opening + inits[n].end()) for n in companions]
    return counter, cast, bound, suffix, _no_volatile(text), drops


def _unsigned(source, counter):
    return re.sub(r'(?m)^([ \t]*)(?:long|s32|int|signed|unsigned)\b[ \t]+' + counter + r'[ \t]*;', r'\1u32 ' + counter + ';',
                  source, count=1)


def _rewrite(source, name, as_for):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return None
    edits, counters = [], []
    for hit in re.finditer(r'\bdo\s*\{', clean[opening:end]):
        start, body_open = opening + hit.start(), opening + hit.end() - 1
        body_end = close(clean, body_open, '{', '}')
        tail = re.match(r'\s*while\s*\(', clean[body_end:end]) if body_end else None
        if not tail:
            continue
        cond_open = body_end + tail.end() - 1
        cond_end = close(clean, cond_open)
        semi = re.match(r'\s*;', clean[cond_end:end]) if cond_end else None
        if not semi:
            continue
        plan = _plan(source, clean, opening, end, (start, body_open, body_end, cond_open, cond_end))
        if not plan:
            continue
        counter, cast, bound, suffix, body, drops = plan
        test = f'{"(u32) " if cast else ""}{counter} < {bound}{suffix}'
        if as_for:
            edits += [(start, body_open, f'for (; {test}; {counter}++) '), (body_open + 1, body_end - 1, body),
                      (body_end - 1, cond_end + semi.end(), '}')]
        else:
            edits += [(body_open + 1, body_end - 1, body + f'\n{counter} += 1;\n'), (cond_open + 1, cond_end - 1, test)]
        edits += [(*_removal(clean, a, b), '') for a, b in drops]
        counters.append((counter, cast))
    if not edits:
        return None
    ordered = sorted(edits)
    if any(a1 < b0 for (_, b0, _), (a1, _, _) in zip(ordered, ordered[1:])):
        return None
    text = source
    for a, b, v in sorted(edits, reverse=True):
        text = text[:a] + v + text[b:]
    for counter, cast in counters:
        if cast:
            text = _unsigned(text, counter)
    return text if text != source else None


SCRATCH = re.compile(r'(?P<v>' + IDENT + r')\s*=\s*(?P<expr>[^;{}=]+?)\s*;\s*(?P<w>' + IDENT + r')\s*=\s*(?P=v)\s*(?P<op>[-+])\s*(?P<k>'
                     + NUM + r')\s*;')


def _inline_scratch(source, name):
    """`v = a * 2; w = v - K;` where `v` (another web of a name the walks use as a counter) is read nowhere after it:
    `w = a * 2 - K;`, so the counter's name is free of the scratch."""
    span = find(source, name)
    clean = _blank(source)
    if not span:
        return None
    text = source
    for hit in reversed(list(SCRATCH.finditer(clean, span[0], span[1]))):
        later = clean[hit.end():span[1]]
        if hit['v'] == hit['w'] or re.search(r'(?<![\w.>])' + hit['v'] + r'\b', later) \
                or re.search(r'&\s*' + hit['v'] + r'\b', clean[span[0]:span[1]]):
            continue
        text = text[:hit.start()] + f'{hit["w"]} = {hit["expr"].strip()} {hit["op"]} {hit["k"]};' + text[hit.end():]
    return text if text != source else None


def _unify(source, name):
    """The counters of the rewritten loops merged into one variable: each is set to 0 right before its own loop and
    named nowhere else, so one `u32` can serve them all (more references, so a higher priority in the allocator)."""
    span = find(source, name)
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1]) if span else -1
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return None
    loops = []
    for hit in re.finditer(r'\bfor\s*\(\s*;\s*(?:\(u32\)\s*)?(?P<c>' + IDENT + r')\s*<\s*' + NUM + r'U?\s*;\s*(?P=c)\+\+\s*\)\s*\{',
                           clean[opening:end]):
        body_open = opening + hit.end() - 1
        loop_end = close(clean, body_open, '{', '}')
        init = None
        for found in re.finditer(r'(?<![\w.>])' + hit['c'] + r'\s*=\s*0U?\s*;', clean[opening:opening + hit.start()]):
            init = found
        if loop_end and init:
            loops.append((hit['c'], opening + init.start(), loop_end, '(u32)' in hit.group().replace(' ', '')))
    eligible = []
    for counter, init, loop_end, unsigned in loops:
        outside = [m for m in re.finditer(r'(?<![\w.>])' + counter + r'\b', clean[opening:end])
                   if not init <= opening + m.start() < loop_end]
        if all(re.match(r'[ \t]*;|[ \t]*\n', clean[opening + m.end():]) and re.search(
                r'(?m)^[ \t]*[A-Za-z_][\w ]*[ \t]' + counter + r'[ \t]*;[ \t]*$', clean[clean.rfind('\n', 0, opening + m.start()) + 1:
                                                                                      clean.find('\n', opening + m.start())])
               for m in outside):
            eligible.append((counter, init, loop_end, unsigned))
    if len(eligible) < 2 or len({e[0] for e in eligible}) < len(eligible):
        return None
    canonical = eligible[0][0]
    text = source
    for counter, init, loop_end, unsigned in sorted(eligible[1:], key=lambda e: -e[1]):
        text = text[:init] + re.sub(r'(?<![\w.>])' + counter + r'\b', canonical, text[init:loop_end]) + text[loop_end:]
    for counter, *_ in eligible[1:]:
        text = re.sub(r'(?m)^[ \t]*[A-Za-z_][\w ]*[ \t]' + counter + r'[ \t]*;[ \t]*\n', '', text, count=1)
    if any(e[3] for e in eligible):
        text = _unsigned(text, canonical)
    return text if text != source else None


def variants(source, name, header=''):
    out, seen = [], {source}
    stripped = scaffold_strip.plain(source, name, header)
    for text in ([stripped] if stripped else []) + [source]:
        for as_for in (True, False):
            child = _rewrite(text, name, as_for)
            if child and child not in seen:
                seen.add(child)
                out.append((FAMILY, child))
                tidy = _inline_scratch(child, name) if as_for else None
                merged = _unify(tidy or child, name) if as_for else None
                if merged and merged not in seen:
                    seen.add(merged)
                    out.append((FAMILY, merged))
    # the same two steps on a source whose loops are already counted `for` loops (the greedy chain's second step: the
    # first step's cheapest child keeps one counter per loop, and the merged one is only a better program together)
    tidy = _inline_scratch(source, name)
    for text in [tidy] if tidy else []:
        if text not in seen:
            seen.add(text)
            out.append((MERGE, text))
    merged = _unify(tidy or source, name)
    if merged and merged not in seen:
        out.append((MERGE, merged))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 120}
