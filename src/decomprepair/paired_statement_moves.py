"""Two statement moves at once: the order a near-match needs when neither move helps alone.

A function whose remaining difference is registers and instruction order often needs two statements relocated
together: a constant assigned earlier AND a counter initialised later change which saved register each gets,
and neither change alone does (a one-move search sits at a local minimum while the pair reaches the target).
This proposes the pairs. It never compiles or judges: the caller scores each candidate and keeps improvements.

Only reorderings that cannot change what the function does are proposed. A statement is movable when it is a plain
expression statement directly inside a block; loops, conditionals, labels, gotos, declarations and returns are
barriers a statement never crosses, and each block's statements are their own run. Two statements swap past each
other only when neither writes a name the other touches, and the memory rules hold: a call, or a write through a
pointer, array or address, never crosses a statement that reads or writes anything but a local, and a statement
that names a macro stays where it is. Functions with `volatile` or `asm` get nothing.
"""
import random
import re
from dataclasses import dataclass, field

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILIES = ('paired_statement_moves',)
LIMIT = 64
MAX_STATEMENTS = 400
EXHAUSTIVE_MOVES = 24  # up to this many single moves, every pair is enumerated before sampling

TYPES = {'char', 'short', 'int', 'long', 'float', 'double', 'void', 'unsigned', 'signed', 'struct', 'union', 'enum',
         'register', 'static', 'extern', 'const', 'typedef', 'u8', 'u16', 'u32', 'u64', 's8', 's16', 's32', 's64',
         'f32', 'f64', 'volatile'}
KEYWORDS = {'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'default', 'goto', 'return', 'break', 'continue',
            'sizeof'}
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
    for hit in re.finditer(r'(?:^|[;{}])\s*((?:register\s+|unsigned\s+|signed\s+|static\s+|const\s+)*'
                           r'(?:char|short|int|long|float|double|[su](?:8|16|32|64)|f32|f64|struct\s+\w+)\b[^;(){}]*);',
                           body):
        for piece in hit[1].split(','):
            piece = re.sub(r'=.*', '', piece)
            found = re.findall(IDENT, piece)
            if found:
                names.add(found[-1])
    return names


def _facts(clean, stmt, locals_, macros):
    text = clean[stmt.start:stmt.end - 1]
    names = {n for n in re.findall(IDENT, text) if n not in KEYWORDS and n not in TYPES}
    stmt.names = names
    if names & macros or re.search(r'\b(?:asm|__asm__)\b|\?|,(?![^(\[]*[)\]])', text):
        stmt.unknown = True
        return
    function_names = set(re.findall(rf'({IDENT})\s*\(', text)) - KEYWORDS - {'sizeof'}
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
            stmt.writes = set(re.findall(IDENT, left)) - KEYWORDS - TYPES
            stmt.indirect_write = True
        right = text[assignment.end():]
        stmt.indirect_read = bool(UNARY_MEMORY.search(right) or '[' in right or '->' in right)
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


def single_moves(source, name, header='', limit=10 ** 6):
    """Every candidate that relocates one statement (what a one-move search already tries)."""
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
    runs = _analysis(source, name, header)
    if not runs:
        return []
    seen = {source, *exclude, *single_moves(source, name, header)}
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
