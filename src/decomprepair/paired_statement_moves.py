"""Two statement moves at once: the order a near-match needs when neither move helps alone.

A function whose remaining difference is registers and instruction order often needs two statements relocated
together: a constant assigned earlier AND a counter initialised later change which saved register each gets,
and neither change alone does (a one-move search sits at a local minimum while the pair reaches the target).
This proposes the pairs. It never compiles or judges: the caller scores each candidate and keeps improvements.

Only reorderings that cannot change what the function does are proposed. A statement is movable when it is a plain
expression statement directly inside a block; loops, conditionals, labels, gotos, declarations and returns are
barriers a statement never crosses, and each block's statements are their own run. An initialised declaration
(`f32 c = x * 2.0f;`) is a barrier too, so its value could never move: `split_declarations` rewrites a block's
leading `T name = value;` lines as `T name;` plus `name = value;` right after the block's last declaration (the
same order, so the same evaluation), and the moves are proposed on that source as well. Two statements swap past each
other only when neither writes a name the other touches, and the memory rules hold: a call, or a write through a
pointer, array or address, never crosses a statement that reads or writes anything but a local, and a statement
that names a macro stays where it is. Functions with `volatile` or `asm` get nothing.
"""
import random
import re
from dataclasses import dataclass, field

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILIES = ('paired_statement_moves', 'wrapped_call_split')
LIMIT = 64
MAX_STATEMENTS = 400
EXHAUSTIVE_MOVES = 24  # up to this many single moves, every pair is enumerated before sampling

TYPES = {'char', 'short', 'int', 'long', 'float', 'double', 'void', 'unsigned', 'signed', 'struct', 'union', 'enum',
         'register', 'static', 'extern', 'const', 'typedef', 'u8', 'u16', 'u32', 'u64', 's8', 's16', 's32', 's64',
         'f32', 'f64', 'volatile'}
KEYWORDS = {'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'default', 'goto', 'return', 'break', 'continue',
            'sizeof'}
NUMBER_LITERAL = re.compile(r'\b(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?)[uUlLfF]*\b')
ASSIGN = re.compile(r'(?<![=!<>+\-*/%&|^])(?:[+\-*/%&|^]|<<|>>)?=(?!=)')
UNARY_MEMORY = re.compile(r'(?:^|[=(,+\-*/&|<>!?:;~]\s*)(?:\*|&(?!&))')


@dataclass
class Stmt:
    start: int
    end: int
    names: set = field(default_factory=set)
    writes: set = field(default_factory=set)
    calls: bool = False
    indirect_write: bool = False
    indirect_read: bool = False
    global_names: set = field(default_factory=set)
    global_writes: set = field(default_factory=set)
    writes_local: bool = False
    unknown: bool = False
    slot: tuple = ()  # (base, constant index) of a store whose value reads no memory


def _skip_space(text, at, stop):
    while at < stop and text[at].isspace():
        at += 1
    return at


def _statement_end(text, at, stop):
    """The end of the plain statement starting at `at`: its terminating ';' at bracket depth 0."""
    depth = 0
    for pos in range(at, stop):
        char = text[pos]
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif char == ';' and depth == 0:
            return pos + 1
    return None


def _barrier_end(text, at, stop, blocks):
    """The end of a compound statement or label starting at `at`; interiors of braces go to `blocks`."""
    if text[at] == '{':
        end = close(text, at, '{', '}')
        if end is None or end > stop:
            return None
        blocks.append((at + 1, end - 1))
        return end
    word = re.match(IDENT, text[at:stop])
    word = word[0] if word else ''
    if word in ('if', 'while', 'for', 'switch'):
        pos = _skip_space(text, at + len(word), stop)
        if pos >= stop or text[pos] != '(':
            return None
        pos = close(text, pos, '(', ')')
        if pos is None:
            return None
        pos = _skip_space(text, pos, stop)
        if pos >= stop:
            return None
        end = _barrier_end(text, pos, stop, blocks) if (text[pos] == '{' or re.match(IDENT, text[pos:])
                                                       and re.match(IDENT, text[pos:])[0] in KEYWORDS - {'sizeof'}) \
            else _statement_end(text, pos, stop)
        if end is None:
            return None
        if word == 'if':
            after = _skip_space(text, end, stop)
            if re.match(r'else\b', text[after:stop]):
                after = _skip_space(text, after + 4, stop)
                inner = _barrier_end(text, after, stop, blocks) if (text[after:after + 1] == '{' or re.match(
                    r'(?:if|for|while|do|switch)\b', text[after:stop])) else _statement_end(text, after, stop)
                return inner
        return end
    if word == 'do':
        pos = _skip_space(text, at + 2, stop)
        end = _barrier_end(text, pos, stop, blocks) if text[pos:pos + 1] == '{' else _statement_end(text, pos, stop)
        if end is None:
            return None
        pos = _skip_space(text, end, stop)
        if not re.match(r'while\b', text[pos:stop]):
            return None
        return _statement_end(text, pos, stop)
    if word in ('case', 'default'):
        colon = text.find(':', at, stop)
        return colon + 1 if colon >= 0 else None
    if re.match(rf'{IDENT}\s*:(?!:)', text[at:stop]) and word not in KEYWORDS:
        return text.index(':', at) + 1
    return _statement_end(text, at, stop)


