"""Typed pointers stepped through a table beside a loop counter, written as the table indexed by the counter.

m2c reads a record table through one pointer per field it touches, started from the table's address (often through a
local that holds it) and stepped by the record's size in the pointer's own elements:

    base = &gRecords;
    used = base;
    text = base + 1;
    i = 0;
    for (;;) {
        if (i < 8U) {
            if (*used != 0) f(text, y);
            y += 0xF;
            text += 17;
            used += 17;
            ++i;
            continue;
        }
        break;
    }

The game indexed the table with the counter, and gcc's loop pass made the pointers itself (one derived induction
variable per field, started in the preheader from the table's address: `addiu $s1,$v0,4` ... `move $s0,$v0`). Pointers
of the source's own are set where the source set them and come out in another order and in other registers.

`stride_cursor_index` writes every such pointer as `((T *) START + i * K)` at once and drops its setup and steps, and
the address local when nothing else names it (SN GCC 2.8.1, `-O2`, a 51-instruction N64 menu list: with
`byte_run_struct_copy`, 250 -> 0). Integer companions stay as they are: that loop's own `y` had to stay a counter of
its own (`counter_companion` offers them with the pointers, or one at a time, and only for `do` loops).

What has to hold: the loop is a `do`, `for (;;)` or `while (1)`; the counter is set to 0 before it and stepped by one
in the same run of statements as the pointers; each pointer is a `T *` local, set before the loop from `&SYMBOL`,
`&SYMBOL + N` or an address local (assigned once, with `&SYMBOL`) plus N, and otherwise only read, before the steps,
inside the loop. A candidate only: the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'stride_cursor_index'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uU]?'
_STEP = re.compile(
    rf'(?:(?P<count>{_ID})\s*\+\+|\+\+\s*(?P<count2>{_ID})|(?P<count3>{_ID})\s*\+=\s*1[uU]?'
    rf'|(?P<name>{_ID})\s*\+=\s*(?P<stride>{_NUM}))\s*;')
_LOOP = re.compile(r'\b(?:do|for\s*\(\s*;\s*;\s*\)|while\s*\(\s*1\s*\))\s*\{')
_WRITE = r'(?<![\w.>])(?:{0}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))|(?:\+\+|--)\s*{0}\b)|(?<![&\w])&\s*{0}\b'


def _step_runs(clean, begin, end):
    """Runs of adjacent step statements inside a loop body: [[(start, stop, counter, name, stride)]]."""
    runs, current, last = [], [], None
    for hit in _STEP.finditer(clean, begin, end):
        before = clean[:hit.start()].rstrip()[-1:]
        if before not in (';', '{', '}'):
            continue
        if last is not None and clean[last:hit.start()].strip():
            runs.append(current)
            current = []
        counter = hit['count'] or hit['count2'] or hit['count3']
        current.append((hit.start(), hit.end(), counter, hit['name'], hit['stride']))
        last = hit.end()
    return [*runs, current] if current else runs


def _statement(clean, a, b):
    """The span of a dropped statement: its whole line when nothing else is on it."""
    line = clean.rfind('\n', 0, a) + 1
    tail = re.match(r'[ \t]*(?:\n|$)', clean[b:])
    if not clean[line:a].strip() and tail:
        return line, b + tail.end()
    return a, b


def _declared(clean, opening, end, name):
    """(type, match) of a local `T *name;`."""
    found = re.search(rf'(?m)^[ \t]*(?P<type>[A-Za-z_][\w \t]*?)[ \t]*\*[ \t]*{name}[ \t]*;[ \t]*\n', clean[opening:end])
    return (' '.join(found['type'].split()), (opening + found.start(), opening + found.end())) if found else None


def _single_set(clean, opening, end, name):
    """The one `name = value;` of the function, or None."""
    writes = re.findall(_WRITE.format(name), clean[opening:end])
    hit = re.search(rf'(?<![\w.>]){name}\s*=(?!=)\s*(?P<value>[^;{{}}]+);', clean[opening:end])
    if len(writes) != 1 or not hit:
        return None
    return hit['value'].strip(), (opening + hit.start(), opening + hit.end())


def _start(clean, opening, end, value, aliases):
    """The pointer's start written without the address local: (text, alias name or None)."""
    match = re.fullmatch(rf'(?P<amp>&\s*)?(?P<name>{_ID})(?P<plus>\s*\+\s*{_NUM})?', value)
    if not match:
        return None
    plus = match['plus'] or ''
    if match['amp']:
        return f'&{match["name"]}{plus}', None
    alias = match['name']
    held = _single_set(clean, opening, end, alias)
    declared = _declared(clean, opening, end, alias)
    if not held or not declared or not re.fullmatch(rf'&\s*{_ID}', held[0]):
        return None
    aliases[alias] = (held[1], declared[1])
    symbol = held[0][1:].strip()
    plain = re.search(rf'(?m)^extern\s+{re.escape(declared[0])}\s+{symbol}\b', clean)
    address = f'&{symbol}' if plain else f'({declared[0]} *) &{symbol}'
    return f'{address}{plus}', alias


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    results = []
    for loop in _LOOP.finditer(clean, opening, end):
        body_open = loop.end() - 1
        body_end = close(clean, body_open, '{', '}')
        if not body_end:
            continue
        stop = body_end
        tail = re.match(r'\s*while\s*\(', clean[body_end:end]) if loop[0].startswith('do') else None
        if tail:
            stop = close(clean, body_end + tail.end() - 1) or body_end
        for run in _step_runs(clean, body_open + 1, body_end - 1):
            text = _rewrite(source, clean, opening, end, loop.start(), body_open, stop, run)
            if text and text not in [t for _, t in results]:
                results.append((FAMILY, text))
    return results[:4]


