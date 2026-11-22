"""Source shapes of a list walk that logs what it did (a chunk cache), found by matching one by hand.

A 364-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`), the lookup of a block cache: walk a
recency list for nodes that overlap a byte range, log the part of each that needed loading, move the node to the front,
and fill the rest of the range from nodes taken off a free list or off the list's tail. m2c's draft of it scored 5451
with eighty register rows; a series of small edits, none of which the permuter proposed, took it to exact. Each edit
is a family here. They are hypotheses about what gcc 2.7.2 keys on, not proofs; the judge decides every child.

- `element_pointer_inline`: `e = &table[idx]; e->a = ..; e->b = ..;` written as `table[idx].a = ..; table[idx].b = ..;`.
  A pointer local assigned in several places is one long-lived pseudo that global allocation gives a call-clobbered
  register of its own (`$t0`); written at each store, the address is a temporary of the block and takes the target's
  `$a1`/`$v1` (80 rows -> 34 with this edit alone, on top of the ones below).
- `condition_capture`: a value read twice in a condition and then copied into a local as the body's first statement,
  `if (n->addr < hi && lo < n->addr) { a = n->addr; ..`, as `(a = n->addr) < hi && lo < a`. One load fewer, and the
  local is set where the target's first use of its register is.
- `value_reuse_before_branch`: `if (x + y >= r) v = k - a; else v = ((x + y - b) + 255) & ~255;`, the sum computed once
  into the variable both arms assign, `v = x + y; if (v >= r) v = k - a; else v = ((v - b) + 255) & ~255;`. The
  target holds the sum in the saved register `v` takes later (`move $s1,$v1`).
- `arm_scoped_scratch`: an arm of an if chain that assigns a function-level scratch before reading it declares that
  scratch in its own block. Pseudo registers of a block-scoped local are numbered when the block is entered, and the
  one shared scratch (live over the whole loop, hence a global pseudo that took `$a1`) became a short-lived
  temporary of the arm that gets `$v0`.
- `reassociation_temp`: `x = x - 0x600 + s;` and `x -= s - 0x600;` with the part that gcc's fold would reassociate
  held in a temporary: `n = x - 0x600; x = n + s;`, `m = s - 0x600; x -= m;`. gcc 2.7.2 folds `(a - K) + b` to
  `a + (b - K)` and `a - (b - K)` to `(a + K) - b` inside one expression, so the target's `addiu`, `addu` and
  `addiu`, `subu` order needs the two statements.
- `store_run_move`: in a run of two to five consecutive stores and assignments, one statement moved to another place
  in the run when the two do not conflict (a store reading what the other writes stays put). Output records and arrays
  written field by field are scheduled in source order for ties, and the target's order was the match.

Offered one at a time, each as its own child, so a search that keeps ties walks the chain, and `chain()` for the whole
set applied together where several steps only pay off combined (the match needed all of them).
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY_POINTER = 'element_pointer_inline'
FAMILY_CAPTURE = 'condition_capture'
FAMILY_REUSE = 'value_reuse_before_branch'
FAMILY_SCOPED = 'arm_scoped_scratch'
FAMILY_REASSOC = 'reassociation_temp'
FAMILY_MOVE = 'store_run_move'
FAMILY_HANDLE = 'arm_handle_copy'
FAMILY_CHAIN = 'walk_shape_chain'
FAMILIES = (FAMILY_CHAIN, FAMILY_HANDLE, FAMILY_POINTER, FAMILY_CAPTURE, FAMILY_REUSE, FAMILY_SCOPED, FAMILY_REASSOC, FAMILY_MOVE)
LIMIT = 200
WINDOW = 5
SCALAR = r'(?:unsigned\s+(?:char|short|int)|signed\s+(?:char|short|int)|[su](?:8|16|32)|char|short|int)'
FIELD = rf'{IDENT}(?:\s*(?:->|\.)\s*{IDENT})+'


def _usable(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto|setjmp|longjmp|switch)\b|^\s*#', part.body, re.M):
        return None
    return part


def _block_end(clean, opening):
    return close(clean, opening, '{', '}')


def _enclosing_block(clean, position, part):
    """(opening, end) of the innermost brace block around `position` inside the function."""
    depth = 0
    for pos in range(position - 1, part.opening, -1):
        if clean[pos] == '}':
            depth += 1
        elif clean[pos] == '{':
            if depth == 0:
                return pos, _block_end(clean, pos)
            depth -= 1
    return part.opening, part.end


def _locals(part):
    """name -> declared scalar or pointer type text, for the declarations at the start of any block."""
    found = {}
    for hit in re.finditer(rf'(?:(?<=[;{{}}])|^)\s*((?:const\s+)?(?:{SCALAR}|{IDENT})(?:\s*\*)*)\s+(\*?\s*{IDENT}(?:\s*,\s*\*?\s*{IDENT})*)\s*;',
                           part.clean[part.opening + 1:part.end], re.M):
        if re.match(r'(?:return|else|goto|break|continue|case|do)\b', hit[1]):
            continue
        for item in hit[2].split(','):
            star = '*' if item.strip().startswith('*') else ''
            found[item.strip().lstrip('*').strip()] = hit[1].strip() + (' *' if star and not hit[1].strip().endswith('*') else '')
    return found


def _declarations_end(part, position=None):
    """Offset just after the leading declarations of a block (the function's, by default)."""
    clean = part.clean
    position = part.opening + 1 if position is None else position
    pattern = re.compile(rf'\s*(?:const\s+)?(?:struct\s+|union\s+)?(?:{SCALAR}|{IDENT})(?:[\s*]+)(?:\*?\s*{IDENT}(?:\[[^\];]*\])*\s*,?\s*)+;')
    while True:
        match = pattern.match(clean, position)
        if not match or re.match(r'\s*(?:return|else|goto|break|continue|case|do)\b', clean[position:position + 12]):
            return position
        position = match.end()


def _decl(type_text, name):
    return f'{type_text}{name};' if type_text.endswith('*') else f'{type_text} {name};'


def _free_name(body, stem):
    for suffix in ('', '2', '3', '4', '5', '6'):
        if not re.search(rf'\b{stem}{suffix}\b', body):
            return stem + suffix
    return None


def _writes(text, name):
    """Does `text` assign, increment or take the address of `name`?"""
    n = re.escape(name)
    return bool(re.search(rf'(?<![\w.>]){n}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{n}\b|(?<![\w.>]){n}\s*(?:\+\+|--)|&\s*{n}\b', text))


def _mentions(text, name):
    return re.search(rf'(?<![\w.>])(?<!->){re.escape(name)}\b', text)


# ---------------------------------------------------------------------------------------------------------------------
def element_pointer_inline(source, name):
    part = _usable(source, name)
    if not part:
        return []
    clean = part.clean
    assign = re.compile(rf'(?:(?<=[;{{}}])|^)(\s*)({IDENT})\s*=\s*&\s*({IDENT})\s*\[([^\[\];]+)\]\s*;', re.M)
    sites = []
    for hit in assign.finditer(clean, part.opening + 1, part.end):
        pointer, array, index = hit[2], hit[3], hit[4].strip()
        _, block_end = _enclosing_block(clean, hit.start(), part)
        tail = clean[hit.end():block_end]
        uses = list(re.finditer(rf'(?<![\w.>]){re.escape(pointer)}\s*->\s*({IDENT})', tail))
        if len(uses) < 2:
            continue
        last = uses[-1].end()
        span = tail[:last]
        if len(re.findall(rf'(?<![\w.>]){re.escape(pointer)}\b', span)) != len(uses):
            continue
        if re.search(r'\w\s*\(', re.sub(r'\[[^\[\]]*\]', '', span)) and re.search(rf'{IDENT}\s*\(', span):
            continue
        names = set(re.findall(IDENT, index)) | {array}
        if any(_writes(span, n) for n in names):
            continue
        sites.append((hit, pointer, array, index, uses))
    # a pointer also read anywhere outside the stores it is inlined into has to stay as it is
    spans = [(site[0].start(), site[0].end() + site[4][-1].end()) for site in sites]
    sites = [site for site in sites if not _mentioned_outside(clean, part, site[1], spans)]
    if not sites:
        return []

    def rewrite(chosen):
        edits = []
        for hit, pointer, array, index, uses in chosen:
            edits.append((hit.start(), hit.end(), ''))
            for use in uses:
                start = hit.end() + use.start()
                edits.append((start, hit.end() + use.end(), f'{array}[{index}].{use[1]}'))
        text = edit(source, edits)
        for pointer in {site[1] for site in chosen}:
            fresh = view(text, name)
            declaration = re.search(rf'^[ \t]*[A-Za-z_][\w\s*]*?\*?\s*\b{re.escape(pointer)}\s*;[ \t]*\n', text[fresh.opening:fresh.end], re.M) if fresh else None
            if not declaration:
                continue
            rest = fresh.clean[fresh.opening:fresh.end]
            rest = rest[:declaration.start()] + rest[declaration.end():]
            if not _mentions(rest, pointer):
                text = text[:fresh.opening + declaration.start()] + text[fresh.opening + declaration.end():]
        return text
    result = [(FAMILY_POINTER, rewrite(sites))]
    if len(sites) > 1:
        result += [(FAMILY_POINTER, rewrite([site])) for site in sites[:2]]
    return result


def _mentioned_outside(clean, part, name, spans):
    """Is `name` read anywhere in the function but inside the given spans, and its declaration?"""
    for m in re.finditer(rf'(?<![\w.>])(?<!->){re.escape(name)}\b', clean[part.opening + 1:part.end]):
        position = part.opening + 1 + m.start()
        if any(a <= position < b for a, b in spans):
            continue
        before = clean[:position].rstrip()
        after = clean[position + len(name):].lstrip()
        if after.startswith(';') and re.search(r'[\w*]\s*\*?\s*$', before) and re.search(r'(?:^|[;{}])\s*[A-Za-z_][\w\s*]*$', before):
            continue
        return True
    return False


# ---------------------------------------------------------------------------------------------------------------------
def condition_capture(source, name):
    part = _usable(source, name)
    if not part:
        return []
    clean = part.clean
    result = []
    for hit in re.finditer(r'\bif\s*\(', clean[part.opening + 1:part.end]):
        paren = part.opening + 1 + hit.end() - 1
        end = close(clean, paren)
        if not end:
            continue
        condition = clean[paren + 1:end - 1]
        brace = re.match(r'\s*\{\s*', clean[end:])
        if not brace:
            continue
        copy = re.match(rf'({IDENT})\s*=\s*({FIELD})\s*;\s*', clean[end + brace.end():])
        if not copy:
            continue
        local, value = copy[1], re.sub(r'\s+', '', copy[2])
        if re.search(r'\|\||\?|[^=!<>]=(?!=)|\+\+|--', condition) or re.search(rf'\b{IDENT}\s*\(', condition):
            continue
        if _mentions(condition, local):
            continue
        pattern = re.compile(r'\s*'.join(re.escape(piece) for piece in re.split(r'(->|\.)', value) if piece))
        spots = [m for m in pattern.finditer(condition) if not re.match(r'\s*(?:->|\.|\w)', condition[m.end():])]
        if not spots:
            continue
        edits = []
        for number, spot in enumerate(spots):
            edits.append((paren + 1 + spot.start(), paren + 1 + spot.end(), f'({local} = {value})' if number == 0 else local))
        copy_start = end + brace.end()
        edits.append((copy_start, copy_start + copy.end(), ''))
        result.append((FAMILY_CAPTURE, edit(source, edits)))
    return result


# ---------------------------------------------------------------------------------------------------------------------
def _statement(clean, position):
    """The single assignment statement at `position` (inside optional braces): (start, end, target, value)."""
    match = re.match(rf'\s*(\{{\s*)?({IDENT})\s*=\s*([^;{{}}]+);(\s*\}})?', clean[position:])
    if not match or bool(match[1]) != bool(match[4]):
        return None
    return position, position + match.end(), match[2], match[3], position + match.start(3), position + match.end(3)


def value_reuse_before_branch(source, name):
    part = _usable(source, name)
    if not part:
        return []
    clean = part.clean
    result = []
    for hit in re.finditer(r'(?:(?<=[;{}])|^)\s*(if)\s*\(', clean[part.opening + 1:part.end], re.M):
        start = part.opening + 1 + hit.start(1)
        paren = part.opening + 1 + hit.end() - 1
        end = close(clean, paren)
        if not end:
            continue
        then = _statement(clean, end)
        if not then:
            continue
        otherwise = re.match(r'\s*else\b', clean[then[1]:])
        if not otherwise:
            continue
        other = _statement(clean, then[1] + otherwise.end())
        if not other or other[2] != then[2]:
            continue
        variable = then[2]
        condition = clean[paren + 1:end - 1]
        if _mentions(condition, variable) or re.search(r'\|\||&&|\?|\+\+|--|[^=!<>]=(?!=)', condition):
            continue
        found = None
        for sum_ in re.finditer(rf'(?<![\w.>])({IDENT})\s*([-+])\s*({IDENT})\b(?!\s*(?:->|\.|\())', condition):
            expression = sum_[0]
            if variable in (sum_[1], sum_[3]):
                continue
            shape = re.compile(rf'(?<![\w.>]){re.escape(sum_[1])}\s*{re.escape(sum_[2])}\s*{re.escape(sum_[3])}\b')
            arms = [other[4:6]]
            if any(shape.search(clean[a:b]) for a, b in arms):
                found = (sum_, shape)
                break
        if not found:
            continue
        sum_, shape = found
        edits = [(paren + 1 + m.start(), paren + 1 + m.end(), variable) for m in shape.finditer(condition)]
        for a, b in (then[4:6], other[4:6]):
            edits += [(a + m.start(), a + m.end(), variable) for m in shape.finditer(clean[a:b])]
        expression = re.sub(r'\s+', ' ', sum_[0]).strip()
        edits.append((start, start, f'{variable} = {expression};\n{_indent(source, start)}'))
        result.append((FAMILY_REUSE, edit(source, edits)))
    return result


def _indent(source, position):
    line = source.rfind('\n', 0, position) + 1
    return re.match(r'[ \t]*', source[line:position])[0]


# ---------------------------------------------------------------------------------------------------------------------
def arm_scoped_scratch(source, name):
    part = _usable(source, name)
    if not part:
        return []
    clean = part.clean
    types = _locals(part)
    top = set(types)
    result = []
    by_variable = {}
    for arm in re.finditer(r'(?:\bif\s*\([^{};]*\)|\belse(?:\s+if\s*\([^{};]*\))?)\s*\{', clean[part.opening + 1:part.end]):
        opening = part.opening + 1 + arm.end() - 1
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        inner = clean[opening + 1:end - 1]
        before = clean[part.opening + 1:opening]
        chained = re.search(r'\belse\s*(?:if\s*\([^{};]*\))?\s*\{$', before.rstrip() + ' {') or re.match(r'\s*else\b', clean[end:])
        if not chained:
            continue
        if re.match(r'\s*(?:' + SCALAR + r'|\w+\s*\*)\s+\w', inner):
            continue
        chain_end = end
        while True:
            more = re.match(r'\s*else\b(?:\s+if\s*\([^{};]*\))?\s*\{', clean[chain_end:])
            if not more:
                break
            chain_end = close(clean, chain_end + more.end() - 1, '{', '}') or chain_end
            if chain_end == end:
                break
        for variable in sorted(top):
            if variable not in types or not re.fullmatch(SCALAR, types[variable]):
                continue
            first = _mentions(inner, variable)
            if not first or not re.match(rf'{re.escape(variable)}\s*=(?!=)', inner[first.start():]):
                continue
            rest = inner[first.start():]
            assignment = re.match(rf'{re.escape(variable)}\s*=\s*([^;]*);', rest)
            if not assignment or _mentions(assignment[1], variable):
                continue
            if not _mentions(clean[part.opening + 1:opening], variable) and not _mentions(clean[chain_end:part.end], variable):
                continue
            after = clean[chain_end:part.end]
            read = None
            for m in re.finditer(rf'(?<![\w.>])(?<!->){re.escape(variable)}\b', after):
                if not re.match(r'\s*=(?!=)', after[m.end():]):
                    read = m
                    break
            if read:
                continue
            indent = _indent(source, opening + 1 + len(inner) - len(inner.lstrip()))
            decl = f'\n{indent}{_decl(types[variable], variable)}'
            by_variable.setdefault(variable, []).append((opening + 1, decl))
    for variable, edits in by_variable.items():
        for position, decl in edits:
            result.append((FAMILY_SCOPED, source[:position] + decl + source[position:]))
        if len(edits) > 1:
            result.append((FAMILY_SCOPED, edit(source, [(position, position, decl) for position, decl in edits])))
    return result


# ---------------------------------------------------------------------------------------------------------------------
def reassociation_temp(source, name):
    part = _usable(source, name)
    if not part:
        return []
    clean = part.clean
    types = _locals(part)
    result = []
    patterns = (
        (rf'(?:(?<=[;{{}}])|^)([ \t]*)({IDENT})\s*=\s*({IDENT})\s*-\s*(0[xX][0-9a-fA-F]+|\d+)\s*\+\s*({IDENT})\s*;',
         lambda m, t: (f'{t} {{n}};', f'{{n}} = {m[3]} - {m[4]};\n{m[1]}{m[2]} = {{n}} + {m[5]};')),
        (rf'(?:(?<=[;{{}}])|^)([ \t]*)({IDENT})\s*-=\s*({IDENT})\s*-\s*(0[xX][0-9a-fA-F]+|\d+)\s*;',
         lambda m, t: (f'{t} {{n}};', f'{{n}} = {m[3]} - {m[4]};\n{m[1]}{m[2]} -= {{n}};')),
    )
    for pattern, build in patterns:
        for hit in re.finditer(pattern, clean[part.opening + 1:part.end], re.M):
            start = part.opening + 1 + hit.start()
            target = hit[2]
            if target not in types or not re.fullmatch(SCALAR, types[target]):
                continue
            opening, end = _enclosing_block(clean, start, part)
            body = part.clean[part.opening + 1:part.end]
            stem = 'n' if '+' in hit[0] else 'm'
            fresh = _free_name(body, stem)
            if not fresh:
                continue
            declare, replace = (x.replace('{n}', fresh) for x in build(hit, types[target]))
            statement_start = start + (len(hit[0]) - len(hit[0].lstrip()))
            text = source[:statement_start] + replace.lstrip() + source[part.opening + 1 + hit.end():]
            block_open = opening
            indent = _indent(source, statement_start)
            text = text[:block_open + 1] + f'\n{indent}{declare}' + text[block_open + 1:]
            result.append((FAMILY_REASSOC, text))
    return result


# ---------------------------------------------------------------------------------------------------------------------
def _simple_statements(clean, start, end):
    """Spans of the consecutive simple statements (no braces, no control words) from `start`."""
    spans = []
    position = start
    while position < end:
        match = re.match(r'\s*([^;{}]+;)', clean[position:end])
        if not match or re.match(r'\s*(?:if|else|for|while|do|return|break|continue|switch)\b', match[1]):
            break
        spans.append((position + match.start(1), position + match.end(1)))
        position += match.end()
    return spans


# ---------------------------------------------------------------------------------------------------------------------
def arm_handle_copy(source, name):
    """`v = G; if (G != 0) { use v } else { v = H; use v }` with each arm working on a temporary handle `t`.

    `v` is the long-lived variable of a loop (a saved register); the node taken off a free list (`$a0`) is a short-lived
    value copied into it where the arm is done with the free-list bookkeeping, `v = t;`. The copy's place in the second
    arm is offered at each of the first five statements: copy propagation makes later reads of the pair use whichever
    came first, so the position changes which register the stores name."""
    part = _usable(source, name)
    if not part:
        return []
    clean = part.clean
    types = _locals(part)
    result = []
    for hit in re.finditer(rf'(?:(?<=[;{{}}])|^)([ \t]*)({IDENT})\s*=\s*({FIELD}|{IDENT})\s*;\s*if\s*\(', clean[part.opening + 1:part.end], re.M):
        variable, value = hit[2], hit[3]
        if variable not in types or not types[variable].endswith('*'):
            continue
        start = part.opening + 1 + hit.start()
        paren = part.opening + 1 + hit.end() - 1
        end = close(clean, paren)
        if not end or not _mentions(clean[paren:end], value) or _mentions(clean[paren:end], variable):
            continue
        a_open = re.match(r'\s*\{', clean[end:])
        if not a_open:
            continue
        a_start = end + a_open.end() - 1
        a_end = close(clean, a_start, '{', '}')
        b_open = re.match(r'\s*else\s*\{', clean[a_end:]) if a_end else None
        if not b_open:
            continue
        b_start = a_end + b_open.end() - 1
        b_end = close(clean, b_start, '{', '}')
        b_body = _declarations_end(part, b_start + 1) if b_end else None
        first = re.match(rf'\s*({re.escape(variable)})\s*=\s*([^;{{}}]+);', clean[b_body:b_end]) if b_end else None
        if not first:
            continue
        temp = _free_name(clean[part.opening + 1:part.end], 't')
        if not temp:
            continue
        a_text = source[a_start + 1:a_end - 1]
        pattern = re.compile(rf'(?<![\w.>])(?<!->){re.escape(variable)}\b')

        def rename(text, pattern=pattern, temp=temp):
            return pattern.sub(temp, text)

        indent = _indent(source, a_start + 1 + len(a_text) - len(a_text.lstrip())) or '  '
        tail_indent = _indent(source, a_end - 1)
        new_a = f'\n{indent}{temp} = {value};' + rename(a_text).rstrip() + f'\n{indent}{variable} = {temp};\n{tail_indent}'
        spans = _simple_statements(clean, b_body, b_end - 1)
        if not spans or len(spans) < 2:
            continue
        for count in range(1, min(len(spans), 6)):
            if any(re.search(r'[{}]', clean[a:b]) for a, b in spans[:count]):
                break
            head = source[b_start + 1:b_body] + rename(source[b_body:spans[0][1]])
            middle = rename(source[spans[0][1]:spans[count - 1][1]]) if count > 1 else ''
            new_b = head + middle + f'\n{indent}{variable} = {temp};' + source[spans[count - 1][1]:b_end - 1]
            prefix = source[:start] + hit[1] + source[start + hit[0].rindex('if'):a_start + 1]
            text = prefix + new_a + source[a_end - 1:b_start + 1] + new_b + source[b_end - 1:]
            decl_at = _declarations_end(part)
            text = text[:decl_at] + f'\n  {_decl(types[variable], temp)}' + text[decl_at:]
            result.append((FAMILY_HANDLE, text))
    return result


# ---------------------------------------------------------------------------------------------------------------------
def _effects(text):
    """(written base, names read, destination text) of one assignment statement; None when it is not one."""
    postfix = re.fullmatch(r'\s*(\w+)\s*(\+\+|--)\s*;\s*', text)
    if postfix:
        return postfix[1], {postfix[1]}, postfix[1]
    match = re.fullmatch(r'\s*([^=;]+?)\s*((?:[-+*/%&|^]|<<|>>)?=)\s*([^;]*?)\s*;\s*', text, re.S)
    if not match or '++' in text or '--' in text or re.search(rf'{IDENT}\s*\(', text) or match[3].startswith('='):
        return None
    left = match[1]
    base = re.match(rf'\s*\*?\s*\(?\s*({IDENT})', left)
    if not base:
        return None
    subscripts = ' '.join(re.findall(r'\[([^\]]*)\]', left))
    reads = set(re.findall(IDENT, match[3])) | set(re.findall(IDENT, subscripts))
    if match[2] != '=':
        reads.add(base[1])
    return base[1], reads, left


def _distinct(left_a, left_b):
    """Two destinations of one base that differ in a literal subscript or field cannot be the same object."""
    pattern = r'\[\s*(0[xX][0-9a-fA-F]+|\d+)\s*\]|->\s*(\w+)|\.\s*(\w+)'
    a, b = re.findall(pattern, left_a), re.findall(pattern, left_b)
    return bool(a and b and a != b)


def _independent(a, b):
    base_a, reads_a, left_a = a
    base_b, reads_b, left_b = b
    if base_a in reads_b or base_b in reads_a:
        return False
    if base_a == base_b:
        return _distinct(left_a, left_b)
    return True


def _runs(clean, start, end):
    """Runs of consecutive simple statements in [start, end), nested blocks included."""
    runs, run, cursor = [], [], start
    while cursor < end:
        match = re.compile(r'\s*').match(clean, cursor)
        cursor = match.end()
        if cursor >= end:
            break
        char = clean[cursor]
        if char in '{}':
            runs.append(run)
            run = []
            cursor += 1
            continue
        word = re.match(r'(if|for|while|switch)\s*\(', clean[cursor:end])
        if word:
            runs.append(run)
            run = []
            cursor = close(clean, cursor + word.end() - 1) or end
            continue
        word = re.match(r'(else|do)\b', clean[cursor:end])
        if word:
            runs.append(run)
            run = []
            cursor += word.end()
            continue
        statement = re.compile(r'[^;{}]*;').match(clean, cursor)
        if not statement or statement.end() > end:
            break
        effects = None if re.match(r'(?:return|break|continue|goto|case|default)\b', clean[cursor:]) else _effects(clean[cursor:statement.end()])
        if effects is None:
            runs.append(run)
            run = []
        else:
            run.append((cursor, statement.end(), effects))
        cursor = statement.end()
    runs.append(run)
    return [r for r in runs if len(r) >= 2]


def store_run_move(source, name):
    part = _usable(source, name)
    if not part:
        return []
    result, seen = [], set()
    for run in _runs(part.clean, part.opening + 1, part.end - 1):
        for first in range(len(run) - 1):
            _emit(source, run[first:first + WINDOW], result, seen)
    return result[:LIMIT]


def _emit(source, run, result, seen):
    texts = [source[a:b] for a, b, _ in run]
    first, last = run[0][0], run[-1][1]
    gaps = [source[run[i][1]:run[i + 1][0]] for i in range(len(run) - 1)]
    moves = sorted(((i, j) for i in range(len(run)) for j in range(len(run)) if i != j), key=lambda m: (abs(m[0] - m[1]), m))
    made = 0
    for i, j in moves:
        order = list(range(len(run)))
        order.remove(i)
        order.insert(j, i)
        low, high = sorted((i, j))
        if not all(_independent(run[i][2], run[k][2]) for k in range(low, high + 1) if k != i):
            continue
        body = texts[order[0]]
        for k in range(1, len(order)):
            body += gaps[k - 1] + texts[order[k]]
        text = source[:first] + body + source[last:]
        if text not in seen:
            seen.add(text)
            result.append((FAMILY_MOVE, text))
            made += 1
            if made == 12:
                break

# ---------------------------------------------------------------------------------------------------------------------
def chain(source, name):
    """Every step of the match that is the same rewrite wherever it applies, as one child.

    Each of them alone is no better (the pointer inline and the captures even score worse); the hand match needed all of
    them before the register rows fell (2820 -> 1970 for the first five, then the stores moved and the copies of the
    parameters dropped). The store moves differ from function to function, so they stay single steps for the search."""
    text = source
    for family in (element_pointer_inline, condition_capture, value_reuse_before_branch, arm_scoped_scratch,
                   reassociation_temp, arm_handle_copy):
        for _ in range(6):
            offered = family(text, name)
            if not offered:
                break
            offered = [item for item in offered if item[1] != text]
            if not offered:
                break
            text = offered[-1][1] if family is arm_scoped_scratch else offered[3 if family is arm_handle_copy and len(offered) > 3 else 0][1]
    return [(FAMILY_CHAIN, text)] if text != source else []


def variants(source, name, header=''):
    out = []
    for family in (element_pointer_inline, condition_capture, value_reuse_before_branch, arm_scoped_scratch,
                   reassociation_temp, arm_handle_copy, store_run_move):
        out += family(source, name)
    return chain(source, name) + out