def _is_declaration(statement):
    first = re.match(IDENT, statement)
    if first and first[0] in TYPES:
        return True
    return bool(re.match(rf'{IDENT}\s+\**\s*{IDENT}\s*[;,=\[]', statement))


def _runs(clean, start, stop, runs, limit):
    """Runs of consecutive plain statements in the block clean[start:stop], and in every block nested in it."""
    current, blocks, at = [], [], start
    while True:
        at = _skip_space(clean, at, stop)
        if at >= stop:
            break
        word = re.match(IDENT, clean[at:stop])
        word = word[0] if word else ''
        compound = (clean[at] == '{' or word in KEYWORDS - {'sizeof'} or
                    (re.match(rf'{IDENT}\s*:(?!:)', clean[at:stop]) is not None and word not in KEYWORDS))
        end = _barrier_end(clean, at, stop, blocks) if compound else _statement_end(clean, at, stop)
        if end is None:
            return False
        if compound or _is_declaration(clean[at:end]):
            if current:
                runs.append(current)
            current = []
        else:
            current.append(Stmt(at, end))
            limit[0] -= 1
            if limit[0] < 0:
                return False
        at = end
    if current:
        runs.append(current)
    for inner_start, inner_stop in blocks:
        if not _runs(clean, inner_start, inner_stop, runs, limit):
            return False
    return True


def _declared(clean, part):
    """Names the function declares itself: its parameters and its local declarations."""
    names = set()
    head = clean[:part.opening]
    signature = head[head.rfind('(') + 1:] if '(' in head else ''
    for piece in signature.split(','):
        found = re.findall(IDENT, piece)
        if found and found[-1] not in TYPES:
            names.add(found[-1])
    body = part.clean[part.opening + 1:part.end]
    for hit in re.finditer(r'(?:^|(?<=[;{}]))\s*((?:register\s+|unsigned\s+|signed\s+|static\s+|const\s+)*'
                           r'(?:char|short|int|long|float|double|[su](?:8|16|32|64)|f32|f64|struct\s+\w+)\b[^;(){}]*);',
                           body):
        for piece in hit[1].split(','):
            piece = re.sub(r'=.*', '', piece)
            found = re.findall(IDENT, piece)
            if found:
                names.add(found[-1])
    # a declaration that starts with a call (`f32 c = cosf(x);`) has parentheses the list above stops at: its
    # name is still the function's own local, not a global
    for hit in re.finditer(r'(?:^|(?<=[;{}]))\s*(?:register\s+|unsigned\s+|signed\s+|static\s+|const\s+)*'
                           rf'(?:char|short|int|long|float|double|[su](?:8|16|32|64)|f32|f64|struct\s+\w+)\s*\**\s*({IDENT})\s*=',
                           body):
        names.add(hit[1])
    return names


