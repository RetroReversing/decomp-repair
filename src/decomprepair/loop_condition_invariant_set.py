"""A loop-invariant value set just before a `do`/`while` loop and read only in its test, assigned inside the test.

GCC 2.x's loop.c hoists a loop's invariant computations to just before the loop (`move_movables` emits them before
the loop's start note), in the order they appear in the loop. An invariant set by a statement before the loop stays
where the source puts it, before everything loop.c hoists; the same assignment written in the loop's test is hoisted
after the invariants of the loop body that come before the test. That changes no instruction, only where the values'
lives start, and so their allocation priorities (`floor_log2(refs) * refs / live length`, global.c).

A 681-instruction N64 bit-stream decoder (KMC GCC 2.7.2 `-O2`): its last table pass sets a subtable's shift amount
`a = (ent >> 4) & 7;` before the fill loop `do { ...; y += step; } while ((y >> a) == 0);`. The fill loop's loop-made
copy of a symbol-table pointer (set where loop.c hoisted it) outranked the pointers the target gives the first
registers; written `while ((y >> (a = (ent >> 4) & 7)) == 0)`, the shift amount's two instructions are hoisted after
that copy, its life grew from 15 to 18 instructions, its priority fell from 2.20 to 1.83, and five register rows
went: 85 -> 70.

Child, for `V = E;` (a plain assignment statement, `E` without a call, assignment, `++` or `--`) followed, after
statements that neither name `V` nor assign any name `E` reads, by `do { BODY } while (COND);` whose BODY names
neither `V` nor assigns a name `E` reads, and whose COND names `V`: the statement removed and the first `V` of COND
written `(V = E)`. The test runs at least once, after the body, so `V` holds `E` wherever it is read, after the loop
too. The candidate is never a verdict: the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'loop_condition_invariant_set'
FAMILIES = (FAMILY,)
LIMIT = 6
_SET = re.compile(rf'(?<![\w.>])(?P<v>{IDENT})\s*=(?!=)\s*(?P<e>[^;{{}}]+);')
_DO = re.compile(r'\bdo\b\s*{')
_ASSIGN = re.compile(rf'(?P<n>{IDENT})\s*(?:\[[^\]]*\]\s*)*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*(?P<p>{IDENT})|'
                     rf'(?P<q>{IDENT})\s*(?:\+\+|--)')
_KEYWORDS = {'sizeof', 'if', 'while', 'for', 'switch', 'return'}


def _assigned(text):
    """The names a stretch of C assigns, increments or decrements (an indexed store counts for the array)."""
    return {hit['n'] or hit['p'] or hit['q'] for hit in _ASSIGN.finditer(text)}


def _pure(expr):
    if _assigned(expr) or re.search(r'[?;{}]', expr) or len(expr) > 80:
        return False
    return not [n for n in re.findall(rf'({IDENT})\s*\(', expr) if n not in _KEYWORDS]


def _names(text):
    return set(re.findall(IDENT, text))


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for loop in _DO.finditer(clean, part.opening + 1, part.end):
        body_open = loop.end() - 1
        body_end = close(clean, body_open, '{', '}')
        if not body_end:
            continue
        tail = re.match(r'\s*while\s*\(', clean[body_end:])
        if not tail:
            continue
        cond_open = body_end + tail.end() - 1
        cond_end = close(clean, cond_open)
        if not cond_end or not re.match(r'\s*;', clean[cond_end:]):
            continue
        body, cond = clean[body_open:body_end], clean[cond_open + 1:cond_end - 1]
        changed = _assigned(body) | _assigned(cond)
        # the statements straight before the loop, nearest first, within the same block
        before = clean[part.opening + 1:loop.start()]
        stop = max(before.rfind('{'), before.rfind('}'))
        between_start = part.opening + 1 + stop + 1
        statements = list(_SET.finditer(clean, between_start, loop.start()))
        for hit in reversed(statements):
            var, expr = hit['v'], hit['e'].strip()
            prefix = clean[between_start:hit.start()].rstrip()
            if prefix and prefix[-1] not in ';{}':
                continue  # part of a declaration or a longer expression
            if not _pure(expr) or var in _names(expr):
                continue
            reads = _names(expr) - _KEYWORDS
            between = clean[hit.end():loop.start()]
            if re.search(rf'\b{re.escape(var)}\b', body) or reads & (changed | _assigned(between)):
                continue
            if re.search(rf'\b{re.escape(var)}\b', between) or var in changed:
                continue
            use = re.search(rf'(?<![\w.>]){re.escape(var)}\b', cond)
            if not use:
                continue
            at = cond_open + 1 + use.start()
            removal_end = hit.end()
            line_start = source.rfind('\n', 0, hit.start()) + 1
            if not source[line_start:hit.start()].strip() and source[removal_end:removal_end + 1] == '\n':
                start, removal_end = line_start, removal_end + 1
            else:
                start = hit.start()
            text = edit(source, [(start, removal_end, ''), (at, at + len(var), f'({var} = {source[hit.start("e"):hit.end("e")].strip()})')])
            out.append((FAMILY, text))
            break
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
