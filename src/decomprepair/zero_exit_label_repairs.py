"""One labelled zero return that the function's other zero exits jump to.

m2c writes every "no result" path of a bounding-box or intersection test as its own `return 0;`, a returned
variable that only ever holds 0, or a guard `if (c) { return 0; } goto next;`. gcc 2.7.2 cross-jumps those exits
(hypothesis from the dumps, not confirmed in the compiler source): the second jump pass merges identical
`$v0 = 0; goto end` tails into the first copy, and the final `if (!x) goto L; return 0; L:` is then turned into one
inverted branch (`bnel`) where the game keeps the branch over its own `j; move $v0,$zero`. Written once with a label
at that final return, and with every later zero exit and every guard-then-return jumping to it, the tails are no
longer separate copies and the game's layout comes back.

An N64 line-segment test (KMC GCC 2.7.2, 205 instructions, score 20 -> 0 in the isolated judge, no permuter run)
needed three edits at once, none of which moved the score alone (each pair stayed at 520): the final return as the
labelled zero, the trailing `return <zero variable>;` exits as `goto` to it, and both `if (c) { return 0; } goto
next;` guards as `if (!(c)) goto next; goto label;`.

The final return counts as zero only when it is `return 0;`, or a variable that an earlier guard `if ((.. | v) != 0)
{ return 0; }` already forced to 0 through a copy `v = variable;`. Variants offered, each keeping the label:
the label alone, with the trailing exits, with the guards, and with both.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'zero_exit_label'
FAMILIES = (FAMILY,)
LABEL = '__zero_exit'

_IF = re.compile(r'\bif\s*\(')
_ANCHOR = re.compile(r'\s*goto\s+(?P<skip>\w+)\s*;\s*(?P<ret>return\s+(?P<value>[^;]+?)\s*;)\s*(?P=skip)\s*:')
_GUARD = re.compile(
    r'\s*(?:\{\s*(?:if\s*\(\s*1\s*\)\s*\{\s*\}\s*)?return\s+0\s*;\s*\}|return\s+0\s*;)\s*goto\s+(?P<next>\w+)\s*;')
_RETURN = re.compile(r'\breturn\s+(\w+)\s*;')
_ASSIGNED = re.compile(r'(?<![=!<>+\-*/%&|^])\b(\w+)\s*=(?!=)\s*([^;]+?)\s*;')


def _body(source, name):
    span = find(source, name)
    if not span:
        return None, None, None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    return (clean, opening, end) if end else (None, None, None)


def _zero_only(clean, opening, end):
    """Names whose every assignment in the body is the literal 0, and whose address is never taken."""
    seen = {}
    for m in _ASSIGNED.finditer(clean, opening, end):
        seen.setdefault(m[1], []).append(m[2].strip())
    return {key for key, values in seen.items()
            if all(value == '0' for value in values) and not re.search(rf'&\s*{key}\b', clean[opening:end])}


def _forced_zero(clean, opening, anchor, value):
    """`value` is 0 where the final return is reached: a guard on a copy of it already returned 0."""
    for copy in re.finditer(rf'\b(\w+)\s*=\s*{re.escape(value)}\s*;', clean[opening:anchor]):
        held = copy[1]
        for guard in _IF.finditer(clean, opening + copy.end(), anchor):
            stop = close(clean, guard.end() - 1)
            if not stop or not re.match(r'\s*\{?\s*return\s+0\s*;', clean[stop:stop + 40]):
                continue
            condition = clean[guard.end():stop - 1]
            parts = re.fullmatch(r'\s*\(?(.*?)\)?\s*!=\s*0\s*', condition)
            if parts and held in [part.strip(' ()') for part in parts[1].split('|')]:
                return True
    return False


def _anchors(clean, opening, end):
    """The `if (c) goto L; return v; L:` exits whose `v` is 0: (if start, return start, return end)."""
    found = []
    for match in _IF.finditer(clean, opening, end):
        stop = close(clean, match.end() - 1)
        tail = _ANCHOR.match(clean, stop) if stop else None
        if not tail:
            continue
        value = tail['value'].strip()
        if value == '0' or (re.fullmatch(r'\w+', value) and _forced_zero(clean, opening, match.start(), value)):
            found.append((match.start(), *tail.span('ret')))
    return found


def variants(source, name):
    clean, opening, end = _body(source, name)
    if clean is None or LABEL in clean:
        return []
    zero_names = _zero_only(clean, opening, end)
    result = []
    for guard_start, ret_start, ret_end in _anchors(clean, opening, end):
        label = (ret_start, ret_end, f'{LABEL}:\n    return 0;')
        later = [(m.start(), m.end(), f'goto {LABEL};') for m in _RETURN.finditer(clean, ret_end, end)
                 if m[1] == '0' or m[1] in zero_names]
        guards = []
        for m in _IF.finditer(clean, opening, guard_start):
            stop = close(clean, m.end() - 1)
            rest = _GUARD.match(clean, stop) if stop else None
            if rest and rest.end() <= guard_start:
                guards.append((m.start(), rest.end(),
                               f'if (!{source[m.end() - 1:stop]}) goto {rest["next"]};\n    goto {LABEL};'))
        chosen = [[label]]
        if later:
            chosen.append([label] + later)
        if guards:
            chosen.append([label] + guards)
        if later and guards:
            chosen.append([label] + later + guards)
        for edits in chosen:
            text = source
            for start, stop, replacement in sorted(edits, reverse=True):
                text = text[:start] + replacement + text[stop:]
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result
