"""A run of `if (v == K) { ...; break; }` guards on one value, and the code after them, written as the `switch` it was.

    case 1:
        r = check(o);
        if (r == 1) { o->state = 3; start(o, 0x36); break; }
        if (r == 2) { start(o, 0x35); o->state = 3; break; }
        switch (o->sub) { ... }
        break;
 -> case 1:
        switch (check(o)) {
        case 1: o->state = 3; start(o, 0x36); break;
        case 2: start(o, 0x35); o->state = 3; break;
        default:
            switch (o->sub) { ... }
            break;
        }
        break;

Each guard leaves its region (`break` out of the enclosing `switch`, or `return` at the end of a function), so the run
means the same as a `switch` whose `default:` is the rest of the region. The two compile differently: GCC expands a
`switch`'s compare chain at its end (`expand_end_case`), and with the guards written as `if`s, cse (following jumps,
-O2) saw the tests' constants `1` and `2` beside the later `o->sub = 1;` store of the same constant in the extended
basic block, and kept them in saved registers across the calls (hypothesis: read from the dumps' effect, not from
cse.c). A 376-instruction enemy state machine (SN64 GCC 2.8.1, `-G0 -mips3 -O2 -mfp32`) had two such runs on one
call's result in two arms: written as the `switch` it went 2038 -> 40 (the last 40 an order of three stores), and the
cross-jumped arms between the two copies came out as the target's.

`variants` reads every run of two or more adjacent `if (NAME == CONSTANT)` statements (braced, no `else`, distinct
constants, every body ending in the same exit: `break;` when the run sits in a `switch` arm, `return ...;` when it sits
at the end of the function body), and writes the `switch`, the region's rest as its `default:`. In a `switch` arm a
`break;` follows the new `switch`, since the arms' `break`s now leave the inner one. When the name was assigned by the
statement just before the run and is read nowhere else in the function, a second child switches on the assigned
expression itself and drops the assignment (and the declaration, when nothing else names it). With several runs in a
function, one more child of each kind rewrites all of them at once. At most eight children.
"""
import re

from .c_scan import close, enclosing_block, header_before
from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'guard_exit_switch'
FAMILIES = (FAMILY,)
LIMIT = 8
GUARD = re.compile(r'\bif\s*\(\s*(' + IDENT + r')\s*==\s*(' + NUMBER + r')\s*\)\s*\{')
TOKENS = re.compile(r'[{}]|\bcase\b[^:;{}]*:|\bdefault\s*:')


def _guard(clean, at):
    """The guard starting at `at`: (name, constant, body start, body end, exit kind, end past the `}`), or None."""
    hit = GUARD.match(clean, at)
    if not hit:
        return None
    opening = hit.end() - 1
    closing = close(clean, opening)
    if closing < 0:
        return None
    body = clean[opening + 1:closing].rstrip()
    if re.match(r'\s*else\b', clean[closing + 1:]):
        return None
    last = re.search(r'(?:^|[;{}])\s*(break\s*;|return\b[^;{}]*;)$', body)
    if not last:
        return None
    kind = 'break' if last[1].startswith('break') else 'return'
    return hit[1], hit[2].replace(' ', ''), opening + 1, closing, kind, closing + 1


def _region_end(clean, at, limit):
    """Where the region holding position `at` ends: the next `case`/`default` label or the `}` of its block."""
    depth = 0
    for hit in TOKENS.finditer(clean, at, limit):
        token = hit[0]
        if token == '{':
            depth += 1
        elif token == '}':
            if depth == 0:
                return hit.start(), False
            depth -= 1
        elif depth == 0:
            return hit.start(), True
    return limit, False


def _indent(source, at):
    line = source[source.rfind('\n', 0, at) + 1:at]
    return re.match(r'[ \t]*', line).group(0)


def _runs(part):
    clean = part.clean
    runs, seen = [], set()
    for hit in GUARD.finditer(clean, part.opening, part.end):
        start = hit.start()
        if start in seen:
            continue
        before = clean[:start].rstrip()
        if not before or before[-1] not in ';{}:' or re.search(r'\belse$', before):
            continue
        guards, at = [], start
        while True:
            one = _guard(clean, at)
            if not one or (guards and (one[0] != guards[0][0] or one[4] != guards[0][4])):
                break
            if any(one[1] == other[1] for other in guards):
                break
            guards.append(one)
            seen.add(at)
            at = len(clean) - len(clean[one[5]:].lstrip())
        if len(guards) < 2:
            continue
        name, kind = guards[0][0], guards[0][4]
        opening = enclosing_block(clean, start, part.opening)
        if opening < 0:
            continue
        tail_end, labelled = _region_end(clean, guards[-1][5], part.end)
        if kind == 'break':
            if not re.match(r'switch\s*\(', header_before(clean, opening)):
                continue
        elif opening != part.opening or labelled or tail_end != close(clean, part.opening):
            continue
        if re.search(r'\b' + re.escape(name) + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + re.escape(name) + r'\b'
                     r'|\b' + re.escape(name) + r'\s*(?:\+\+|--)', ''.join(clean[g[2]:g[3]] for g in guards)):
            continue
        runs.append((start, guards, tail_end, kind))
    return runs