def _facts(clean, stmt, locals_, macros):
    text = clean[stmt.start:stmt.end - 1]
    # numbers are not names: the 'x64' in 0x64 used to look like a global and pin every constant behind each call
    words = NUMBER_LITERAL.sub(' ', text)
    names = {n for n in re.findall(IDENT, words) if n not in KEYWORDS and n not in TYPES}
    stmt.names = names
    if names & macros or re.search(r'\b(?:asm|__asm__)\b|\?|,(?![^(\[]*[)\]])', text):
        stmt.unknown = True
        return
    function_names = set(re.findall(rf'({IDENT})\s*\(', words)) - KEYWORDS - {'sizeof'}
    stmt.calls = bool(function_names)
    others = names - function_names
    stmt.global_names = others - locals_
    assignment = None
    depth = 0
    for hit in ASSIGN.finditer(text):
        depth = text[:hit.start()].count('(') - text[:hit.start()].count(')')
        depth += text[:hit.start()].count('[') - text[:hit.start()].count(']')
        if depth == 0:
            assignment = hit
            break
    inc = re.search(rf'(?:\+\+|--)\s*({IDENT})|({IDENT})\s*(?:\+\+|--)', text)
    if assignment:
        left = text[:assignment.start()].strip()
        plain = re.fullmatch(IDENT, left)
        if plain:
            stmt.writes = {left}
            stmt.writes_local = left in locals_
        else:
            stmt.writes = set(re.findall(IDENT, NUMBER_LITERAL.sub(' ', left))) - KEYWORDS - TYPES
            stmt.indirect_write = True
        right = text[assignment.end():]
        stmt.indirect_read = bool(UNARY_MEMORY.search(right) or '[' in right or '->' in right)
        cell = re.fullmatch(rf'({IDENT})\s*\[\s*(0[xX][0-9a-fA-F]+|\d+)\s*\]', left)
        if cell and text[assignment.start():assignment.end()].strip() == '=' and not stmt.indirect_read:
            stmt.slot = (cell[1], int(cell[2], 0))
    elif inc:
        target = inc[1] or inc[2]
        stmt.writes = {target}
        stmt.writes_local = target in locals_
    elif not stmt.calls:
        stmt.unknown = True
    if stmt.calls or not assignment:
        stmt.indirect_read = stmt.indirect_read or bool(UNARY_MEMORY.search(text) or '[' in text or '->' in text)
    stmt.global_writes = {w for w in stmt.writes if w not in locals_}


def _touches_memory(stmt):
    return bool(stmt.global_names or stmt.indirect_read or stmt.indirect_write or stmt.calls)


def _writes_memory(stmt):
    return bool(stmt.global_writes or stmt.indirect_write or stmt.calls)


def conflict(a, b):
    """Whether swapping two statements could change what the function does (conservative)."""
    if a.unknown or b.unknown:
        return True
    if (a.slot and b.slot and a.slot[0] == b.slot[0] and a.slot[1] != b.slot[1] and not (a.calls or b.calls)
            and not (a.global_names | b.global_names) - {a.slot[0]}):
        # two stores into different constant cells of one array (a matrix, a record of words) whose values read
        # only locals: they touch different words, so either order writes the same bytes. Only the schedule
        # differs, and that is what a near match with register-only differences needs to move (a 16-store float
        # matrix function went 85 -> 0 by reordering its stores alone).
        return bool((a.writes - {a.slot[0]}) & b.names or (b.writes - {b.slot[0]}) & a.names)
    if a.writes & b.names or b.writes & a.names:
        return True
    if (a.calls and _touches_memory(b)) or (b.calls and _touches_memory(a)):
        return True
    if (a.indirect_write and _touches_memory(b)) or (b.indirect_write and _touches_memory(a)):
        return True
    return bool((a.indirect_read and _writes_memory(b)) or (b.indirect_read and _writes_memory(a)))


def _valid_moves(order, stmts):
    """(from, to) index pairs in `order` whose moved statement commutes with every statement it passes."""
    moves = []
    for i in range(len(order)):
        for j in range(len(order)):
            if j == i:
                continue
            lo, hi = (i + 1, j) if j > i else (j, i - 1)
            if all(not conflict(stmts[order[i]], stmts[order[k]]) for k in range(lo, hi + 1)):
                moves.append((i, j))
    return moves


def _apply(order, move):
    i, j = move
    new = list(order)
    new.insert(j, new.pop(i))
    return new


def _analysis(source, name, header):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean + '\n' + header):
        return None
    macros = set(re.findall(r'^\s*#\s*define\s+(' + IDENT + ')', header + '\n' + source, re.M))
    runs = []
    finish = close(part.clean, part.opening, '{', '}')
    if finish is None or not _runs(part.clean, part.opening + 1, finish - 1, runs, [MAX_STATEMENTS]):
        return None
    locals_ = _declared(part.clean, part)
    runs = [run for run in runs if len(run) > 1]
    for run in runs:
        for stmt in run:
            _facts(part.clean, stmt, locals_, macros)
    return runs


def _render(source, run, order):
    """The run's statements in a new order, each separator staying at its own position."""
    texts = [source[s.start:s.end] for s in run]
    seps = [source[run[k].end:run[k + 1].start] for k in range(len(run) - 1)]
    out = texts[order[0]]
    for k in range(1, len(order)):
        out += seps[k - 1] + texts[order[k]]
    return run[0].start, run[-1].end, out


