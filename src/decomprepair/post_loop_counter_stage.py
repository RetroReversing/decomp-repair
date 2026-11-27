"""An accumulator read after its loop, staged in the loop's counter: `i = sum & 0xFF; if (i != expect)`.

    sum = 0;
    for (i = 0; i < n; i++) { sum += buf[i]; }
    if ((sum & 0xFF) != expect) { .. }          ->          i = sum & 0xFF;
                                                            if (i != expect) { .. }

The target had the accumulator's zero first and the counter's zero in the delay slot of the loop's entry test
(`move $v1,$zero; andi; move $a0,$v0; blez $v0; move $s0,$zero`); every spelling of the two initialisations (either
order, one statement, in the `for` header, a `while`) gave them the other way round. Read in gcc 2.7.2's cse.c
(`make_regs_eqv`, via `insert_regs`): the second register set to 0 joins the first one's quantity, and the canonical
register of a quantity is the one whose last mention comes latest. The accumulator, read after the loop, outlives the
counter, so cse rewrites the copied entry test `i < n` to `sum < n`, and combine then moves `sum = 0` (not `i = 0`) next
to the branch, where reorg puts it in the delay slot. A later mention of the counter makes it canonical; the C that does
that is the post-loop read of the accumulator kept in the counter (no instruction more: the counter is dead there).
Matched a checksum check on an N64 game (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O1 -g`), 5 -> 0, and 10 -> 0 after
`accumulate_separate_dest`; the two edits are independent (15 -> 5 alone).

Children (`post_loop_counter_stage`, bounded): for each `for (C = 0; ...)` loop over an integer local `C` whose body
updates an integer local `A` (`A op= E`, or `A = ... A ...`), the statement right after the loop that reads `A` while
the rest of the function never reads `C` again before setting it: that statement with `A`'s read staged in `C` just
before it. The masked read (`A & K`, the parentheses around it if any) is staged first, then the bare `A`. A candidate
rewrite; the exact judge decides."""
import re

from .integer_repair_support import DECL, IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'post_loop_counter_stage'
FAMILIES = (FAMILY,)
LIMIT = 6
WORD = re.compile(r'(?:[su]32|int|unsigned\s+int|signed\s+int)$')
FOR_ZERO = re.compile(rf'\bfor\s*\(\s*(?P<c>{IDENT})\s*=\s*0\s*[;,]')


def _mentions(name):
    return re.compile(rf'(?<![\w.>]){re.escape(name)}\b')


def _updated(body, acc):
    """`acc` is updated from itself in the loop: `acc op= E`, or set there and read there too (`acc = acc + E`, or
    accumulate_separate_dest's `t = E + acc; acc = t;`)."""
    name = re.escape(acc)
    if re.search(rf'(?<![\w.>]){name}\s*[-+*&|^]=', body):
        return True
    sets = list(re.finditer(rf'(?<![\w.>]){name}\s*=(?!=)', body))
    if not sets:
        return False
    starts = {hit.start() for hit in sets}
    return any(hit.start() not in starts for hit in _mentions(acc).finditer(body))


def _counter_dead_after(clean, start, end, counter):
    """The counter is not read in clean[start:end] before it is set again (or at all)."""
    hit = _mentions(counter).search(clean, start, end)
    if not hit:
        return True
    return bool(re.match(r'\s*=(?!=)', clean[hit.end():end]))


def _reads(statement, acc):
    """The spans of `acc`'s read in `statement` to stage: `(acc & K)` / `acc & K` first, then `acc`."""
    name = re.escape(acc)
    found = []
    masked = re.search(rf'\(\s*{name}\s*&\s*(?:0[xX][0-9a-fA-F]+|\d+)[uU]?\s*\)', statement)
    if masked:
        found.append((masked.start(), masked.end(), statement[masked.start() + 1:masked.end() - 1].strip()))
    else:
        masked = re.search(rf'(?<![\w.>]){name}\s*&\s*(?:0[xX][0-9a-fA-F]+|\d+)[uU]?\b', statement)
        if masked:
            found.append((masked.start(), masked.end(), masked.group(0).strip()))
    bare = [hit for hit in _mentions(acc).finditer(statement)]
    if len(bare) == 1:
        found.append((bare[0].start(), bare[0].end(), acc))
    return found


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, source = part.clean, part.source
    body = clean[part.opening:part.end]
    words = {hit['name'] for hit in DECL.finditer(body) if WORD.match(hit['type'].strip())}
    out, seen = [], set()
    for loop in FOR_ZERO.finditer(clean, part.opening, part.end):
        counter = loop['c']
        if counter not in words:
            continue
        header_end = close(clean, loop.start() + loop.group(0).index('('))
        if not header_end:
            continue
        brace = re.match(r'\s*{', clean[header_end:part.end])
        if not brace:
            continue
        opening = header_end + brace.end() - 1
        loop_end = close(clean, opening, '{', '}')
        if not loop_end or loop_end > part.end:
            continue
        loop_body = clean[opening:loop_end]
        stmt = re.match(r'\s*', clean[loop_end:part.end])
        stmt_start = loop_end + stmt.end()
        stmt_end = re.compile(r'[;{]').search(clean, stmt_start, part.end)
        if not stmt_end:
            continue
        statement = clean[stmt_start:stmt_end.start()]
        if _mentions(counter).search(statement) or statement.lstrip().startswith(('}', 'for', 'while', 'do')):
            continue
        if not _counter_dead_after(clean, stmt_end.start(), part.end - 1, counter):
            continue
        indent = re.search(r'[^\n]*$', source[:stmt_start]).group(0)
        indent = indent if not indent.strip() else ''
        for acc in sorted(words - {counter}):
            if not _mentions(acc).search(loop_body) or not _updated(loop_body, acc):
                continue
            for start, end, expr in _reads(statement, acc):
                text = edit(source, [
                    (stmt_start, stmt_start, f'{counter} = {expr};\n{indent}'),
                    (stmt_start + start, stmt_start + end, counter),
                ])
                if text != source and text not in seen:
                    seen.add(text)
                    out.append((FAMILY, text))
                if len(out) >= LIMIT:
                    return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
