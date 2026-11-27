"""Stores at consecutive indexes through a pointer, written with the first ones stepping the pointer (`*p++ = a;`).

m2c folds a post-increment into the offsets of the stores after it, so a file extension appended with `*p++ = 'P';
p[0] = 'A'; p[1] = 'K';` reads `p[0] = 'P'; p[1] = 'A'; p[2] = 'K';`. The program is the same when `p` is not used again,
but the target keeps the `addiu` between the stores: an N64 asset loader (sn-n64-281 GCC 2.8.1, 229 instructions) went
710 -> 0 with the first store stepping the pointer.

`variants` finds runs of two or more statements `p[k] = ..;` (`*p` for `p[0]`) with consecutive `k` from 0, `p` a pointer
local that nothing names after the run, with no loop around the run and no `goto` after it. One child steps the pointer
at the first store, one at every store but the last.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'store_run_post_increment'
FAMILIES = (FAMILY,)
LIMIT = 6
STORE = re.compile(rf'(?:\*\s*(?P<star>{IDENT})|(?<![\w.>])(?P<p>{IDENT})\s*\[\s*(?P<k>0x[0-9A-Fa-f]+|\d+)\s*\])'
                   r'\s*=(?!=)\s*(?P<value>[^;{}=]+);')


def _in_loop(clean, opening, position):
    """Whether a brace block around `position` is a loop's body."""
    stack = []
    for i in range(opening + 1, position):
        if clean[i] == '{':
            head = clean[max(opening, i - 200):i].rstrip()
            stack.append(bool(re.search(r'\bdo\Z', head) or
                              re.search(r'\b(?:for|while)\s*\([^{}]*\)\Z', head)))
        elif clean[i] == '}' and stack:
            stack.pop()
    return any(stack)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = _blank(source)
    hits = list(STORE.finditer(clean, part.opening, part.end))
    out, taken = [], 0
    for first in range(len(hits)):
        if first < taken:
            continue
        pointer = hits[first]['p'] or hits[first]['star']
        run = [hits[first]]
        for hit in hits[first + 1:]:
            index = int(hit['k'], 0) if hit['k'] else 0
            if (hit['p'] or hit['star']) != pointer or index != len(run) or clean[run[-1].end():hit.start()].strip():
                break
            run.append(hit)
        if len(run) < 2 or (run[0]['k'] and int(run[0]['k'], 0)):
            continue
        taken = first + len(run)
        word = re.compile(rf'(?<![\w.>]){re.escape(pointer)}\b')
        if not re.search(rf'\b{IDENT}\s*\*\s*{re.escape(pointer)}\s*[;=]', clean[part.opening:run[0].start()]):
            continue
        if not re.search(r'(?:\A|[;{}:])\s*\Z', clean[:run[0].start()]):
            continue
        if any(word.search(hit['value']) for hit in run):
            continue
        tail = clean[run[-1].end():part.end]
        if word.search(tail) or re.search(r'\bgoto\b', tail) or _in_loop(clean, part.opening, run[0].start()):
            continue
        for steps in dict.fromkeys((1, len(run) - 1)):
            edits = []
            for index, hit in enumerate(run):
                if index < steps:
                    target = f'*{pointer}++'
                else:
                    target = f'{pointer}[{index - steps}]'
                # from the source, not the blanked text: a character literal's body is blanked there
                value = source[clean.index('=', hit.start()) + 1:hit.end() - 1].strip()
                edits.append((hit.start(), hit.end(), f'{target} = {value};'))
            out.append((FAMILY, edit(source, edits)))
        if len(out) >= LIMIT:
            break
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 900}