DECLARATOR = re.compile(rf'((?:(?:register|unsigned|signed)\s+)*{IDENT}\b(?:\s+{IDENT}\b)?\s*\**\s*)\b({IDENT})\s*=(?!=)\s*(.*)', re.S)


def split_declarations(source, name):
    """The function with each block's leading `T name = value;` declarations split into a declaration and an
    assignment placed after the block's declarations, or None when it has none to split.

    Only single scalar declarators are split (no arrays, braces, commas, static or const), and nothing is split
    when a value names a variable declared later in the same block (it would then read the new one).
    """
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    finish = close(clean, part.opening, '{', '}')
    if finish is None:
        return None
    edits = []
    for brace in [part.opening] + [m.start() for m in re.finditer(r'\{', clean[part.opening + 1:finish])]:
        brace = brace if brace == part.opening else brace + part.opening + 1
        stop = close(clean, brace, '{', '}')
        if stop is None:
            return None
        at, decls = brace + 1, []
        while True:
            at = _skip_space(clean, at, stop - 1)
            end = _statement_end(clean, at, stop - 1) if at < stop - 1 else None
            text = clean[at:end - 1] if end else ''
            word = re.match(IDENT, text)
            if not end or not word or word[0] in KEYWORDS or not _is_declaration(text):
                break
            decls.append((at, end, text))
            at = end
        pieces, names = [], [re.findall(IDENT, re.sub(r'=.*', '', t, flags=re.S))[-1:] for _, _, t in decls]
        for k, (start, end, text) in enumerate(decls):
            hit = DECLARATOR.fullmatch(text.rstrip())
            if (not hit or re.search(r'\b(?:static|const|extern)\b|[{\[,]', hit[1] + hit[3])
                    or re.search(r'[{]|,(?![^(]*\))', hit[3])):
                continue
            later = {n for ns in names[k + 1:] for n in ns}
            if later & set(re.findall(IDENT, hit[3])):
                continue
            pieces.append(f'{hit[2]} = {source[start + hit.start(3):end - 1].strip()};')
            edits.append((start, end, f'{hit[1].rstrip()} {hit[2]};'.replace('* ', '*')))
        if pieces:
            last = decls[-1][1]
            indent = re.search(r'[ \t]*$', source[:decls[-1][0]])[0]
            edits.append((last, last, ''.join(f'\n{indent}{p}' for p in pieces)))
    if not edits:
        return None
    edits.sort(key=lambda e: (e[0], e[1]))
    return edit(source, edits)


def _sources(source, name):
    split = split_declarations(source, name)
    return [source] if split is None else [source, split]


def single_moves(source, name, header='', limit=10 ** 6):
    """Every candidate that relocates one statement (what a one-move search already tries), including the moves
    of a split declaration's value (`split_declarations`)."""
    found = []
    for at, origin in enumerate(_sources(source, name)):
        if at:
            found.append(origin)
        for candidate in _single_moves(origin, name, header, limit - len(found)):
            if candidate != source and candidate not in found:
                found.append(candidate)
        if len(found) >= limit:
            return found[:limit]
    return found


def _single_moves(source, name, header, limit):
    runs = _analysis(source, name, header)
    found = []
    for run in runs or ():
        base = list(range(len(run)))
        for move in _valid_moves(base, run):
            start, end, text = _render(source, run, _apply(base, move))
            found.append(edit(source, [(start, end, text)]))
            if len(found) >= limit:
                return found
    return found


def variants(source, name, header='', limit=LIMIT, seed=0, exclude=()):
    """Up to `limit` distinct candidates that apply two statement moves, in a seeded random order.

    Candidates one move can reach, the original, and anything in `exclude` are left out. A function with few
    movable statements has every pair enumerated; a long straight run is sampled, favouring statements that write a
    local (a counter or a held constant: what shapes register allocation).
    """
    seen = {source, *exclude, *single_moves(source, name, header)}
    found = []
    for origin in _sources(source, name):
        found += _variants(origin, name, header, limit - len(found), seed, seen)
        if len(found) >= limit:
            break
    return found


