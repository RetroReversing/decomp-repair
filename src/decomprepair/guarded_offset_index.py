"""Index m2c's guarded counter loops by their counter, the way their source was written.

m2c writes a loop over records as a counter, a byte offset it advanced beside it, and a guard that tests the
bound before the first pass:

    i = 0;
    if (n > 0) {
        off = 0;
        do { ... off + base ...; i += 1; off += 0x18; } while (i < n);
    }

GCC 2.x made that offset itself (loop.c strength-reduces `base + i * 0x18` into a giv), so a source that spells
the offset as a variable of its own gets a pseudo the allocator ranks differently, and its zero is set before the
hoisted loop invariants instead of after them. The source had `i * 0x18`. And GCC 2.x ranks the counter by
floor_log2(uses) * uses / live_length (global.c): a guard written on the counter (`if (i < n)`, what a `for`
loop expands to) adds one use per loop, which is what puts the counter in the lower saved register ahead of the
strength-reduced offsets. Each of these alone can score worse (a 3-loop MIPS function: 180 -> 60 with the
indices, then only the counter-guard and the frame locals together reached 0), so the family offers the indexed
loops alone and with the counter guards, every loop at once.

Only rewrites a loop whose offset is read solely as a value (`off + x`, `x + off`), set to 0 once before the
loop and advanced once by a constant; an early `i += 1` in the body moves to the end, which is sound only when
the counter is not otherwise used in the body."""
import re

from .csource import _blank, find

FAMILY = 'guarded_offset_index'
GUARD_FAMILY = 'guarded_offset_index_counter_guard'
SHARED_FAMILY = 'guarded_offset_index_shared_counter'
FAMILIES = (FAMILY, GUARD_FAMILY, SHARED_FAMILY)
FRESH = 'i'
ID = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][\da-fA-F]+|[1-9]\d*)'


def _python_close(text, start):
    """Index of the brace closing the one at `start`, or None."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i
    return None


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(text, start):
        found = _scan.close_if(text, start, '{', '}', None)
        return _python_close(text, start) if found is NotImplemented else found


def _guard_condition(cond, bound):
    """`n > 0` and `n - 1 > 0` style guards with the loop's bound, spelled on the counter, or None."""
    inner = cond.strip()
    while inner.startswith('(') and _paren_close(inner, 0) == len(inner) - 1:
        inner = inner[1:-1].strip()
    hit = re.fullmatch(r'(?P<value>.+?)\s*>\s*0', inner, re.S)
    if not hit:
        return None
    norm = lambda s: re.sub(r'\s+|[()]', '', s)  # noqa: E731
    return norm(hit['value']) == norm(bound)


def _python_paren_close(text, start):
    depth = 0
    for i in range(start, len(text)):
        depth += {'(': 1, ')': -1}.get(text[i], 0)
        if depth == 0:
            return i
    return None


_paren_close = _python_paren_close
if _scan is not None:
    def _paren_close(text, start):
        found = _scan.close_every(text, start, '(', ')', False, None)
        return _python_paren_close(text, start) if found is NotImplemented else found


def _indexed(src_block, count, offset, body):
    """The loop's block with its offset spelled `count * stride` and the bump moved last, or None."""
    if not offset:
        return None
    steps = list(re.finditer(rf'\b{offset}\s*\+=\s*(?P<stride>{NUM})\s*;', body))
    bumps = list(re.finditer(rf'\b{count}\s*\+=\s*1\s*;', body))
    if len(steps) != 1 or len(bumps) != 1:
        return None
    rest_count = body
    for a, b in sorted((steps[0].span(), bumps[0].span()), reverse=True):
        rest_count = rest_count[:a] + rest_count[b:]
    if re.search(rf'\b{count}\b', rest_count) or re.search(r'\b(?:goto|continue|break)\b', body):
        return None
    reads = list(re.finditer(rf'\b{offset}\b', rest_count))
    if not reads or any(re.search(r'(?:\+\+|--|&)\s*$', rest_count[:r.start()]) or
                        re.match(r'\s*(?:\+\+|--|[-+*/%&|^]?=(?!=)|<<=|>>=)', rest_count[r.end():])
                        for r in reads):
        return None
    stride = steps[0]['stride']
    s_shape = re.fullmatch(
        rf'(?P<head>\s*){offset}\s*=\s*0\s*;(?P<mid>\s*do\s*\{{)(?P<body>.*)(?P<tail>\}}\s*while\s*\(.*)', src_block, re.S)
    if not s_shape:
        return None
    sb = s_shape['body']
    lines = sb
    for a, b in sorted([steps[0].span(), bumps[0].span()], reverse=True):
        # extend over the statement's own line when it stands alone
        line_start = lines.rfind('\n', 0, a) + 1
        if not lines[line_start:a].strip():
            a = line_start
            if b < len(lines) and lines[b] == '\n':
                b += 1
        lines = lines[:a] + lines[b:]
    lines = re.sub(rf'\b{offset}\b', f'({count} * {stride})', lines)
    indent = re.search(r'\n([ \t]*)\S', '\n' + lines.lstrip('\n'))
    pad = indent[1] if indent else '    '
    lines = lines.rstrip() + f'\n{pad}{count} += 1;\n' + re.search(r'\n?([ \t]*)$', sb)[1]
    return s_shape['head'] + s_shape['mid'].lstrip() + lines + s_shape['tail']


