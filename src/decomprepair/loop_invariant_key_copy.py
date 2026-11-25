"""A loop's invariant comparand copied into a local of its own at the loop, and the rest of the arm reading the copy.

A local that the loop only reads (`if (pos >= cur)`) and that the code after the loop stores (`D[prev] = pos`) is, to
GCC 2.7.2, one pseudo from where it is set to its last use. Written as a copy taken where the loop starts
(`key = pos;` beside `cur = head;`), the loop and the stores after it read a pseudo of their own, so the allocator ranks
and places the two values separately and the original's `move` appears in the loop's setup. Found by hand on an
insertion into a sorted linked list (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`): the u16 position written
before the loop and compared in it took the register the list head's zero-extension has in the target; with the copy,
50 -> 10, and 0 once the copy was written after the cursor's start (`pure_preheader_order` finds that last swap).

For a local `V` (an ordinary integer scalar) read in a loop and never written in it, three children per loop:
  * `loop_invariant_key_copy`: `K = V;` right before the loop; the loop and everything after it in the block read `K`;
  * the same with the copy written before the statement that precedes the loop (the order the other way round);
  * `loop_invariant_key_copy_loop`: only the loop reads `K` (what follows keeps `V`).
Hypothesis (not read from the compiler's source): a loop-invariant read copied at the loop head ends up as its own
pseudo, which changes the allocation order. The exact judge decides; nothing here is a verdict."""
import re

from .integer_repair_support import IDENT, edit, locals_for, view
from .pattern_repairs import close

FAMILY = 'loop_invariant_key_copy'
LOOP_ONLY = 'loop_invariant_key_copy_loop'
FAMILIES = (FAMILY, LOOP_ONLY)
LIMIT = 8
LOOP = re.compile(r'\b(?:for|while)\s*\(|\bdo\b(?=\s*[{\w])')
WRITE = r'(?<![\w.>]){v}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?<![\w.>]){v}\s*(?:\+\+|--)|(?:\+\+|--)\s*{v}\b|&\s*{v}\b'


def _loop_end(clean, at, limit):
    """Where the loop statement starting at `at` ends (just past its body, or past `while (...);` of a do loop)."""
    if clean.startswith('do', at):
        body = clean.find('{', at)
        if body < 0:
            return None
        end = close(clean, body, '{', '}')
        tail = re.compile(r'\s*while\s*\(').match(clean, end or 0)
        if not end or not tail:
            return None
        stop = close(clean, tail.end() - 1)
        semi = clean.find(';', stop or 0)
        return semi + 1 if stop and 0 <= semi < limit else None
    header = clean.find('(', at)
    after = close(clean, header)
    if after is None:
        return None
    rest = re.compile(r'\s*').match(clean, after).end()
    if rest < len(clean) and clean[rest] == '{':
        return close(clean, rest, '{', '}')
    semi = clean.find(';', rest)
    return semi + 1 if 0 <= semi < limit else None


def _python_block_end(clean, at, opening):
    """The `}` that closes the block holding position `at` (the function's own at the top level)."""
    depth, index = 0, at
    while index > opening:
        index -= 1
        if clean[index] == '}':
            depth += 1
        elif clean[index] == '{':
            if depth == 0:
                end = close(clean, index, '{', '}')
                return end - 1 if end else None
            depth -= 1
    return None


_block_end = _python_block_end
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _block_end(clean, at, opening):
        found = _scan.enclosing_open(clean, at, opening, -1)
        if found is not NotImplemented:
            if found < 0:
                return None
            end = close(clean, found, '{', '}')
            return end - 1 if end else None
        return _python_block_end(clean, at, opening)


def _statement_start(clean, at, floor):
    """The start of the statement that precedes `at` (after the previous `;`, `{` or `}`), or None."""
    end = at
    while end > floor and clean[end - 1].isspace():
        end -= 1
    if end <= floor or clean[end - 1] != ';':
        return None
    index = end - 1
    while index > floor and clean[index - 1] not in ';{}':
        index -= 1
    while index < end and clean[index].isspace():
        index += 1
    return index if re.match(IDENT + r'\s*=[^=]', clean[index:end]) else None


def _swapper(var, key):
    pattern = re.compile(rf'(?<![\w.>]){var}\b')
    return lambda span: pattern.sub(key, span)


def _fresh(clean, base):
    for name in (base, base + '_copy', base + '_loop'):
        if not re.search(rf'\b{name}\b', clean):
            return name
    return None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto|setjmp|longjmp|volatile)\b|(?m:^\s*#)', part.body):
        return []
    clean, out = part.clean, []
    decls = {hit['name']: hit for hit in locals_for(part)}
    if not decls:
        return []
    key = _fresh(clean, 'key')
    if not key:
        return []
    for loop in LOOP.finditer(clean, part.opening + 1, part.end):
        end = _loop_end(clean, loop.start(), part.end)
        block = _block_end(clean, loop.start(), part.opening)
        if not end or not block or end > block:
            continue
        text = clean[loop.start():end]
        for var, decl in decls.items():
            reads = len(re.findall(rf'(?<![\w.>]){var}\b', text))
            if not reads or re.search(WRITE.format(v=re.escape(var)), text) or decl.start() > loop.start():
                continue
            if re.search(rf'\b{key}\b', text):
                continue
            after = clean[end:block]
            uses_after = bool(re.search(rf'(?<![\w.>]){var}\b', after))
            declaration = f'\n  {decl["type"]} {key};'
            where = source.index('\n', decl.end()) if '\n' in source[decl.end():] else decl.end()
            swap = _swapper(var, key)
            plan = [(FAMILY, end, True)] if uses_after else []
            plan.append((LOOP_ONLY, loop.start(), False) if uses_after else (FAMILY, loop.start(), False))
            for family, _, include_after in plan:
                body = swap(source[loop.start():end]) + (swap(source[end:block]) if include_after else '')
                span_end = block if include_after else end
                indent = re.match(r'[ \t]*', clean[clean.rfind('\n', 0, loop.start()) + 1:loop.start()])[0]
                copy = f'{key} = {var};'
                heads = [(loop.start(), f'{copy}\n{indent}')]
                before = _statement_start(clean, loop.start(), part.opening)
                if before is not None:
                    heads.append((before, f'{copy}\n{indent}'))
                for position, line in heads:
                    first = [(where, where, declaration), (position, position, line),
                             (loop.start(), span_end, body)]
                    if position == loop.start():
                        first = [(where, where, declaration), (loop.start(), span_end, line + body)]
                    out.append((family, edit(source, first)))
    seen, result = set(), []
    for family, text in out:
        if text not in seen and text != source:
            seen.add(text)
            result.append((family, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 97}