def _variants(source, name, header, limit, seed, seen):
    runs = _analysis(source, name, header)
    if not runs or limit <= 0:
        return []
    rng = random.Random(seed)
    pool = []
    for index, run in enumerate(runs):
        base = list(range(len(run)))
        moves = _valid_moves(base, run)
        pool += [(index, m) for m in moves]
    if not pool:
        return []
    found = []

    def emit(index, order):
        run = runs[index]
        start, end, text = _render(source, run, order)
        candidate = edit(source, [(start, end, text)])
        if candidate not in seen:
            seen.add(candidate)
            found.append((FAMILIES[0], candidate))

    if len(pool) <= EXHAUSTIVE_MOVES:
        for index, first in pool:
            run, base = runs[index], list(range(len(runs[index])))
            once = _apply(base, first)
            for second in _valid_moves(once, run):
                emit(index, _apply(once, second))
                if len(found) >= limit:
                    return found
        return found
    weights = [3 if runs[i][m[0]].writes_local else 1 for i, m in pool]
    attempts = 0
    while len(found) < limit and attempts < limit * 20:
        attempts += 1
        index, first = rng.choices(pool, weights)[0]
        run, base = runs[index], list(range(len(runs[index])))
        once = _apply(base, first)
        options = [m for m in _valid_moves(once, run) if m[0] != first[1]]
        if not options:
            continue
        emit(index, _apply(once, rng.choice(options)))
    return found


LITERAL = re.compile(r'[-+]?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*')


def _is_plain_call(text):
    """`f(...)` with nothing assigned: a call statement a one-shot scope can wrap."""
    body = text.strip()
    return bool(re.fullmatch(rf'{IDENT}\s*\(.*\)\s*;', body, re.S)) and not re.match(r'(?:if|while|for|switch|return|sizeof)\b', body)


def _is_local_literal(stmt, text):
    """`local = 5;`: a held constant, which commutes with everything that does not name the local."""
    hit = re.fullmatch(rf'\s*({IDENT})\s*=\s*({LITERAL.pattern})\s*;', text)
    return bool(hit) and stmt.writes_local


def wrapped_call_splits(source, name, header='', limit=LIMIT, exclude=()):
    """Candidates that wrap one call in `do { call; } while (0);` and move some of the held-constant assignments
    ahead of it to just after it.

    A one-shot loop around a call is a scheduling barrier: the compiler places a loop-invariant constant as late
    as it can inside its region, and loop notes end regions. Wrapping a call therefore decides where the constants
    land, and moving some of them past the call splits them across two regions, the way hand-written code does when
    one constant is wanted before the call and the others after it. Neither one-move nor two-move search can reach
    this: it is one wrap and several coordinated moves. (A real function went from 325 to 120 this way.)

    Every moved statement is a local assigned a literal and commutes with each statement it passes; the wrap itself
    changes no behaviour. Candidates are ordered by the number of constants moved, fewest first, and an empty
    subset (the bare wrap) comes first for each call.
    """
    runs = _analysis(source, name, header)
    seen = {source, *exclude}
    found = []
    for run in runs or ():
        texts = [source[s.start:s.end] for s in run]
        base = list(range(len(run)))
        for j, call in enumerate(run):
            if not _is_plain_call(texts[j]) or call.unknown:
                continue
            held = [i for i in range(j) if _is_local_literal(run[i], texts[i])]
            for size in range(0, min(len(held), 6) + 1):
                for chosen in _subsets(held, size):
                    if any(conflict(run[i], run[k]) for i in chosen for k in range(i + 1, j + 1) if k not in chosen):
                        continue
                    rest = [i for i in held if i not in chosen]
                    # the constants left before the call may stay where they are, or sink to just before it
                    # (one at a time, or all together): the region the wrapper starts is then theirs alone
                    for sunk in [()] + [(i,) for i in rest] + ([tuple(rest)] if len(rest) > 1 else []):
                        if any(conflict(run[i], run[k]) for i in sunk for k in range(i + 1, j) if k not in sunk
                               and k not in chosen):
                            continue
                        keep = [i for i in base[:j] if i not in chosen and i not in sunk]
                        order = keep + list(sunk) + [j] + list(chosen) + base[j + 1:]
                        wrapped = list(texts)
                        wrapped[j] = 'do { ' + texts[j].strip() + ' } while (0);'
                        out = wrapped[order[0]]
                        seps = [source[run[k].end:run[k + 1].start] for k in range(len(run) - 1)]
                        for k in range(1, len(order)):
                            out += seps[k - 1] + wrapped[order[k]]
                        candidate = edit(source, [(run[0].start, run[-1].end, out)])
                        if candidate not in seen:
                            seen.add(candidate)
                            found.append((FAMILIES[1], candidate))
                            if len(found) >= limit:
                                return found
    return found


def _subsets(items, size):
    if size == 0:
        yield ()
        return
    for k in range(len(items)):
        for rest in _subsets(items[k + 1:], size - 1):
            yield (items[k],) + rest
