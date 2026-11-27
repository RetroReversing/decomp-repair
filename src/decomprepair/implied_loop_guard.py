"""A guard that only repeats a loop's first test, removed so the loop is the one the compiler was given.

m2c writes a loop that starts at a constant with the test the compiler copied in front of it:

    j = 9;                                  for (j = 9; j > i; j--) {
    if (i < 9) {                                ...
        do { ... j--; } while (j > i);      }
    }

(or `if (i < 9) { for (j = 9; j > i; j--) ... }` once a rewrite has made the loop a `for`). Written with both, the
compiler has the test twice over and orders the loop's preheader differently: on a 115-instruction high-score insertion
routine (SN64 GCC 2.8.1, `-G0 -mips3 -O2`, N64) the guarded `for` stood at 60, two instructions swapped before the
loop, and the `for` alone was exact.

`implied_loop_guard`: where an `if` with no `else` holds only a loop, and its condition is the loop's first test with
the counter's starting constant in the counter's place, the `if` is dropped:

    if (G) { for (V = K; T; S) B }                  ->  for (V = K; T; S) B
    V = K; if (G) { do { B V--; } while (T); }      ->  for (V = K; T; V--) { B }
    if (G) { V = K; do { B V--; } while (T); }      ->  the same, when V is not read outside the `if`

The step must be the body's last statement and the body has no `continue`. The judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .pattern_repairs import close

FAMILY = 'implied_loop_guard'
FAMILIES = (FAMILY,)
LIMIT = 4
_IF = re.compile(r'\bif\s*\(')
_CAST = re.compile(r'\(\s*(?:[su](?:8|16|32)|int|unsigned(?:\s+int)?)\s*\)')
_ATOM = rf'(?:{IDENT}|{NUMBER})'
_TEST = re.compile(rf'^(?P<left>{_ATOM})(?P<op><=|>=|!=|<|>)(?P<right>{_ATOM})$')
_MIRROR = {'<': '>', '>': '<', '<=': '>=', '>=': '<=', '!=': '!='}
_FOR = re.compile(rf'for\s*\(\s*(?P<counter>{IDENT})\s*=\s*(?P<start>{NUMBER})\s*;(?P<test>[^;]*);')
_START = rf'(?P<counter>{IDENT})\s*=\s*(?P<start>{NUMBER})\s*;'


def _comparison(text):
    """(left, operator, right) of a plain comparison, casts and parentheses aside, or None."""
    text = re.sub(r'\s+', '', _CAST.sub('', text)).replace('(', '').replace(')', '')
    hit = _TEST.match(text)
    if not hit:
        return None
    def value(atom):
        return str(integer(atom)) if atom[0].isdigit() else atom
    return value(hit['left']), hit['op'], value(hit['right'])


def _implied(guard, test, counter, start):
    guard, test = _comparison(guard), _comparison(test)
    if not guard or not test or counter not in (test[0], test[2]):
        return False
    first = tuple(str(integer(start)) if atom == counter else atom for atom in test)
    return guard in (first, (first[2], _MIRROR[first[1]], first[0]))


def _skip(clean, at, end):
    while at < end and clean[at].isspace():
        at += 1
    return at


def _guards(clean, part):
    """(start of `if`, condition, offset of the block's `{`, offset just past its `}`) for each braced `if` without
    an `else`."""
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        if re.search(r'\belse$', clean[part.opening:hit.start()].rstrip()):
            continue
        stop = close(clean, hit.end() - 1, '(', ')')
        if not stop:
            continue
        opening = _skip(clean, stop, part.end)
        if clean[opening] != '{':
            continue
        after = close(clean, opening, '{', '}')
        if not after or re.match(r'\s*else\b', clean[after:part.end]):
            continue
        yield hit.start(), clean[hit.end():stop - 1], opening, after


def _dedent(text, indent):
    """The loop's text, moved from its first line's indentation to `indent`."""
    first, *rest = text.split('\n')
    if not rest:
        return first
    inner = min((len(line) - len(line.lstrip()) for line in rest if line.strip()), default=0)
    return '\n'.join([first] + [indent + line[inner:] if line.strip() else line for line in rest])


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    found = []
    for start, guard, opening, after in _guards(clean, part):
        inside = _skip(clean, opening + 1, after)
        indent = re.search(r'[ \t]*$', source[:start])[0]
        loop = _FOR.match(clean, inside)
        if loop:
            header = close(clean, clean.index('(', inside), '(', ')')
            body = _skip(clean, header, after)
            stop = close(clean, body, '{', '}') if clean[body] == '{' else clean.find(';', body) + 1
            if (stop and clean[stop:after - 1].strip() == ''
                    and _implied(guard, loop['test'], loop['counter'], loop['start'])):
                found.append((FAMILY, edit(source, [(start, after, _dedent(source[inside:stop], indent))])))
            continue
        child = _do_loop(source, part, start, guard, inside, after, indent)
        if child:
            found.append((FAMILY, child))
        if len(found) >= LIMIT:
            break
    return found[:LIMIT]


def _do_loop(source, part, start, guard, inside, after, indent):
    clean = part.clean
    begin = re.compile(_START).match(clean, inside)
    outside = None
    at = _skip(clean, begin.end(), after) if begin else inside
    if not begin:
        before = clean[:start].rstrip()
        outside = re.search(rf'(?<![\w.>]){_START}$', before)
        if not outside or before[:outside.start()].rstrip()[-1:] not in (';', '{', '}'):
            return None
    counter, value = (begin or outside)['counter'], (begin or outside)['start']
    do = re.compile(r'do\s*\{').match(clean, at)
    if not do:
        return None
    body_end = close(clean, do.end() - 1, '{', '}')
    tail = body_end and re.compile(r'\s*while\s*\(').match(clean, body_end)
    if not tail:
        return None
    test_end = close(clean, tail.end() - 1, '(', ')')
    if not test_end or not re.match(r'\s*;\s*\}$', clean[test_end:after]):
        return None
    test = clean[tail.end():test_end - 1]
    body = clean[do.end():body_end - 1]
    step = re.search(rf'(?<![\w.>])(?P<step>{counter}\s*(?:\+\+|--|[+-]=\s*{NUMBER})|(?:\+\+|--)\s*{counter})\s*;\s*$',
                     body)
    if (not step or body[:step.start()].rstrip()[-1:] not in ('', ';', '{', '}') or re.search(r'\bcontinue\b', body)
            or not _implied(guard, test, counter, value)):
        return None
    if begin:
        # the original leaves the counter alone when the guard is false, the `for` does not: nothing else may read it
        rest = clean[part.opening:start] + ' ' + clean[after:part.end]
        rest = re.sub(rf'\b(?:u8|s8|u16|s16|u32|s32|int|short|char)\s+{counter}\s*;', '', rest)
        rest = re.sub(rf'(?<![\w.>]){counter}\s*=(?!=)\s*{NUMBER}\s*;', '', rest)
        if re.search(rf'(?<![\w.>]){counter}\b', rest):
            return None
    kept = source[do.end():do.end() + step.start()].rstrip()
    if kept.startswith('\n'):
        kept = kept[1:].split('\n')
        width = min(len(line) - len(line.lstrip()) for line in kept if line.strip()) if any(map(str.strip, kept)) else 0
        inner = '\n'.join(['{'] + [indent + '    ' + line[width:] if line.strip() else line for line in kept]) + f'\n{indent}}}'
    else:
        inner = '{' + kept + ' }'
    loop = f'for ({counter} = {value}; {source[tail.end():test_end - 1].strip()}; {step["step"].strip()}) {inner}'
    edits = [(start, after, loop)]
    if outside:
        line = source.rfind('\n', 0, outside.start()) + 1
        if not source[line:outside.start()].strip() and source[outside.end():outside.end() + 1] == '\n':
            edits.append((line, outside.end() + 1, ''))
        else:
            edits.append((outside.start(), outside.end(), ''))
    return edit(source, edits)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 80}
