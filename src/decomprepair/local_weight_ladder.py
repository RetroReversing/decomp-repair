"""A local's own statements wrapped in one-shot scopes several deep, all at once: the weight ladder of one variable.

GCC 2.x hands registers to pseudos in order of `floor_log2(refs) * refs / live length` (global.c), and flow.c counts a
reference once more for every loop it sits in. `do { x = e; } while (0);` is one loop more round the statement, at no
instruction or run-time cost, so it adds one reference to every local the statement names; written three deep it adds
three. `loop_weight_set` wraps the steps of loop locals and `call_weight_ladder` the calls; a function whose registers
are swapped between two locals that have no loop step of their own (a block's size and the pointer to the block carved
from it) is decided by how much weight *one* of them carries, which needs all of that local's statements wrapped
together, deep, and none of those wrappers moves the score alone.

A 110-instruction KMC N64 heap allocator (`-G0 -mips3 -mgp32 -mfp32 -O2`, a free-list walk in a do loop, at 85 with the
registers of a block's size and of the block carved from it exchanged) matched on those rows with the size's three
statements that name the carved pointer's rival (not the pointer) wrapped three, one and three deep (its read of the
block, the end pointer's sum and its re-set), and one unrelated load pinned behind the carve in a scope of its own:
85 -> 15, where each of those edits alone scores the same or worse (that child is the 325th of the 500 offered). Counting the weighted references from the source (a reference is one plus the loop
depth; the `-dl -dg` table agreed) says the size needed 21 references against the carved pointer's 18 to outrank it,
seven more. Those are hypotheses read from the allocation table, not confirmed in the compiler source. The wrappers are
scaffolding no developer wrote; polishing removes them once the match is recorded.

Initialised declarations (`u32 size = block->size;`) cannot be wrapped, so each block's run of leading declarations is
first split into the declarations and then their assignments, in the same order, which changes no code. `variants` then
offers, for each ordered pair of locals that share a statement (v, w), the statements that name v and not w: every depth
one to three for all of them at once, the same with each one a step lighter or at depth one, and the depth-one shapes
with one of the next statements pinned once in a scope of its own, fewest wrappers first. The judge decides, and no
child is a verdict."""
import bisect
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'local_weight_ladder'
FAMILIES = (FAMILY,)
LIMIT = 500
DEPTHS = (1, 2, 3)
PIN_REACH = 4
_KEYWORDS = {'if', 'else', 'while', 'for', 'do', 'switch', 'return', 'goto', 'break', 'continue', 'case', 'default',
             'typedef', 'extern', 'static', 'register', 'sizeof', 'struct', 'union', 'enum'}
_DECL = re.compile(rf'^(?P<indent>[ \t]*)(?P<type>(?:{IDENT}[ \t]+)*{IDENT})(?P<gap>[ \t]*\*+[ \t]*|[ \t]+)'
                   rf'(?P<name>{IDENT})(?:[ \t]*=[ \t]*(?P<init>[^;{{}}]+?))?[ \t]*;[ \t]*$')
_STATEMENT = re.compile(r'(?<=[;{}])(?P<lead>[ \t\r\n]*)(?P<s>[^;{}]+?)\s*;')
_ASSIGN = re.compile(r'(?<![=!<>])(?:[-+*/%&|^]|<<|>>)?=(?!=)')


def _declaration(line):
    """The match of a plain scalar or pointer local declaration on one line, or None."""
    match = _DECL.match(line)
    if not match:
        return None
    words = match['type'].split()
    if set(words) & _KEYWORDS or 'const' in words or 'volatile' in words:
        return None
    init = match['init'] or ''
    if init.lstrip().startswith('{') or (init and _ASSIGN.search(init) and not re.search(r'[=!<>]=', init)):
        return None
    return match


def split_declarations(source, name):
    """The source with each block's run of leading declarations split into `type name;` lines and then the assignments
    of their initialisers, in order; the source itself when there is nothing to split."""
    part = view(source, name)
    if not part:
        return source
    clean = part.clean
    body = clean[part.opening + 1:part.end]
    lines, at = [], part.opening + 1
    for text in body.split('\n'):
        lines.append((at, text))
        at += len(text) + 1
    changes, index = [], 0
    while index < len(lines):
        start, text = lines[index]
        if clean[:start].rstrip()[-1:] != '{' or not _declaration(text):
            index += 1
            continue
        run = []
        while index < len(lines) and _declaration(lines[index][1]):
            run.append((lines[index][0], _declaration(lines[index][1])))
            index += 1
        if not any(m['init'] for _, m in run):
            continue
        pieces = [f"{m['indent']}{m['type']}{m['gap']}{m['name']};" for _, m in run]
        for line_start, m in run:
            if m['init']:
                begin = line_start + m.start('init')
                pieces.append(f"{m['indent']}{m['name']} = {source[begin:begin + len(m['init'])]};")
        last_start, last = run[-1]
        changes.append((run[0][0], last_start + len(lines[[s for s, _ in lines].index(last_start)][1]), '\n'.join(pieces)))
    return edit(source, changes) if changes else source


