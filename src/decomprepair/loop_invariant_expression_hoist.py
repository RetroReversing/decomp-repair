"""A loop-invariant expression computed inside a loop, written once into a local before the loop (and the empty fences gone).

m2c, and an autopilot's fenced drafts, leave a value the loop only reads inside it: `(s16) (M2C_FIELD(arg0, const u16 *,
0x216) + 0x64)` compared with every list node, between `do { } while (0)` fences that were scaffolding for a weight
experiment. GCC 2.7.2's loop pass would move such an invariant out on its own, but only in its own order and as one more
hoisted insn: the original's author wrote the key into a local first (`key = (s16) (...);`, above the guard that
tests the list head), so its load and its `addiu`/`sll` come before the head's `lui; lw`, and the loop compares a
register (`beq $v0, $v1`) where the inline spelling re-tests the expression's pieces. Found by hand on a 29-instruction
list walker (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`): 120 -> 0 with the key set before the loop and the fences
removed; the fences alone and the hoist alone were not the match (the rows that differ are the frame's `addiu $sp` and
the order of the key's `lhu` against the head's load).

Two parts, offered separately and together (the match needed both; a chain that takes one step at a time cannot see a
pair of edits that each leave the score unchanged):
  * `loop_invariant_expression_hoist`: for a cast of a parenthesised expression (`(s16) (...)`) or a bare `M2C_FIELD(...)`
    read inside a loop, built only from parameters and locals that the loop never assigns (and, when it reads memory,
    in a loop with no call), a local `key` of the cast's type set once and read in the loop. Three places for the set: right before
    the loop, before the whole top-level statement that holds the loop, and as the function's first statement; each only
    where nothing between it and the loop assigns the expression's names or stores through memory (a fenced assignment
    of the list head between the set and the loop is the usual case, and does not touch the key);
  * `loop_fence_unwrap`: `do { S } while (0);` written in statement position (never as the body of an `if` or `else`, and
    never round a `break`, `continue` or a declaration) becomes `S`, every one in a loop at once and every one in the
    function at once (the fences are nested at times: repeated until none is left);
  * `loop_invariant_hoist_unfenced`: both, the hoist's three places with every fence of the function removed.
The hoist is a hypothesis (the hoisted value's lifetime and priority, which the allocator ranks by
`floor_log2(refs) * refs / live length`, change); it is not read from the compiler's source. A store through a pointer
the loop writes may alias a field the expression reads: the proposal does not prove otherwise, the byte judge decides."""
import re

from .integer_repair_support import IDENT, INTEGER, edit, view
from .loop_invariant_key_copy import LOOP, WRITE, _block_end, _fresh, _loop_end
from .pattern_repairs import close

HOIST = 'loop_invariant_expression_hoist'
UNWRAP = 'loop_fence_unwrap'
BOTH = 'loop_invariant_hoist_unfenced'
FAMILIES = (HOIST, UNWRAP, BOTH)
LIMIT = 10
CAST = re.compile(rf'\(\s*({INTEGER})\s*\)\s*\(')
FIELD = re.compile(r'\bM2C_FIELD\s*\(')
FENCE = re.compile(r'\bdo\s*\{(?P<body>[^{}]*)\}\s*while\s*\(\s*0\s*\)\s*;')
KEYWORDS = {'return', 'goto', 'break', 'continue', 'else', 'case', 'default', 'do', 'if', 'while', 'for', 'switch'}
DECLARATION = re.compile(rf'\s*(?:const\s+)?(?:struct\s+\w+|unsigned\s+\w+|{IDENT})[\s*]+({IDENT})(?:\[[^\]]*\])?\s*;')
MEMORY_STORE = re.compile(r'(?:\*|\]|->\s*\w+|\.\s*\w+|\bM2C_FIELD\s*\((?:[^;()]|\([^;()]*\))*\))\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)')
CALL = re.compile(rf'\b({IDENT})\s*\(')
MEMBER = re.compile(rf'(?:->|\.)\s*{IDENT}')
PURE_MACROS = {'M2C_FIELD', 'M2C_BITWISE'}


def _names(declared, text):
    """The identifiers of `text` (members and numbers aside) that are not types; None when one is not a local or
    parameter of the function (a global may change under a store)."""
    names = set(re.findall(r'\b' + IDENT, MEMBER.sub(' ', text)))
    names -= {'M2C_FIELD', 'M2C_BITWISE', 'const', 'unsigned', 'signed', 'char', 'short', 'int', 'NULL'}
    names = {n for n in names if not re.fullmatch(INTEGER, n) and not re.fullmatch(r'[su](?:8|16|32)|0[xX]\w*', n)}
    return names if names <= declared else None


