"""Two edits to a call's argument that no other family writes.

call_argument_inplace_update
    A local passed through arithmetic to the last call that reads it, updated in place on the line before:

        func(head, ALIGN16(limit));      ->      limit = ALIGN16(limit);
                                                 func(head, limit);

    The value then lives in the local's own pseudo, whose reference count rises. In a 155-instruction SN GCC (2.7.2
    based) N64 asset loader that count decided which of three saved registers the local took (70 -> 0; the register
    explanation is a hypothesis from the two compiles). Offered when the argument reads one local once, calls nothing
    but all-capitals macros, nothing mentions the local after the call and the call is in no loop.

known_zero_argument_drop
    m2c passes a variable a variadic call still had in an argument register inside the arm where it is known to be zero:

        if (rank != 0) {
            sprintf(out, fmtRank, rank);
        } else {
            sprintf(out, fmtNone, rank);     ->      sprintf(out, fmtNone);
        }

    The compiler writes `move $a2,$zero` for it, which the target did not have (160 -> 0 on a 174-instruction SN GCC
    N64 results screen, with its compare operands already in order). The last argument only, and only when nothing in
    the arm assigns the variable first.

Both change only what the caller passes or where it computes it; the judge decides."""
import re

from .csource import _blank, find
from .pattern_repairs import close

UPDATE = 'call_argument_inplace_update'
DROP = 'known_zero_argument_drop'
FAMILIES = (UPDATE, DROP)
LIMIT = 6
IDENT = r'[A-Za-z_]\w*'
TYPE = r'(?:(?:unsigned|signed)\s+)?(?:char|short|int|long|[su](?:8|16|32|64))'
_CALL = re.compile(r'(?m)^([ \t]*)(' + IDENT + r')[ \t]*\(')
_KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'sizeof'}


def _arguments(text):
    """(start, end) of each top-level argument of a call's parentheses `text` (without them)."""
    out, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif char == ',' and not depth:
            out.append((start, index))
            start = index + 1
    if text.strip():
        out.append((start, len(text)))
    return out


def _calls(body):
    """(statement start, indent, [(argument start, end)], end of the call) of each call that starts a line."""
    for m in _CALL.finditer(body):
        if m[2] in _KEYWORDS:
            continue
        stop = close(body, m.end() - 1, '(', ')')
        if not stop or not body[stop:].lstrip().startswith(';'):
            continue
        spans = [(m.end() + a, m.end() + b) for a, b in _arguments(body[m.end():stop - 1])]
        yield m.start(), m[1], spans, stop


def _loops(body):
    """(start, end) of every loop in `body`."""
    spans = []
    for m in re.finditer(r'\b(for|while|do)\b', body):
        at = m.end()
        if m[1] != 'do':
            opening = body.find('(', at)
            at = close(body, opening, '(', ')') if opening >= 0 else 0
        if not at:
            continue
        at += len(body[at:]) - len(body[at:].lstrip())
        if body.startswith('{', at):
            spans.append((m.start(), close(body, at, '{', '}') or len(body)))
    return spans


def _updates(body, locals_):
    loops = _loops(body)
    labels = re.search(r'\bgoto\b', body)
    for start, indent, spans, _ in _calls(body):
        if labels or any(a <= start < b for a, b in loops):
            continue
        for a, b in spans:
            argument = body[a:b].strip()
            if re.fullmatch(IDENT, argument) or '++' in argument or '--' in argument or '=' in argument:
                continue
            # only casts and all-capitals macros may be followed by a bracket
            called = re.findall(r'\b(' + IDENT + r')\s*\(', argument)
            if any(not re.fullmatch(r'[A-Z][A-Z0-9_]*', word) for word in called):
                continue
            read = [word for word in re.findall(r'\b' + IDENT + r'\b', argument) if word in locals_]
            if len(read) != 1:
                continue
            local = read[0]
            if re.search(r'&\s*' + local + r'\b', body):
                continue
            word = re.compile(r'\b' + local + r'\b')
            rest = [body[x:y] for x, y in spans if (x, y) != (a, b)]
            if any(word.search(text) for text in rest) or word.search(body, spans[-1][1]):
                continue
            lead = len(body[a:b]) - len(body[a:b].lstrip())
            yield start, indent, a + lead, a + lead + len(argument), local


def _zero_arms(body):
    """(start, end, variable) of every arm in which a tested variable is zero."""
    for m in re.finditer(r'\bif\s*\(\s*(' + IDENT + r')\s*(!=\s*0|==\s*0)?\s*\)\s*\{', body):
        stop = close(body, m.end() - 1, '{', '}')
        if not stop:
            continue
        if m[2] and m[2].startswith('=='):
            yield m.end() - 1, stop, m[1]
            continue
        other = re.match(r'\s*else\s*\{', body[stop:])
        if other:
            opening = stop + other.end() - 1
            end = close(body, opening, '{', '}')
            if end:
                yield opening, end, m[1]


def _drops(body):
    calls = list(_calls(body))
    for first, end, variable in _zero_arms(body):
        for start, _, spans, _ in calls:
            if not first < start < end or len(spans) < 2:
                continue
            a, b = spans[-1]
            if body[a:b].strip() != variable:
                continue
            if re.search(r'\b' + variable + r'\b\s*(?:[-+*/|&^]?=(?!=)|\+\+|--)', body[first:start]):
                continue
            yield spans[-2][1], b


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    head, text, tail = source[:span[0]], source[span[0]:span[1]], source[span[1]:]
    body = _blank(text)
    opening = body.find('{')
    if opening < 0:
        return []
    locals_ = {m[1] for m in re.finditer(r'(?m)^[ \t]+' + TYPE + r'[ \t]+(' + IDENT + r')[ \t]*(?=[;=])', body)}
    out = []
    for start, indent, a, b, local in list(_updates(body, locals_))[:LIMIT]:
        changed = (text[:start] + f'{indent}{local} = {text[a:b]};\n' + text[start:a] + local + text[b:])
        out.append((UPDATE, head + changed + tail))
    drops = list(_drops(body))[:LIMIT]
    for a, b in drops:
        out.append((DROP, head + text[:a] + text[b:] + tail))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