def _parameters(part):
    head = part.clean[:part.opening]
    signature = head[head.rindex('(') + 1:head.rindex(')')] if '(' in head and ')' in head else ''
    return [m[1] for m in (re.search(rf'({IDENT})\s*(?:\[[^\]]*\])?\s*$', piece) for piece in signature.split(',')) if m]


def units(source, name):
    """([(start, end, text, {local: references})], tracked locals): the statements that assign or call, with the
    references each makes to the function's declared locals and parameters."""
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return [], set()
    clean = part.clean
    tracked = set(_parameters(part))
    for text in clean[part.opening + 1:part.end].split('\n'):
        match = _declaration(text)
        if match:
            tracked.add(match['name'])
    found = []
    for hit in _STATEMENT.finditer(clean, part.opening + 1, part.end):
        text = hit['s']
        first = re.match(IDENT, text.strip())
        if not first or first[0] in _KEYWORDS or re.match(rf'{IDENT}\s*:(?!:)', text.strip()):
            continue
        if _declaration(text.strip() + ';'):
            continue
        if not (_ASSIGN.search(text) or re.match(rf'{IDENT}\s*\(', text.strip()) or re.search(r'\+\+|--', text)):
            continue
        counts = {n: len(re.findall(rf'(?<![\w.>]){re.escape(n)}\b', text)) for n in tracked}
        counts = {n: c for n, c in counts.items() if c}
        if counts:
            found.append((hit.start('s'), hit.end(), source[hit.start('s'):hit.end()], counts))
    return found, tracked


def _wrap(text, depth):
    return 'do { ' * depth + text.strip() + ' } while (0);' * depth


def ladders(found, limit=None):
    """Rank distinct wrapper sets by count, size and positions, retaining only the first `limit` when given.

    The local lane uses at most LIMIT children. A large function can have millions of possible sets, so keeping and
    sorting every discarded set consumed gigabytes before even the first child could be judged. A set outside the
    current best limit can never become one of the best later; keep only the best keys while enumerating.
    """
    names = {n for _, _, _, counts in found for n in counts}
    containing = {name: {i for i, (_, _, _, counts) in enumerate(found) if name in counts} for name in names}
    ranked, selected = [], set()

    def offer(shape, total, pin=None):
        length = len(shape) + (pin is not None)
        cost = total + (pin is not None)
        if limit and len(ranked) >= limit and (cost, length) > ranked[-1][:2]:
            return
        picks = shape if pin is None else {**shape, pin: 1}
        key = tuple(sorted(picks.items()))
        rank = (cost, length, key)
        if rank in selected or (limit and len(ranked) >= limit and rank >= ranked[-1]):
            return
        bisect.insort(ranked, rank)
        selected.add(rank)
        if limit and len(ranked) > limit:
            selected.remove(ranked.pop())

    for v in sorted(names):
        for w in sorted(names - {v}):
            if containing[v].isdisjoint(containing[w]):
                continue
            indexes = sorted(containing[v] - containing[w])
            if not indexes:
                continue
            for depth in DEPTHS:
                shape = {i: depth for i in indexes}
                total = depth * len(indexes)
                offer(shape, total)
                if depth > 1 and len(indexes) > 1:
                    for light in indexes:
                        lighter = {**shape, light: depth - 1}
                        offer(lighter, total - 1)
                        if depth > 2:
                            lighter = {**shape, light: 1}
                            light_total = total - depth + 1
                            offer(lighter, light_total)
                            if not limit or len(ranked) < limit or (light_total + 1, len(indexes) + 1) <= ranked[-1][:2]:
                                pins = sorted({p for i in indexes for p in range(i + 1, min(len(found), i + PIN_REACH + 1))
                                               if p not in lighter})
                                for pin in pins:
                                    offer(lighter, light_total, pin)
    return [(total, dict(key)) for total, _, key in ranked]


def variants(source, name):
    result, seen = [], set()
    split = split_declarations(source, name)
    for base in dict.fromkeys((split, source)):
        found, _ = units(base, name)
        if len(found) < 2:
            continue
        count = LIMIT
        while True:
            shapes = ladders(found, count)
            for _, picks in shapes:
                text = edit(base, [(found[i][0], found[i][1], _wrap(found[i][2], depth)) for i, depth in picks.items()])
                if text not in seen:
                    seen.add(text)
                    result.append((FAMILY, text))
                    if len(result) >= LIMIT:
                        return result
            if len(shapes) < count:
                break
            # Equal edits can collapse to one text. Ask for more ranks until the child limit is filled or exhausted.
            count *= 2

    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 91,
          'lanes': ('beam', 'local')}  # the registry: no caller wiring (registry.py)
