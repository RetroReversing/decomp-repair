"""The statements between an `if`/`else` chain and the `break;` that ends a switch case, written at the end of each arm
that falls through to them: jump2 cross-jumps the arms' identical tails back into one.

On a 485-instruction N64 audio thread (SN64 GCC 2.8.1, `sn-n64-281 -G0 -mips3 -O2 ...`) one case read

    if (arg == cur) { if (handle != 0) { break; } } else { ...; play(arg, bank); cur = arg; }
    handle = start(bank);
    setvol(handle, vol);
    break;

and the shared tail took its own copy of the bank address and re-read `handle` after the store. The target builds the
bank address separately on each path (one copy from the hoisted register, one fresh `lui`/`addiu` before a jump into
the shared `jal`) and passes the call's result straight on: the game wrote both statements in each arm and the final
jump optimisation merged the identical tails. Moving the first statement alone was 26300 -> 25760; both, 25060 with
every register row gone. A hypothesis from jump.c's cross-jumping and cse's extended blocks; the judge decides.

tail_run_into_arms
    For a braced `if`/`else` chain followed by one to four plain one-line statements and then `break;`, the first k
    statements (every k, longest first) written at the end of each arm that does not end in `return`, `goto`, `break`
    or `continue`, and removed after the chain.
"""
import re

from .arm_block_support import arm_chain, brace_pairs
from .integer_repair_support import edit, view

FAMILY = 'tail_run_into_arms'
FAMILIES = (FAMILY,)
MAX_RUN = 4
EXITS = re.compile(r'(?:return|goto|break|continue)\b[^;{}]*;\s*$')
_CONTROL = re.compile(r'^\s*(?:if|for|while|do|switch|return|break|continue|goto|case|default|else)\b')


def _lines(source, part):
    out, at = [], part.opening + 1
    for line in source[part.opening + 1:part.end].splitlines(keepends=True):
        start, at = at, at + len(line)
        out.append((start, start + len(line.rstrip('\r\n')), part.clean[start:start + len(line.rstrip('\r\n'))]))
    return out


def _plain(text):
    text = text.strip()
    return text.endswith(';') and not re.search(r'[{}]', text) and not _CONTROL.match(text)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return []
    by_close = {close_at: open_at for open_at, close_at in pairs.items()}
    lines = _lines(source, part)
    out = []
    for i, (_, _, text) in enumerate(lines):
        if text.strip() != 'break;':
            continue
        j = i - 1
        while j >= 0 and i - j <= MAX_RUN and _plain(lines[j][2]):
            j -= 1
        run = list(range(j + 1, i))
        if not run or j < 0 or lines[j][2].strip() != '}':
            continue
        closing = lines[j][0] + lines[j][2].index('}')
        blocks = arm_chain(clean, by_close, closing)
        if not blocks or len(blocks) < 2:
            continue
        for k in range(len(run), 0, -1):
            moved = [source[lines[r][0]:lines[r][1]].strip() for r in run[:k]]
            edits, ok = [], True
            for a, b in blocks:
                body = clean[a + 1:b]
                if EXITS.search(body.rstrip()):
                    continue
                if clean[clean.rfind('\n', 0, b) + 1:b].strip():
                    ok = False  # the closing brace shares its line with a statement
                    break
                brace_indent = re.match(r'[ \t]*', source[clean.rfind('\n', 0, b) + 1:]).group(0)
                inner = brace_indent + '    '
                at = clean.rfind('\n', 0, b) + 1
                edits.append((at, at, ''.join(f'{inner}{m}\n' for m in moved)))
            if not ok or not edits:
                continue
            for r in run[:k]:
                start, end, _ = lines[r]
                edits.append((start, end + 1, ''))
            text = edit(source, edits)
            if text != source and all(text != t for _, t in out):
                out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