def _classified(clean, opening, end, run):
    """`p += 1` of a pointer local is a pointer's step, not a second counter."""
    return [(a, b, None, counter, '1') if counter and _declared(clean, opening, end, counter) else (a, b, counter, name, stride)
            for a, b, counter, name, stride in run]


def _rewrite(source, clean, opening, end, start, body_open, stop, run):
    # `p += 1` of a pointer local is a pointer's step, not a second counter
    run = _classified(clean, opening, end, run)
    counters = [step for step in run if step[2]]
    if len(counters) != 1:
        return None
    counter = counters[0][2]
    zero = list(re.finditer(rf'(?<![\w.>]){counter}\s*=(?!=)\s*(?P<value>[^;{{}}]+);', clean[opening:start]))
    if (not zero or zero[-1]['value'].strip() not in ('0', '0U', '0u')
            or len(re.findall(_WRITE.format(counter), clean[body_open:stop])) != 1):
        return None
    first = run[0][0]
    edits, aliases, used = [], {}, set()
    for position, finish, _, pointer, stride in run:
        if not pointer:
            continue
        declared = _declared(clean, opening, end, pointer)
        sets = list(re.finditer(rf'(?<![\w.>]){pointer}\s*=(?!=)\s*(?P<value>[^;{{}}]+);', clean[opening:start]))
        if not declared or len(sets) != 1 or len(re.findall(_WRITE.format(pointer), clean[opening:end])) != 2:
            continue
        word = rf'(?<![\w.>]){pointer}\b'
        init = (opening + sets[0].start(), opening + sets[0].end())
        outside = clean[opening:declared[1][0]] + clean[declared[1][1]:init[0]] + clean[init[1]:body_open] + clean[stop:end]
        if re.search(word, outside) or re.search(word, clean[finish:stop]):
            continue
        held = _start(clean, opening, end, sets[0]['value'].strip(), aliases)
        if not held:
            continue
        kind = 'char' if declared[0] == 'void' else declared[0]
        value = f'(({kind} *) ({held[0]}) + {counter} * {stride.rstrip("uU")})'
        for use in re.finditer(word, clean[body_open:first]):
            edits.append((body_open + use.start(), body_open + use.end(), value))
        edits += [(*_statement(clean, position, finish), ''), (*_statement(clean, *init), ''), (*declared[1], '')]
        if held[1]:
            used.add(held[1])
    if not edits:
        return None
    gone = [(a, b) for a, b, _ in edits]
    for alias in used:
        held, declared = aliases[alias]
        spans = [_statement(clean, *held), declared]
        left = [use for use in re.finditer(rf'(?<![\w.>]){alias}\b', clean[opening:end])
                if not any(a <= opening + use.start() < b for a, b in [*gone, *spans])]
        if not left:
            edits += [(a, b, '') for a, b in spans]
    text = source
    for a, b, value in sorted(edits, reverse=True):
        text = text[:a] + value + text[b:]
    return text


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
