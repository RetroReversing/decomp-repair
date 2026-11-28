"""m2c's guarded `for (;;)` search with a duplicated exit return, written as the `while` that returns what it finds.

A `strchr`-like scan (`while (*s != 0) { if (*s == c) return s; s++; } return NULL;`) comes back from m2c inside out:

    if (*p != 0) {
        for (;;) {
            if (*p != c) {
                p += 1;
                if (*p == 0) {
                    return NULL;            /* "Duplicate return node" */
                }
                continue;
            }
            break;
        }
        return p;
    }
    return NULL;

The `if` around the loop and the test after the step are the two copies of one `while` condition, and the `return` in
the loop is the function's own. Written as

    while (*p != 0) {
        if (*p == c) {
            return p;
        }
        p += 1;
    }
    return NULL;

a 13-instruction N64 string search (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`) went from 360 to 0.

Offered only when the two tests are opposites, the two returns are the same, the statements after the loop end in a
`return` and neither run of statements holds a brace, a jump or a label. The program is then the same one: the
condition is read at entry and after each step, as before. A candidate for the exact judge, never a verdict.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'guarded_search_return'
FAMILIES = (FAMILY,)
LIMIT = 8

GUARD = re.compile(r'\bif\s*\(')
LOOP = re.compile(r'\s*\{\s*for\s*\(\s*;\s*;\s*\)\s*\{\s*if\s*\(')
OPEN = re.compile(r'\s*\{')
BACK = re.compile(r'\bif\s*\(')
EXIT = re.compile(r'\s*\{\s*return\b([^;{}]*);\s*\}\s*continue\s*;\s*\}\s*break\s*;\s*\}')
RETURN = re.compile(r'\s*return\b([^;{}]*);')
# a run of statements that may move into or out of the new loop
UNSAFE = re.compile(r'[{}#]|\b(?:break|continue|goto|if|else|for|while|do|switch|case|default)\b|(?:^|;)\s*\w+\s*:(?!:)')
LAST_RETURN = re.compile(r'(?:^|;)\s*return\b[^;]*;\s*$')


def _squeeze(text):
    return re.sub(r'\s+', '', text)


def _opposite(condition):
    """`condition` negated: the comparison flipped for `==`/`!=` (exact for floats too), else wrapped in `!`."""
    text = condition.strip()
    flipped = negate(text)
    if flipped is not None and re.search(r'==|!=', text):
        return flipped
    if text.startswith('!') and flipped is not None:
        return flipped
    return f'!({text})'


def _opposites(first, second):
    return _squeeze(_opposite(first)) == _squeeze(second) or _squeeze(_opposite(second)) == _squeeze(first)


def _condition(clean, opening):
    """(start, end) of the text inside the parentheses opening at `opening`, or None."""
    end = close(clean, opening, '(', ')')
    return (opening + 1, end - 1) if end else None


def _rewrite(source, clean, guard):
    """(start, end, text) replacing the `if` that starts at match `guard` and the return after it, or None."""
    entry = _condition(clean, guard.end() - 1)
    if not entry:
        return None
    loop = LOOP.match(clean, entry[1] + 1)
    if not loop:
        return None
    skip = _condition(clean, loop.end() - 1)
    body = OPEN.match(clean, skip[1] + 1) if skip else None
    if not body:
        return None
    back = BACK.search(clean, body.end())
    if not back:
        return None
    step = (body.end(), back.start())
    again = _condition(clean, back.end() - 1)
    leave = EXIT.match(clean, again[1] + 1) if again else None
    if not leave:
        return None
    found_end = clean.find('}', leave.end())
    if found_end < 0:
        return None
    last = RETURN.match(clean, found_end + 1)
    if not last:
        return None
    stepped, found = clean[step[0]:step[1]], clean[leave.end():found_end]
    if UNSAFE.search(stepped) or UNSAFE.search(found) or not LAST_RETURN.search(found.rstrip()):
        return None
    if stepped.strip() and not stepped.rstrip().endswith(';'):
        return None
    if _squeeze(source[leave.start(1):leave.end(1)]) != _squeeze(source[last.start(1):last.end(1)]):
        return None
    condition = source[entry[0]:entry[1]].strip()
    if not _opposites(condition, source[again[0]:again[1]]):
        return None
    indent = source[source.rfind('\n', 0, guard.start()) + 1:guard.start()]
    if indent.strip():
        return None
    one, two, three = indent + '    ', indent + '        ', '\n'

    def lines(start, end, pad):
        kept = [line.strip() for line in clean[start:end].split(';')]
        spans, at = [], start
        for line in kept:
            if line:
                begin = clean.find(line, at, end)
                spans.append(pad + source[begin:begin + len(line)] + ';')
                at = begin + len(line)
        return spans

    text = three.join(
        [f'while ({condition}) {{', f'{one}if ({_opposite(source[skip[0]:skip[1]])}) {{']
        + lines(leave.end(), found_end, two) + [one + '}'] + lines(step[0], step[1], one)
        + [indent + '}', indent + source[last.start():last.end()].strip()])
    return guard.start(), last.end(), text


def _edits(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    edits, done = [], span[0]
    for guard in GUARD.finditer(clean, span[0], span[1]):
        if guard.start() < done:
            continue
        edit = _rewrite(source, clean, guard)
        if edit:
            edits.append(edit)
            done = edit[1]
    return edits[:LIMIT]


def _apply(source, edits):
    for start, end, text in reversed(edits):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name):
    edits = _edits(source, name)
    if not edits:
        return []
    out = [(FAMILY, _apply(source, edits))]
    if len(edits) > 1:
        out += [(FAMILY, _apply(source, [edit])) for edit in edits]
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