def _loops(source, span):
    """Each rewritable guarded loop: (start, end, indexed, indexed and guarded on the counter or None, counter)."""
    clean = _blank(source)
    found = []
    for hit in re.finditer(rf'\b(?P<count>{ID})\s*=\s*0\s*;\s*if\s*\(', clean[:span[1]]):
        if hit.start() < span[0]:
            continue
        count = hit['count']
        open_paren = hit.end() - 1
        close_paren = _paren_close(clean, open_paren)
        if close_paren is None:
            continue
        brace = re.match(r'\s*\{', clean[close_paren + 1:])
        if not brace:
            continue
        block_open = close_paren + brace.end()
        block_close = _close(clean, block_open)
        if block_close is None:
            continue
        block = clean[block_open + 1:block_close]
        shape = re.fullmatch(
            rf'\s*(?:(?P<offset>{ID})\s*=\s*0\s*;\s*)?do\s*\{{(?P<body>.*)\}}\s*while\s*\(\s*{count}\s*<\s*(?P<bound>.+?)\s*\)\s*;\s*',
            block, re.S)
        if not shape or shape['offset'] == count:
            continue
        bound = shape['bound']
        if _paren_close('(' + bound + ')', 0) != len(bound) + 1:
            continue
        # every loop counts for the guards and the shared counter; only the ones with an indexable offset change
        new_block = _indexed(source[block_open + 1:block_close], count, shape['offset'], shape['body'])
        indexed = new_block is not None
        if new_block is None:
            new_block = source[block_open + 1:block_close]
        plain = source[hit.start():block_open + 1] + new_block + source[block_close:block_close + 1]
        guarded = None
        cond = source[open_paren + 1:close_paren]
        if _guard_condition(cond, bound):
            guarded = (source[hit.start():open_paren + 1] + f'{count} < {bound.strip()}' +
                       source[close_paren:block_open + 1] + new_block + source[block_close:block_close + 1])
        found.append((hit.start(), block_close + 1, plain, guarded, count, indexed))
    return found


def _escapes(clean, span, start, end, count):
    """True when the counter's value is read outside its own loop (or it is not a plain local), so it can't share."""
    before, after = clean[span[0]:start], clean[end:span[1]]
    declared = re.search(rf'(?:s32|int|u32)\s+{count}\s*;', before)
    if not declared:
        return True
    uses = list(re.finditer(rf'\b{count}\b', before))[1:]
    if any(not re.match(r'\s*=(?!=)', before[m.end():]) for m in uses):
        return True
    later = re.search(rf'\b{count}\b', after)
    return bool(later and not re.match(r'\s*=(?!=)', after[later.end():]))


def _shared(source, span, loops, pick):
    """The loops whose counter's value stays inside them, counted by one fresh local; None when fewer than two.

    A counter read after its loop (a count kept for later, an index used past the loop) keeps its own name, and
    the others still share: one escaping counter used to stop the whole variant."""
    clean = _blank(source)
    if re.search(rf'\b{FRESH}\b', clean[span[0]:span[1]]):
        return None
    sharing = [loop for loop in loops if not _escapes(clean, span, loop[0], loop[1], loop[4])]
    if len(sharing) < 2:
        return None
    text = source
    for loop in sorted(loops, reverse=True):
        body = pick(loop)
        if loop in sharing:
            body = re.sub(rf'\b{loop[4]}\b', FRESH, body)
        text = text[:loop[0]] + body + text[loop[1]:]
    opening = _blank(text).index('{', span[0])
    return text[:opening + 1] + f'\n    s32 {FRESH};' + text[opening + 1:]


def variants(source, name, arch='mips', asm=''):
    """[(family, source)]: every guarded counter loop indexed by its counter; then also guarded on the counter;
    then with one counter shared by the loops whose counter stays inside them (each loop re-zeroes it, so GCC sees
    one pseudo whose uses add up). Loops without an indexable offset still take the guard and the shared counter,
    so a function mixing m2c's offset loops with plain counted loops gets every loop's use."""
    if not (span := find(source, name)):
        return []
    loops = _loops(source, span)
    if not loops:
        return []
    out = []
    indexed = lambda loop: loop[2]  # noqa: E731
    guarded = lambda loop: loop[3] or loop[2]  # noqa: E731
    for family, pick in ((FAMILY, indexed), (GUARD_FAMILY, guarded)):
        if family == FAMILY and not any(loop[5] for loop in loops):
            continue
        text = source
        for loop in sorted(loops, reverse=True):
            text = text[:loop[0]] + pick(loop) + text[loop[1]:]
        if text != source and all(text != other for _, other in out):
            out.append((family, text))
    if len(loops) > 1 and (shared := _shared(source, span, loops, guarded)) and all(shared != o for _, o in out):
        out.append((SHARED_FAMILY, shared))
    return out
