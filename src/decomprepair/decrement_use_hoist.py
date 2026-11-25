"""An update that reads a counter after its decrement written above the decrement, the counter read as `(n - 1)`.

GCC 2.x local-alloc.c ranks the quantities of a block by `floor_log2(refs) * refs / (death - birth)` in the order the
first scheduler left the insns, and gives each the lowest register free over its life: a short-lived value comes first.
A value derived from the decremented counter (`n << 2`) that one statement reads near the top of the block and an
accumulator update reads at the bottom (`offset += texw * (n << 2);`) lives over the whole tail of the block and is
allocated last; the cursor temporaries in between take the registers the target gives it. With the update written
before the decrement, `offset += texw * ((n - 1) << 2);`, the scheduler finishes the product early, the value dies
sooner and takes the first free register. On an N64 texture-strip blitter (SN GCC 2.8.1, `-G0 -mips3 -O2`,
477 instructions) that moved `n << 2` from `$t1` to the target's `$a2` and the cursor temporaries after it (435 -> 370,
13 register rows), and so did moving the block's other reader, `dtdy = ((n - 1) << 12) / strip;`; every placement after
the decrement, and every spelling of the shift, compiled the same.
Which statement the scheduler finishes early is read from the measured output, not confirmed in sched.c.

`variants` takes each `v--;` (`--v;`, `v -= 1;`) and each later statement of the same block that updates another local
(`x = E;`, `x += E;`, ...) with an expression that reads `v` and calls nothing, when nothing between them mentions `x` or
assigns a name the expression reads, and offers the update moved directly above the decrement with every `v` in it read as
`(v - 1)`. The judge decides; no child is a verdict."""
import re

from .integer_repair_support import edit, view
from .local_weight_ladder import _declaration, _parameters

FAMILY = 'decrement_use_hoist'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
LIMIT = 8
DECREMENT = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?:(?P<a>{IDENT})\s*--|--\s*(?P<b>{IDENT})|(?P<c>{IDENT})\s*-=\s*1)\s*;[ \t]*\n')
UPDATE = re.compile(rf'(?P<x>{IDENT})\s*(?P<op>[-+*/%&|^]|<<|>>)?=(?!=)\s*(?P<e>[^;{{}}]+);')


def _mention(name):
    return re.compile(rf'(?<![\w.>]){re.escape(name)}\b')


def _assigns(text, name):
    escaped = re.escape(name)
    return re.search(rf'(?<![\w.>]){escaped}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{escaped}\b'
                     rf'|(?<![\w.>]){escaped}\s*(?:\+\+|--)|&\s*{escaped}\b', text)


def _locals(part):
    names = set(_parameters(part))
    for text in part.clean[part.opening + 1:part.end].split('\n'):
        match = _declaration(text)
        if match:
            names.add(match['name'])
    return names


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, end = part.clean, part.end
    names = _locals(part)
    result, seen = [], set()

    def add(text):
        if text != source and text not in seen:
            seen.add(text)
            result.append((FAMILY, text))

    for dec in DECREMENT.finditer(clean, part.opening + 1, end):
        counter = dec['a'] or dec['b'] or dec['c']
        if counter not in names:
            continue
        mention = _mention(counter)
        depth, at = 0, dec.end()
        block_end = end
        while at < end:  # the end of the decrement's block
            depth += (clean[at] == '{') - (clean[at] == '}')
            if depth < 0:
                block_end = at
                break
            at += 1
        for line in re.finditer(r'(?m)^(?P<indent>[ \t]*)(?P<s>[^\n]*)\n', clean[dec.end():block_end]):
            start = dec.end() + line.start('s')
            update = UPDATE.fullmatch(clean, start, start + len(line['s'].rstrip()))
            if not update:
                continue
            between = clean[dec.end():start]
            if between.count('{') != between.count('}'):
                continue  # the update is inside a nested block
            x, expr = update['x'], update['e']
            if (x == counter or x not in names or not mention.search(expr) or re.search(rf'{IDENT}\s*\(|\+\+|--', expr)
                    or _mention(x).search(between) or _assigns(between, counter)):
                continue
            if any(_assigns(between, ident) for ident in set(re.findall(IDENT, expr)) - {counter}):
                continue
            moved = source[update.start():update.start('e')] + mention.sub(
                f'({counter} - 1)', source[update.start('e'):update.end()])
            line_start = dec.start()
            edits = [(line_start, line_start, f'{dec["indent"]}{moved}\n'),
                     (dec.end() + line.start(), dec.end() + line.end(), '')]
            add(edit(source, edits))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 94,
          'lanes': ('beam', 'local')}  # the registry: no caller wiring (registry.py)
