"""One plain assignment in a run of independent ones moved to another place in the run.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) projectile update of 2,503 instructions: two arms record a
nearer hit with six or seven assignments in a row (`best = d; kind = 1; hitTarget = gTarget; savedPlayer = gPlayer;
pos = hitPos; surface = NULL;`). The target loads the two globals and stores the spilled locals in an order that only
the statement order reaches: moving one statement at a time, 2797 -> 2527 -> 2467 for the first arm and
2467 -> 2387 -> 2327 for the second. `adjacent_init_swap` swaps declarations, `statement_slide` moves `M2C_FIELD` cells;
neither moves a plain assignment through a run.

assignment_run_move
    In a run of three to eight consecutive lines at one indent, each `lhs = rhs;` with no call, `++`/`--` or
    compound assignment, each statement is moved to every other position of the run where it commutes with every
    statement it passes (it writes nothing they read or write, they write nothing it reads; identifiers compared,
    a store into the frame struct `local` assumed to touch only reads of `local`, any other store all
    memory). One child per move, nearest moves first.
    The exact judge decides.
"""
import re

FAMILY = 'assignment_run_move'
FAMILIES = (FAMILY,)
LIMIT = 160
_ID = re.compile(r'[A-Za-z_]\w*')
_LINE = re.compile(r'^(?P<indent>[ \t]+)(?P<lhs>[^=;{}()]*?(?:\([^;{}]*\))?[^=;{}]*?)\s*=(?!=)\s*(?P<rhs>[^;{}]+);[ \t]*$')
_CALL = re.compile(r'\b[A-Za-z_]\w*\s*\(')
_CASTS = {'char', 'u8', 's8', 'u16', 's16', 'u32', 's32', 'f32', 'f64', 'void', 'int', 'unsigned', 'signed', 'sizeof'}


def _statement(line):
    found = _LINE.match(line)
    if not found:
        return None
    lhs, rhs = found.group('lhs'), found.group('rhs')
    if re.search(r'[-+*/%&|^<>!]$', lhs.strip()) or '++' in line or '--' in line:
        return None
    if any(m.group().rstrip('( ').strip() not in _CASTS for m in _CALL.finditer(lhs + ' ' + rhs)):
        return None
    frame = re.search(r'\blocal\b', lhs) and '->' not in lhs
    memory_write = ('frame' if frame else 'any') if ('*' in lhs or '->' in lhs or '[' in lhs or '.' in lhs) else None
    memory_read = {'frame' if re.search(r'\blocal\b', rhs) else None,
                   'any' if re.search(r'\b(?!local\b)[A-Za-z_]\w*\b', rhs) else None} - {None}
    base = _ID.findall(lhs)
    written = {base[-1]} if base and not memory_write else set()
    reads = set(_ID.findall(rhs)) | (set(_ID.findall(lhs)) - written)
    return found.group('indent'), written, reads, memory_write, memory_read


def _commute(a, b):
    if a[1] & (b[1] | b[2]) or b[1] & a[2]:
        return False
    return not (_clash(a[3], b[3], b[4]) or _clash(b[3], a[3], a[4]))


def _clash(write, other_write, other_reads):
    """Whether a memory write (`'frame'` for the frame struct, `'any'`) may touch the other statement's memory."""
    if not write:
        return False
    touched = set(other_reads) | ({other_write} if other_write else set())
    if write == 'frame':
        return 'frame' in touched or other_write == 'any'
    return bool(touched)


def _runs(lines):
    i = 0
    while i < len(lines):
        parsed = _statement(lines[i])
        if not parsed:
            i += 1
            continue
        run = [(i, parsed)]
        j = i + 1
        while j < len(lines) and len(run) < 8:
            nxt = _statement(lines[j])
            if not nxt or nxt[0] != parsed[0]:
                break
            run.append((j, nxt))
            j += 1
        if len(run) >= 3:
            yield run
        i = j


def variants(source, name):
    lines = source.split('\n')
    moves = []
    for run in _runs(lines):
        start = run[0][0]
        for k, (_, moved) in enumerate(run):
            for target in range(len(run)):
                if target == k:
                    continue
                passed = run[target:k] if target < k else run[k + 1:target + 1]
                if all(_commute(moved, other) for _, other in passed):
                    moves.append((abs(target - k), start, k, target, len(run)))
    moves.sort()
    result, seen = [], set()
    for _, start, k, target, size in moves:
        block = lines[start:start + size]
        line = block.pop(k)
        block.insert(target, line)
        text = '\n'.join(lines[:start] + block + lines[start + size:])
        if text not in seen:
            seen.add(text)
            result.append((FAMILY, text))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
