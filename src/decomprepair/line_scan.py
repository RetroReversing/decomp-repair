"""A line scan of one function body in m2c's layout: one statement per line, each brace on a line of its own.

The families that move a whole statement (a default into an `else`, a pointer increment to the head of its loop, a
temporary into the `if` that uses it) need the statement lines and where each block opens and closes, not a C
parser. A line here is a span of the source with its blanked text (comments and strings spaces, so a brace inside
one doesn't count), its indentation and its offsets. Anything that is not in that layout is left alone by the
callers: they only match lines of the exact shapes they name.
"""
import re
from dataclasses import dataclass

from .integer_repair_support import edit

KEYWORDS = frozenset('''auto break case char const continue default do double else enum extern float for goto if int
long register return short signed sizeof static struct switch typedef union unsigned void volatile while'''.split())
_WORD = re.compile(r'[A-Za-z_]\w*')


@dataclass(frozen=True)
class Line:
    start: int   # offset of the first character of the line
    end: int     # offset just past its newline (or the end of the body)
    text: str    # the blanked text without the newline
    source: str  # the original text without the newline

    @property
    def indent(self):
        return re.match(r'[ \t]*', self.text)[0]

    @property
    def stripped(self):
        return self.text.strip()


def lines(part, source):
    """The body's lines, from the line after `{` to the line before the closing `}`."""
    result = []
    pos = source.find('\n', part.opening) + 1
    stop = part.end - 1
    while 0 < pos < stop:
        nxt = source.find('\n', pos)
        end = stop if nxt < 0 or nxt >= stop else nxt + 1
        result.append(Line(pos, end, part.clean[pos:end].rstrip('\n'), source[pos:end].rstrip('\n')))
        pos = end
    return result


def block_end(body, index):
    """Index of the line holding the `}` that closes the `{` line at `index`, or None."""
    depth = 0
    for i in range(index, len(body)):
        depth += body[i].text.count('{') - body[i].text.count('}')
        if depth == 0:
            return i
    return None


def block_start(body, index):
    """Index of the `{` line that the `}` line at `index` closes, or None."""
    depth = 0
    for i in range(index, -1, -1):
        depth += body[i].text.count('}') - body[i].text.count('{')
        if depth == 0:
            return i
    return None


def block_open(body, index):
    """Index of the `{` line that opens the statement at `index` (`if (...)`, `do`, `else`), or None."""
    nxt = index + 1
    return nxt if nxt < len(body) and body[nxt].stripped == '{' else None


def loops(body):
    """`do { } while (...)` loops as (do line, open line, close line, while line) indexes."""
    found = []
    for i, line in enumerate(body):
        if line.stripped != 'do':
            continue
        opening = block_open(body, i)
        if opening is None:
            continue
        closing = block_end(body, opening)
        if closing is not None and closing + 1 < len(body) and re.match(r'while\s*\(', body[closing + 1].stripped):
            found.append((i, opening, closing, closing + 1))
    return found


def words(text):
    return [w for w in _WORD.findall(text) if w not in KEYWORDS]


def mentions(text, name):
    return re.search(rf'(?<![\w.>]){re.escape(name)}\b', text) is not None


def reads_first(text, name):
    """True when the first mention of `name` in `text` reads it (`x = f(x)`, `g(x)`) rather than only assigns it."""
    first = re.search(rf'(?<![\w.>]){re.escape(name)}\b', text)
    if not first:
        return False
    rest = text[first.end():]
    plain = re.match(r'\s*=(?!=)', rest)
    if not plain:
        return True
    statement = rest[plain.end():rest.find(';') if ';' in rest else len(rest)]
    return mentions(statement, name)


def declaration_end(part):
    """The offset just past the function's leading declarations (where a new local goes), or None."""
    from .frame_padding_repairs import declaration_ends
    ends = declaration_ends(part)
    return ends[-1] if ends else None


def with_local(source, part, declaration):
    """An edit that adds `declaration` after the leading declarations, or None when there are none."""
    end = declaration_end(part)
    if end is None:
        return None
    indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, end) + 1:])[0] or '  '
    return (end, end, '\n' + indent + declaration)


def apply(source, edits):
    return edit(source, edits)
