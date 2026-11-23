"""An identical run of statements written twice, the earlier copy a `goto` into the later one.

A state machine written the way its authors wrote it holds the same handful of statements in several arms (the flag
updates every "activate" step does, a shared "switch off" run). The compiled target has ONE copy of the run: the first
arm branches into the other's. GCC 2.7.2's final jump pass would merge two identical tails by itself, but only when the
labels in front of them are older than the pass and nothing of its own sits between the run and the join; a run in a
second switch, or one a conditional branch reaches from two sides, stays doubled, and the doubled copy is the whole
difference (14840 -> 12470 -> 7595 -> 235 on a 1173-instruction track-trigger state machine, one run at a time:
docs/learnings/function/identical-run-goto-state-machine-arms.md). The goto is the source shape of the merge.

    case 0:                                    case 0:
        if (ready) {                               if (ready) {
            a = 1;                                     goto shared_run_1;
            b = 2;                  ->             }
            s = 2;                                 break;
        }                                      case 1:
        break;                                     if (go) {
    case 1:                                        shared_run_1:
        if (go) {                                      a = 1;
            a = 1;                                     b = 2;
            b = 2;                                     s = 2;
            s = 2;                                 }
        }                                          break;
        break;

Each child jumps from one copy to the other, in both directions. Both copies must be maximal runs of whole lines with no
declaration, label, `case` or `return` in them, balanced in braces, of at least two lines and 60 characters, and each
must be followed by nothing but closing braces and a `break;`, so what runs after them is the same. A label must sit before a statement, so the
line above the later copy must end a statement or open a block.
"""
import re

from .csource import _blank, find

FAMILY = 'identical_run_goto'
FAMILIES = (FAMILY,)

LIMIT = 12
MIN_LINES = 2
MIN_CHARS = 60
_DECLARATION = re.compile(
    r'^(?:register\s+|static\s+|volatile\s+|const\s+)*(?:unsigned\s+|signed\s+)?'
    r'(?:void|char|short|int|long|float|double|[us](?:8|16|32|64)|f(?:32|64)|[A-Z]\w*)\b[\s*]+\w+\s*(?:\[[^\]]*\])?\s*(?:=[^=].*)?;$')
_LABEL = re.compile(r'^\w+\s*:(?!:)')
_BARRED = re.compile(r'\b(?:case|default|return|goto|switch|for|while|do|asm)\b')
_BREAK = 'break;'


def _lines(clean, source, opening, end):
    """(start offset, end offset, normalised text) of each line of the body."""
    result = []
    pos = opening + 1
    while pos < end:
        stop = source.find('\n', pos, end)
        stop = end if stop < 0 else stop
        key = ' '.join(clean[pos:stop].split())
        result.append((pos, stop, key))
        pos = stop + 1
    return result


def _balanced(keys):
    depth = 0
    for key in keys:
        depth += key.count('{') - key.count('}')
        if depth < 0:
            return False
    return depth == 0


def _plain(keys):
    for key in keys:
        if not key or _DECLARATION.match(key) or _LABEL.match(key) or _BARRED.search(key) or '#' in key:
            return False
    return True


def _tail(keys, at):
    """The closing braces from `at` on up to a `break;` (how many), None when something else follows the run: a closed
    block with no `else` is only a brace, so a run in `if (c) { ... }` and one just before `break;` fall into the same."""
    count = 0
    while at < len(keys) and keys[at] == '}':
        at += 1
        count += 1
    return count if at < len(keys) and keys[at] == _BREAK else None


def _runs(lines):
    """Maximal pairs of identical line runs (i, j, n) with i + n <= j, both followed by `break;`."""
    keys = [key for _, _, key in lines]
    found = []
    seen = set()
    for i in range(len(keys)):
        if not keys[i]:
            continue
        for j in range(i + 1, len(keys)):
            if keys[j] != keys[i] or (i, j) in seen:
                continue
            n = 0
            while j + n < len(keys) and i + n < j and keys[i + n] == keys[j + n] and keys[i + n]:
                seen.add((i + n, j + n))
                n += 1
            start = 0
            while start < n and keys[i + start] == '{':  # the block opening both copies sit in is not part of them
                start += 1
            run = keys[i + start:i + n]
            while run and run[-1] in (_BREAK, '}'):  # the closers they share are not part of the copy
                run = run[:-1]
            count = len(run)
            if count < MIN_LINES or not _balanced(run) or not _plain(run):
                continue
            if sum(len(k) for k in run) < MIN_CHARS:
                continue
            end_i, end_j = i + start + count, j + start + count
            if _tail(keys, end_i) is None or _tail(keys, end_j) is None:
                continue
            found.append((i + start, j + start, count))
    return found


def _statement_start(keys, at):
    before = next((k for k in reversed(keys[:at]) if k), '')
    return before.endswith('{') or (before.endswith((';', '}', ':')) and not before.startswith(('if', 'else', 'while', 'for')))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    end = span[1]
    lines = _lines(clean, source, opening, end)
    keys = [key for _, _, key in lines]
    result = []
    for pair, (i, j, n) in enumerate(sorted(_runs(lines), key=lambda r: -r[2]), 1):
        for jump, land in ((i, j), (j, i)):
            if not _statement_start(keys, land):
                continue
            label = f'shared_run_{pair}'
            first = lines[land][0]
            indent = re.match(r'[ \t]*', source[first:lines[land][1]]).group()
            start = lines[jump][0]
            goto = f'{re.match(r"[ \t]*", source[start:lines[jump][1]]).group()}goto {label};'
            marker = f'{indent}{label}:\n'
            if jump < land:
                later = source[:first] + marker + source[first:]
                text = later[:start] + goto + later[lines[jump + n - 1][1]:]
            else:
                later = source[:start] + goto + source[lines[jump + n - 1][1]:]
                text = later[:first] + marker + later[first:]
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
