"""One statement of a loop body wrapped in one-shot scopes: a weight for the index it shares, at no instruction cost.

`do { S } while (0);` is one loop more round `S` to flow.c, which counts every reference a statement makes once more
for each loop it sits in, and a scheduling fence for the first insn after its notes (sched.c). `local_weight_ladder`
wraps the statements of one *named* local against a rival, all at once. Two things it cannot reach decided a
`gcc-2.7.2-kmc` save-slot reset loop (`-G0 -mips3 -mgp32 -mfp32 -O2`, 430 -> 30 -> 0, both steps measured on the
function's own source with the other edits of `slot_loop_scaffold` applied):

  * the `if (...) { ... }` that holds the three reads of a byte offset kept in a local (`j = i * 4;`): wrapping that
    one compound statement once adds three references to the offset and one to the slot, which is what puts the
    offset's priority above the slot's (`$a0` for the offset, `$a1` for the slot, as the game has them), 430 -> 30;
  * one of the stores through the shared `i * 2` (`D[i] = 0;` after `V[i] = 0;`), wrapped twice: the shared
    index is a compiler temporary no source variable names, so the pairwise ladder never wraps its stores
    alone; its weight decides whether it or the pointer beside it gets `$v0` (30 -> 0).
Neither wrapper moves the score alone in other functions; the judge decides.

Offered for the top-level statements of a `for`, `while` or `do` body that are an `if` (with its `else` chain) or an
indexed store `A[x] = e;` naming a local: one child per statement per depth, `if` statements first, deeper stores
before depth one. A statement with a `continue`, a `break` that would leave the loop, a label or a `case` is left
alone (the extra `do` would catch the `break`). The wrappers are scaffolding no developer wrote; polishing removes them.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .local_weight_ladder import units
from .pattern_repairs import close

FAMILY = 'statement_scope_weight'
FAMILIES = (FAMILY,)
LIMIT = 40
IF_DEPTHS = (1, 2, 3)
STORE_DEPTHS = (2, 3, 1)
LOOP = re.compile(r'\b(?:for|while)\s*\(|\bdo\s*\{')
STORE = re.compile(rf'{IDENT}\s*\[[^\];]*\]\s*(?:[-+*/&|^]|<<|>>)?=(?!=)')


def _paren_end(clean, at):
    return close(clean, at, '(', ')')


def _statement_end(clean, at, stop):
    """Offset just past the statement that starts at AT (an `if` chain, a block or a `;`-terminated statement)."""
    while at < stop and clean[at].isspace():
        at += 1
    if clean.startswith('if', at) and not re.match(r'\w', clean[at + 2:at + 3] or ' '):
        paren = clean.find('(', at)
        end = _paren_end(clean, paren)
        if not end:
            return None
        end = _statement_end(clean, end, stop)
        if end is None:
            return None
        rest = re.match(r'\s*else\b', clean[end:stop])
        if rest:
            return _statement_end(clean, end + rest.end(), stop)
        return end
    word = re.match(r'(for|while|switch)\b', clean[at:stop])
    if word:
        paren = clean.find('(', at)
        end = _paren_end(clean, paren) if paren >= 0 else None
        return _statement_end(clean, end, stop) if end else None
    if re.match(r'do\b', clean[at:stop]):
        end = _statement_end(clean, at + 2, stop)
        tail = re.match(r'\s*while\s*\(', clean[end:stop]) if end else None
        if not tail:
            return None
        end = _paren_end(clean, end + tail.end() - 1)
        return clean.find(';', end) + 1 if end and clean.find(';', end) >= 0 else None
    if clean[at] == '{':
        return close(clean, at, '{', '}')
    depth, i = 0, at
    while i < stop:
        depth += (clean[i] in '([') - (clean[i] in ')]')
        if clean[i] == ';' and depth == 0:
            return i + 1
        if clean[i] in '{}':
            return None
        i += 1
    return None


def _blank_regions(text, opener):
    """TEXT with every region that OPENER starts (a keyword, its parentheses and its braces) blanked."""
    out = text
    for hit in re.finditer(opener, text):
        at = hit.end() - 1
        if text[at] == '{':
            end = close(text, at, '{', '}')
        else:
            paren = _paren_end(text, at)
            nxt = text.find('{', paren) if paren else -1
            end = close(text, nxt, '{', '}') if nxt >= 0 and not text[paren:nxt].strip() else None
        if end:
            out = out[:hit.start()] + ' ' * (end - hit.start()) + out[end:]
    return out


def _breaks_out(text):
    """Whether TEXT has a `continue` or a `break` that the extra `do` would catch, a label, or a `case` outside a nested
    switch."""
    loops = _blank_regions(text, r'\b(?:for|while)\s*\(|\bdo\s*\{')
    flat = _blank_regions(loops, r'\bswitch\s*\(')
    if re.search(r'\bcontinue\b', loops) or re.search(r'\bbreak\b', flat):
        return True
    return bool(re.search(r'\bcase\b|\bdefault\s*:|\b(?!default\b)' + IDENT + r'\s*:(?!:)', _blank_regions(text, r'\bswitch\s*\(')))


def statements(source, name):
    """[(kind, start, end)] for the top-level `if` and indexed-store statements of each loop body."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    tracked = units(source, name)[1]
    out = []
    for loop in LOOP.finditer(clean, part.opening, part.end):
        if loop.group().startswith('do'):
            opening = loop.end() - 1
        else:
            paren = _paren_end(clean, loop.end() - 1)
            nxt = paren and re.match(r'\s*\{', clean[paren:])
            if not nxt:
                continue
            opening = paren + nxt.end() - 1
        stop = close(clean, opening, '{', '}')
        if not stop:
            continue
        at = opening + 1
        while at < stop:
            while at < stop and clean[at].isspace():
                at += 1
            if at >= stop:
                break
            end = _statement_end(clean, at, stop - 1)
            if end is None:
                break
            text = clean[at:end]
            if text.startswith('if') and not re.match(r'\w', text[2:3] or ' '):
                kind = 'if'
            elif STORE.match(text) and text.rstrip().endswith(';') and tracked & set(re.findall(IDENT, re.match(r'[^=]*', text)[0])[1:]):
                kind = 'store'
            else:
                kind = None
            if kind and not _breaks_out(text) and not text.lstrip().startswith('do'):
                out.append((kind, at, end))
            at = end
    return out


def variants(source, name):
    found = statements(source, name)
    if not found:
        return []
    result = []
    for kind in ('if', 'store'):
        for start, end in [(s, e) for k, s, e in found if k == kind]:
            for depth in (IF_DEPTHS if kind == 'if' else STORE_DEPTHS):
                text = source[start:end]
                result.append((FAMILY, edit(source, [(start, end, 'do { ' * depth + text + ' } while (0);' * depth)])))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
