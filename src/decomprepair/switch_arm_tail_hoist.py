"""The statement every arm of a guarded `switch` ends with, written once after the `if`, where the default reaches it.

m2c writes a loop step that every path runs into each arm of a dispatch, and once more in the `else` of the guard
around it:

    if (e->kind != 0) {
        switch (e->kind) {
        case 2: two(e); i += 1; break;
        case 100: other(e); i += 1; break;
        case 418: last(e); goto block_81;
        }
    } else {
block_81:
        i += 1;
    }

The values with no arm then skip the step, which the target does not do: its range check branches to the same label as
the guard, in front of the one `addiu`. The game's source had the step once:

    if (e->kind != 0) {
        switch (e->kind) { case 2: two(e); break; ... case 418: last(e); break; }
    }
    i += 1;

Offered only on that evidence (the branch after the range check and an earlier branch name one label), for a switch
that ends the `if`'s block, has no `default:`, and whose every `break;` follows the `else`'s statement (or heads an
arm with nothing in it). With each arm's copy the counter has one reference per arm and takes the register the
target gives the entry pointer.

An SN GCC 2.8.1 N64 entity-pool dispatch (337 instructions, 74 handlers): 865, registers and order only, with the
per-arm copies and 0 with the step after the `if`.
"""
import re

from .integer_repair_support import view
from .pattern_repairs import close
from .switch_empty_case import _switches

FAMILY = 'switch_arm_tail_hoist'
FAMILIES = (FAMILY,)
_ELSE = re.compile(r'\s*\}(?P<else>\s*else\s*\{)')
_LABELLED = re.compile(r'\s*(?:(?P<label>[A-Za-z_]\w*)\s*:(?!:))?(?P<run>[^{}:]*;)\s*$')
_BRANCH = re.compile(r'^\s*(?:/\*.*?\*/\s*)?b\w*\s+(?:[^,\n]+,\s*)*(\.L\w+)\s*$')
_CHECK = re.compile(r'\bsltiu\b')


def shared_exit(asm):
    """Whether the branch after a range check goes where an earlier branch goes: the values with no entry join the
    guard's other path."""
    lines = (asm or '').splitlines()
    seen = set()
    for number, line in enumerate(lines):
        if _CHECK.search(line):
            for later in lines[number + 1:number + 3]:
                branch = _BRANCH.match(later)
                if branch and branch[1] in seen:
                    return True
        branch = _BRANCH.match(line)
        if branch:
            seen.add(branch[1])
    return False


def _tokens(run):
    return r'\s*'.join(re.escape(token) for token in re.findall(r'\w+|[^\w\s]', run))


def variants(source, name, asm):
    if not shared_exit(asm):
        return []
    part = view(source, name)
    if not part:
        return []
    out = []
    for brace, end, body in _switches(part):
        # `end` is the switch's `}`; the next one closes the `if`, whose `else` holds the statement
        other = _ELSE.match(part.clean, end + 1)
        if not other or re.search(r'(?<![\w])(?:default|for|while|do|continue)\b', body):
            continue
        opening = other.end('else') - 1
        closing = close(part.clean, opening, '{', '}')
        if not closing:
            continue
        closing -= 1  # `close` answers the offset past the brace
        tail = _LABELLED.match(part.clean[opening + 1:closing])
        if not tail:
            continue
        label, run = tail['label'], tail['run'].strip()
        written = source[opening + 1 + tail.start('run'):opening + 1 + tail.end('run')].strip()
        if not run or re.search(r'(?<![\w])(?:return|goto|break)\b', run):
            continue
        jumps = [m for m in re.finditer(rf'(?<![\w])goto\s+{re.escape(label)}\s*;', body)] if label else []
        if label and len(re.findall(rf'(?<![\w])goto\s+{re.escape(label)}\b', part.clean)) != len(jumps):
            continue
        edits, copies, ok = [], 0, True
        for stop in re.finditer(r'(?<![\w])break\s*;', body):
            before = body[:stop.start()]
            copy = re.search(rf'(?<![\w]){_tokens(run)}\s*$', before)
            if copy and before[:copy.start()].rstrip().endswith((';', ':', '}', '{')):
                edits.append((brace + copy.start(), brace + stop.start(), ''))
                copies += 1
            elif not before.rstrip().endswith(':'):
                ok = False
                break
        for jump in jumps:
            # a jump to the `else` runs the statement once more: only one that follows no copy of it may become a break
            if re.search(rf'(?<![\w]){_tokens(run)}\s*$', body[:jump.start()]):
                ok = False
                break
            edits.append((brace + jump.start(), brace + jump.end(), 'break;'))
        if not ok or not copies or not re.search(r'(?:\bbreak|\bgoto\s+\w+|\breturn\b[^;{}]*)\s*;\s*$', body):
            continue
        close_if = end + 1 + other.group().index('}')
        indent = re.search(r'[ \t]*$', source[:close_if])[0]
        # after the `else`'s brace: the statement; from the `if`'s brace to there: nothing
        edits.append((close_if + 1, closing + 1, f'\n{indent}{written}'))
        text = source
        for start, stop, new in sorted(edits, reverse=True):
            text = text[:start] + new + text[stop:]
        out.append((FAMILY, text))
    return out[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',), 'order': 1500}
