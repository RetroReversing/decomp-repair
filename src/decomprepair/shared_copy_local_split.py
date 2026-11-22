"""A local copied from a different call result in each arm: the arms read the call result directly.

m2c reuses one name for values that are unrelated: `var_s4 = temp_v0_2;` in one arm and `var_s4 = temp_v0_3;` in
another, each arm then passing `var_s4` to the same later call. The reuse makes one pseudo register with several
definitions, and in KMC GCC 2.7.2 that changes both when the copy out of the call's return register is scheduled and
which hard register it receives (hypothesis, not confirmed in the compiler source: reload and global allocation treat a
multiply-set pseudo as one live range spanning the arms, while the original's separate locals are separate ones).

On an 842-instruction N64 lit-actor drawer (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`, scoring 2) the two arms
that shared `var_s4` went from 7467 to 6442 with the copies removed and each arm reading its own call result, and the
rows of both arms (the copy's place after the call, its register, the temporaries around it) matched.

`shared_copy_local_direct` offers, for a local assigned by `V = T;` (T a local that is assigned exactly once, by a call)
in two or more different blocks, the function with every such copy removed and every read of V that follows a copy in
the same block reading that copy's T instead. A local with a read outside every copy's block is left alone. The
judge decides.
"""
import re

from .declaration_scope_sink_repairs import _blocks, _innermost
from .integer_repair_support import IDENT, edit, view

FAMILY = 'shared_copy_local_direct'
FAMILIES = (FAMILY,)
LIMIT = 4
COPY = re.compile(rf'(?<![\w.>])(?P<v>{IDENT})\s*=\s*(?P<t>{IDENT})\s*;')
CALL_RESULT = re.compile(rf'(?<![\w.>])(?P<t>{IDENT})\s*=\s*{IDENT}\s*\(')


def _once_by_call(body, local):
    assigns = list(re.finditer(rf'(?<![\w.>]){re.escape(local)}\s*=(?!=)', body))
    calls = list(re.finditer(rf'(?<![\w.>]){re.escape(local)}\s*=\s*{IDENT}\s*\(', body))
    return len(assigns) == 1 and len(calls) == 1


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    start, end = part.opening + 1, part.end
    body = clean[start:end]
    blocks = [block for block in _blocks(clean, part.opening, end) if block[0] > part.opening]
    copies = {}
    for hit in COPY.finditer(clean, start, end):
        copies.setdefault(hit['v'], []).append(hit)
    result = []
    for local, hits in copies.items():
        sources = {hit['t'] for hit in hits}
        if len(hits) < 2 or local in sources or not all(_once_by_call(body, t) for t in sources):
            continue
        copy_starts = {hit.start() for hit in hits}
        if any(start + hit.start() not in copy_starts
               for hit in re.finditer(rf'(?<![\w.>]){re.escape(local)}\s*=(?!=)', body)):
            continue  # assigned some other way too
        holders = [_innermost(blocks, [hit.start()]) for hit in hits]
        if None in holders or len(set(holders)) < 2:
            continue
        copy_spans = {(hit.start(), hit.end()) for hit in hits}
        declared = [(start + d.start(), start + d.end())
                    for d in re.finditer(rf'(?m)^[ \t]*(?:{IDENT}[\s*]+)+{re.escape(local)}\s*;', body)]
        edits, ok = [(a, b, '') for a, b in copy_spans], True
        for use in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', body):
            position = start + use.start()
            if any(a <= position < b for a, b in copy_spans | set(declared)):
                continue
            owners = [(hit.end(), hit['t']) for hit, holder in zip(hits, holders)
                      if holder[0] < position < holder[1] and hit.end() <= position]
            if not owners:
                ok = False
                break
            edits.append((position, position + len(local), max(owners)[1]))
        if ok and len(edits) > len(copy_spans):
            result.append((FAMILY, edit(source, edits)))
    return result[:LIMIT]