def _declared(clean, part):
    """Parameters and locals of the function (names only)."""
    head_start = clean.rfind(')', 0, part.opening)
    open_paren = clean.rfind('(', 0, head_start + 1)
    found = set()
    for piece in clean[open_paren + 1:head_start].split(','):
        ident = re.findall(IDENT, piece)
        if ident:
            found.add(ident[-1])
    found.discard('void')
    position = part.opening + 1
    while True:
        hit = DECLARATION.match(clean, position)
        if not hit or hit[1] in KEYWORDS or clean[position:hit.start(1)].split()[:1] in (['return'], ['goto']):
            break
        found.add(hit[1])
        position = hit.end()
    return found, position + len(re.match(r'\s*', clean[position:])[0])


def _split_top(text):
    pieces, depth, last = [], 0, 0
    for index, char in enumerate(text):
        depth += char in '([{'
        depth -= char in ')]}'
        if char == ',' and depth == 0:
            pieces.append(text[last:index])
            last = index + 1
    pieces.append(text[last:])
    return pieces


def _candidates(clean, start, end):
    """[(span start, span end, type, expression text)] of cast expressions and bare field reads inside [start, end)."""
    found = []
    for hit in CAST.finditer(clean, start, end):
        stop = close(clean, hit.end() - 1)
        if stop and stop <= end:
            found.append((hit.start(), stop, re.sub(r'\s+', ' ', hit[1]), clean[hit.start():stop]))
    for hit in FIELD.finditer(clean, start, end):
        stop = close(clean, hit.end() - 1)
        if not stop or stop > end or any(a <= hit.start() and stop <= b for a, b, _, _ in found):
            continue
        pieces = _split_top(clean[hit.end():stop - 1])
        kind = re.fullmatch(rf'\s*(?:const\s+)?({INTEGER})\s*\*\s*', pieces[1]) if len(pieces) == 3 else None
        if kind:
            found.append((hit.start(), stop, re.sub(r'\s+', ' ', kind[1]), clean[hit.start():stop]))
    return found


def _norm(text):
    return re.sub(r'\s+', '', text)


def _open_before(clean, at, low):
    """The `{` that opens the block holding position `at`, or None at the function's own level."""
    depth = 0
    index = at
    while index > low:
        index -= 1
        if clean[index] == '}':
            depth += 1
        elif clean[index] == '{':
            if depth == 0:
                return index
            depth -= 1
    return None


def _statement_top(clean, at, part):
    """The start of the function-level `if`/`for`/`while` statement that holds position `at`, or None when `at` is at
    the top level already or that statement is an `else` arm."""
    outer = None
    opening = _open_before(clean, at, part.opening)
    while opening is not None:
        outer = opening
        opening = _open_before(clean, opening, part.opening)
    if outer is None:
        return None
    back = outer
    while back > part.opening and clean[back - 1].isspace():
        back -= 1
    if back > part.opening and clean[back - 1] == ')':
        depth = 0
        while back > part.opening:
            back -= 1
            if clean[back] == ')':
                depth += 1
            elif clean[back] == '(':
                depth -= 1
                if depth == 0:
                    break
        while back > part.opening and clean[back - 1].isspace():
            back -= 1
        word = re.search(r'(\w+)$', clean[part.opening:back])
        if not word or word[1] not in ('if', 'for', 'while', 'switch'):
            return None
        back -= len(word[1])
    else:
        return None
    before = back
    while before > part.opening and clean[before - 1].isspace():
        before -= 1
    if before > part.opening and clean[before - 1] not in ';{}':
        return None
    return back


