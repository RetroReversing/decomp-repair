"""A loop's `break` written as the `return` that follows the loop, and the other way round.

    for (i = 0; i < 4; i++) {               for (i = 0; i < 4; i++) {
        ...                                     ...
        if (count == max) { break; }    <->     if (count == max) { return count; }
    }                                       }
    return count;                           return count;

Both do the same thing, and GCC lays them out differently: with the `return` at the exit, the jump goes past the
closing path's reload of a returned global (the value is already in `$v0`), so the exit branch's delay slot has no
`lui` of that address to take and the closing load stays on the loop's fall-through only (read from the two
compiled listings, not the compiler's source). On an N64 controller setup
function (SN GCC 2.8.1 `-G0 -mips3 -O2`, 118 instructions, plain C) the `break` scored 210 and the `return` was exact.

`break_as_return`: each loop followed at once by `return E;` (E a name, a number, a member chain or a cast of one), or
a loop that ends a `void` function, has its own `break`s (not those of an inner loop or `switch`) written as that
return. `return_as_break`: the same loops' own `return E;` written as `break;`. Each direction offers all of a loop's
sites together, then each site alone when there are several.

A loop is left alone when it declares a name `E` reads, or holds a loop or `switch` without braces. Candidate
rewrites; the exact judge decides each.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

BREAK = 'break_as_return'
RETURN = 'return_as_break'
FAMILIES = (BREAK, RETURN)
LIMIT = 12

_KEYWORD = re.compile(r'\b(for|while|do|switch)\b')
_VALUE = (rf'(?:\(\s*(?:(?:unsigned|signed|struct)\s+)*{IDENT}\s*\**\s*\)\s*)?'
          rf'&?\s*(?:{IDENT}(?:\s*(?:\.|->)\s*{IDENT}|\s*\[\s*(?:{NUMBER})\s*\])*|-?\s*(?:{NUMBER}))')
_AFTER = re.compile(rf'\s*return\b\s*(?P<e>{_VALUE})?\s*;')
_TAIL = re.compile(r'\s*while\s*\(')
_SPACE = re.compile(r'\s*')


def _statements(clean, opening, end):
    """The braced loops and switches of the body as (keyword, brace, past the body, past the statement), and the
    positions of the ones written without braces. A `do`'s closing `while` is not a loop of its own."""
    braced, bare, tails = [], [], set()
    for hit in _KEYWORD.finditer(clean, opening, end):
        if hit.start() in tails:
            continue
        at = _SPACE.match(clean, hit.end()).end()
        if hit[1] != 'do':
            if not clean.startswith('(', at):
                bare.append(hit.start())
                continue
            past = close(clean, at)
            if past is None:
                bare.append(hit.start())
                continue
            at = _SPACE.match(clean, past).end()
        if not clean.startswith('{', at):
            bare.append(hit.start())
            continue
        past = close(clean, at, '{', '}')
        if past is None:
            bare.append(hit.start())
            continue
        statement = past
        if hit[1] == 'do':
            tail = _TAIL.match(clean, past)
            test = close(clean, tail.end() - 1) if tail else None
            semicolon = re.compile(r'\s*;').match(clean, test) if test is not None else None
            if not semicolon:
                bare.append(hit.start())
                continue
            tails.add(past + tail[0].index('while'))
            statement = semicolon.end()
        braced.append((hit[1], at, past, statement))
    return braced, bare


def _returned(source, part, name, statement):
    """The value the code after the loop returns: its text, '' for a bare return or a void function's end, or None."""
    clean = part.clean
    after = _AFTER.match(clean, statement)
    if after:
        return source[after.start('e'):after.end('e')] if after['e'] else ''
    rest = clean[statement:part.end].strip()
    if rest in ('', '}') and clean[:part.end].rstrip().endswith('}'):
        closes_function = close(clean, part.opening, '{', '}')
        if closes_function is not None and not clean[statement:closes_function - 1].strip():
            if re.search(rf'\bvoid\s+{re.escape(name)}\s*\(', clean):
                return ''
    return None


def _declares(body, value):
    """Whether the loop's body declares a name the returned value reads (the two returns would then differ)."""
    for word in re.findall(rf'(?<![\w.>])\b({IDENT})\b', value):
        if re.search(rf'(?:^|[{{}};])\s*(?!return\b|goto\b|case\b)[A-Za-z_]\w*(?:\s+|\s*\*+\s*)(?:[A-Za-z_]\w*[\s*]+)*'
                     rf'{word}\s*(?:\[|;|=(?!=)|,)', body):
            return True
    return False


def _squeeze(text):
    return re.sub(r'\s+', '', text)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    braced, bare = _statements(clean, part.opening, part.end)
    out, seen = [], set()

    def offer(family, edits):
        child = edit(source, edits)
        if child != source and child not in seen and len(out) < LIMIT:
            seen.add(child)
            out.append((family, child))

    for keyword, opening, past, statement in braced:
        if keyword == 'switch' or any(opening < position < past for position in bare):
            continue
        value = _returned(source, part, name, statement)
        if value is None or _declares(clean[opening:past], value):
            continue
        inner = [(kind, start, stop) for kind, start, stop, _ in braced if opening < start < past]
        loops = [(start, stop) for kind, start, stop in inner if kind != 'switch']
        # a `break` belongs to the innermost loop or switch; a `return` leaves from any of them
        breakable = [(start, stop) for _, start, stop in inner]
        exit_text = f'return {value};' if value else 'return;'
        breaks = [(hit.start(), hit.end(), exit_text)
                  for hit in re.compile(r'\bbreak\s*;').finditer(clean, opening, past)
                  if not any(start < hit.start() < stop for start, stop in breakable)]
        returns = [(hit.start(), hit.end(), 'break;')
                   for hit in re.compile(r'\breturn\b(?P<e>[^;{}]*);').finditer(clean, opening, past)
                   if _squeeze(source[hit.start('e'):hit.end('e')]) == _squeeze(value)
                   and not any(start < hit.start() < stop for start, stop in breakable)
                   and not any(start < hit.start() < stop for start, stop in loops)]
        for family, sites in ((BREAK, breaks), (RETURN, returns)):
            if not sites:
                continue
            offer(family, sites)
            if len(sites) > 1:
                for site in sites:
                    offer(family, [site])
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry (registry.py)