def _block_text(source, lo, hi, indent):
    lines = [line.rstrip() for line in source[lo:hi].split('\n')]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    width = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
    return '\n'.join(indent + line[width:] if line.strip() else '' for line in lines)


def _assignment(part, start, name):
    """The `name = EXPR;` statement just before `start` whose value has a call: (start, end, EXPR), or None."""
    clean = part.clean
    before = clean[:start].rstrip()
    if not before.endswith(';'):
        return None
    head = max(before.rfind(';', 0, len(before) - 1), before.rfind('{', 0, len(before) - 1),
               before.rfind('}', 0, len(before) - 1), before.rfind(':', 0, len(before) - 1))
    statement = clean[head + 1:len(before)]
    hit = re.match(r'\s*' + re.escape(name) + r'\s*=(?!=)\s*(.+);$', statement, re.S)
    if not hit or '(' not in hit[1] or not re.search(IDENT + r'\s*\(', hit[1]):
        return None
    lo = head + 1 + hit.start(1)
    return head + 1 + (len(statement) - len(statement.lstrip())), len(before), part.source[lo:head + 1 + hit.end(1)].strip()


def _rewrite(part, run, inline):
    source = part.source
    start, guards, tail_end, kind = run
    name = guards[0][0]
    indent = _indent(source, start)
    head, edits = name, []
    if inline:
        found = _assignment(part, start, name)
        if not found:
            return None
        lo, hi, expression = found
        if any(re.search(r'\b' + re.escape(name) + r'\b', part.clean[lo:hi])
               for lo, hi in [(g[2], g[3]) for g in guards] + [(guards[-1][5], tail_end)]):
            return None
        line = source.rfind('\n', 0, lo) + 1
        if not source[line:lo].strip() and source[hi:hi + 1] == '\n':
            lo, hi = line, hi + 1
        head = expression
        edits.append((lo, hi, ''))
    lines = [f'switch ({head}) {{']
    for guard in guards:
        lines.append(f'{indent}case {guard[1]}:')
        lines.append(_block_text(source, guard[2], guard[3], indent + '    '))
    rest = _block_text(source, guards[-1][5], tail_end, indent + '    ')
    lines.append(f'{indent}default:')
    if rest:
        lines.append(rest)
    lines.append(f'{indent}}}')
    if kind == 'break':
        lines.append(f'{indent}break;')
    trailing = source[guards[-1][5]:tail_end]
    keep = trailing[len(trailing.rstrip()):]
    edits.append((start, tail_end, '\n'.join(lines) + (keep if keep else '\n')))
    return edits


def _drop_unused(source, name, part_name):
    part = view(source, part_name)
    if not part or len(re.findall(r'\b' + re.escape(name) + r'\b', part.clean[part.opening:part.end])) != 1:
        return source
    hit = re.compile(r'\n[ \t]*(?:(?:unsigned|signed|const|volatile)\s+)*' + IDENT + r'\s+' + re.escape(name)
                     + r'\s*;[ \t]*(?=\n)').search(part.clean, part.opening, part.end)
    return edit(source, [(hit.start(), hit.end(), '')]) if hit else source


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    runs = _runs(part)
    if not runs:
        return []
    results, seen = [], {source}

    def offer(edits, names):
        if not edits:
            return
        text = edit(source, edits)
        for local in names:
            text = _drop_unused(text, local, name)
        if text not in seen:
            seen.add(text)
            results.append((FAMILY, text))

    plain = [_rewrite(part, run, False) for run in runs]
    inlined = [_rewrite(part, run, True) for run in runs]
    if len(runs) > 1:
        offer([e for edits in plain for e in edits], ())
        if all(inlined):
            offer([e for edits in inlined for e in edits], {run[1][0][0] for run in runs})
    for run, edits, inline_edits in zip(runs, plain, inlined):
        offer(edits, ())
        if inline_edits:
            offer(inline_edits, (run[1][0][0],))
    return results[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