def _hoists(source, part, name):
    clean = part.clean
    key = _fresh(clean, 'key')
    if not key:
        return []
    declared, first = _declared(clean, part)
    out = []
    seen_expressions = set()
    for loop in LOOP.finditer(clean, part.opening + 1, part.end):
        end = _loop_end(clean, loop.start(), part.end)
        block = _block_end(clean, loop.start(), part.opening)
        if not end or not block or end > block:
            continue
        text = clean[loop.start():end]
        calls = [c for c in CALL.findall(text) if c not in PURE_MACROS and not re.fullmatch(INTEGER, c)
                 and c not in KEYWORDS]
        for begin, stop, kind, expression in _candidates(clean, loop.start(), end):
            tag = (loop.start(), _norm(expression))
            if tag in seen_expressions:
                continue
            seen_expressions.add(tag)
            names = _names(declared, expression)
            if not names or any(re.search(WRITE.format(v=re.escape(n)), text) for n in names):
                continue
            reads_memory = bool(re.search(r'M2C_FIELD|->|\*|\[', expression))
            if reads_memory and calls:
                continue
            if CALL.search(expression) and any(c not in PURE_MACROS and c not in KEYWORDS
                                               and not re.fullmatch(INTEGER, c) for c in CALL.findall(expression)):
                continue
            pattern = re.compile(r'\s*'.join(re.escape(piece) for piece in re.split(r'\s+', expression.strip())))
            spans = [(loop.start() + hit.start(), loop.start() + hit.end()) for hit in pattern.finditer(text)]
            if len(spans) < 1:
                continue
            # a store to the very expression (a field the loop writes) is no invariant
            if any(re.match(r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', clean[b:]) for _, b in spans):
                continue
            if any(clean[max(a - 1, 0):a].strip() == '&' for a, _ in spans):
                continue
            places = [loop.start()]
            top = _statement_top(clean, loop.start(), part)
            if top is not None:
                places.append(top)
            places.append(first)
            for place in dict.fromkeys(places):
                between = clean[place:loop.start()]
                if place != loop.start():
                    if any(re.search(WRITE.format(v=re.escape(n)), between) for n in names):
                        continue
                    if reads_memory and (CALL.search(between) and any(
                            c not in PURE_MACROS and c not in KEYWORDS for c in CALL.findall(between))
                            or MEMORY_STORE.search(between)):
                        continue
                line_start = clean.rfind('\n', 0, place) + 1
                indent = re.match(r'[ \t]*', clean[line_start:place])[0] if not clean[line_start:place].strip() else '  '
                set_key = f'{key} = {source[spans[0][0]:spans[0][1]]};'
                margin = re.search(r'\n([ \t]+)\S', clean[part.opening:])
                declaration = (part.opening + 1, part.opening + 1, f'\n{margin[1] if margin else "  "}{kind} {key};')
                swaps = [(a, b, key) for a, b in spans]
                insertion = (place, place, f'{set_key}\n{indent}')
                out.append((HOIST, source, [declaration, insertion] + swaps, expression))
    return out


def unwrap_fences(source, name, only_loops):
    """`source` with every `do { S } while (0);` in statement position written as `S`, repeated for nested fences, or None."""
    text, changed = source, False
    for _ in range(8):
        part = view(text, name)
        if not part:
            return text if changed else None
        loops = []
        if only_loops:
            for loop in LOOP.finditer(part.clean, part.opening + 1, part.end):
                stop = _loop_end(part.clean, loop.start(), part.end)
                if stop:
                    loops.append((loop.start(), stop))
        edits = []
        for fence in FENCE.finditer(part.clean, part.opening + 1, part.end):
            body = fence['body']
            if re.search(r'\b(?:break|continue|goto|return)\b', body) or re.match(
                    rf'\s*(?:const\s+)?(?:{INTEGER}|struct\s+\w+|void|float|double|f32|f64)\b[\s*]+{IDENT}\s*[;=\[]', body):
                continue
            before = part.clean[:fence.start()].rstrip()
            if before and before[-1] not in ';{}' or before.endswith(')') or before.endswith('do'):
                continue
            if only_loops and not any(a < fence.start() and fence.end() <= b for a, b in loops):
                continue
            inner = text[fence.start('body'):fence.end('body')].strip()
            edits.append((fence.start(), fence.end(), inner))
        if not edits:
            break
        text = edit(text, edits)
        changed = True
    return text if changed and text != source else None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto|setjmp|longjmp|volatile)\b|(?m:^\s*#)', part.body):
        return []
    out = []
    for family, _, edits, _expression in _hoists(source, part, name):
        hoisted = edit(source, edits)
        out.append((HOIST, hoisted))
        every = unwrap_fences(hoisted, name, False)
        if every:
            out.append((BOTH, every))
    for only_loops in (True, False):
        plain = unwrap_fences(source, name, only_loops)
        if plain:
            out.append((UNWRAP, plain))
    seen, result = set(), []
    for family, text in out:
        if text not in seen and text != source:
            seen.add(text)
            result.append((family, text))
    # the combined children first: a chain that scores one edit at a time cannot reach them
    result.sort(key=lambda row: row[0] != BOTH)
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 96}
