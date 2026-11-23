"""The same statement moved the same way in every arm that has it.

Two arms of an `if`/`else` (or the arms of a `switch`) that end in the same store keep that store at the same place in
the program only as long as GCC 2.7.2's jump pass can cross-jump the identical tails (the final `jump_optimize` merges
two jumps to one label whose preceding insns match, back to the branch). Moving the store one or two statements in one
arm alone breaks the match for that arm and shows as a worse score; moving it in both is the scheduling change that
was meant, so a search that edits one statement at a time never sees it: on a 616-instruction audio command builder
the target's order of a halfword store after the stack-run stores took two edits (the store up two statements in two
arms, 2980 -> 2820, each edit alone leaving the score at 2980 or worse), and the greedy statement-move passes and the library's
adjacent-swap families stalled there.

For every one-line statement that appears in two or more straight-line runs of the function (the same text), a child
moves it by -3 .. +3 positions in every one of those runs by the same amount, when each run has room and every statement
it crosses is a plain one-line statement (no label, `if`, brace, call or `volatile`). One child per statement and offset,
at most 24 children. The order of a store relative to its neighbours is a hypothesis about the scheduler read off the
target, not from the compiler's source: every child is judged."""
import re

from .integer_repair_support import view

FAMILY = 'identical_statement_comove'
FAMILIES = (FAMILY,)

LIMIT = 24
OFFSETS = (-3, -2, -1, 1, 2, 3)
_DECL = re.compile(r'^(?:register\s+)?(?:u8|u16|u32|s8|s16|s32|f32|f64|unsigned|int|char|short|long|void|struct|const)\b')
_CALL = re.compile(r'\b[A-Za-z_]\w*\s*\(')


def _plain(line):
    text = line.strip()
    if not text.endswith(';') or text.startswith(('if', 'else', 'while', 'for', 'switch', 'return', 'goto', 'case', 'default',
                                                 'break', 'continue', '#')):
        return False
    if '{' in text or '}' in text or _DECL.match(text) or re.search(r'(?<!\w):(?!:)', text) or 'volatile' in text:
        return False
    stripped = re.sub(r'\(\s*(?:u8|u16|u32|s8|s16|s32|f32|f64|int|unsigned|char|short|long)\s*\*?\s*\)', '', text)
    return not _CALL.search(stripped)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    lines = source.split('\n')
    begin = source.count('\n', 0, part.opening)
    finish = source.count('\n', 0, part.end)
    where = {}
    for index in range(begin + 1, min(finish, len(lines))):
        if _plain(lines[index]):
            where.setdefault(lines[index].strip(), []).append(index)
    out = []
    for text, found in where.items():
        if len(found) < 2 or len(found) > 8:
            continue
        for offset in OFFSETS:
            moved = _move_all(lines, found, offset, begin + 1, finish)
            if moved:
                out.append((FAMILY, '\n'.join(moved)))
                if len(out) >= LIMIT:
                    return out
    return out


def _move_all(lines, found, offset, low, high):
    """`lines` with each statement at `found` moved `offset` lines, or None when one run cannot take it."""
    result = list(lines)
    # work from the bottom up for a downward move, from the top down for an upward one: the indexes stay valid
    for index in sorted(found, reverse=offset > 0):
        target = index + offset
        if target < low or target >= high:
            return None
        span = range(min(index, target), max(index, target) + 1)
        if any(not _plain(result[k]) for k in span):
            return None
        line = result.pop(index)
        result.insert(target, line)
    return result if result != lines else None


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 270}
