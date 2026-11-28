"""Case labels m2c left inside an arm's `else`, lifted out as arms of their own.

    case 4: case 8:                          case 4: case 8:
        if (mode == 5) {                         if (mode == 5) {
            p->type = 0x138;                         p->type = 0x138;
        } else {                                 } else {
    case 1: case 6: case 7:          ->              count++;
            count++;                             }
        }                                        break;
        break;                               case 1:
                                                 count++;
                                                 break;
                                             case 6:
                                             ...

m2c finds one block reached both by an arm's `else` and by other cases, and opens those cases inside the `else`.
The game wrote the statements in each place; cross-jumping merges them into the one block. That is not the same
code for GCC 2.x even though it jumps to the same place: every copy is still there when loop.c counts the loop's
instructions, and a larger loop keeps it from moving a constant out (the move must pay for the register it takes:
`threshold * savings * lifetime >= insn_count`). A 193-instruction N64 spawner (SN GCC 2.8.1 `-G0 -mips3 -O2`)
compared one mode word with the same constant twice; the constant was hoisted and spilled until the switch in its
loop had one copy of the increment per case (1655 with the arms shared, 685 with the lifted arms copied, 0 with the
other stacked run of the switch copied too).

Where the copies stand matters too (cross-jumping keeps one of them, and the block lands where it stood): on that
function only the switch's last arms matched (right after the `if`'s arm: 680).

Offered children, the whole combination first: every label of the lifted run as the switch's last arms and every
other stacked run with a plain body copied per label (0 there); the same with the copies right after their old arm;
only the lifted run copied, at the end; the run lifted with its labels still sharing one copy.

Meaning is kept: the `else` must be the last thing in its arm (`} break;`), its statements hold no label, `case` or
declaration, and the `if` sits directly in the switch's block.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'else_case_arm_lift'
FAMILIES = (FAMILY,)
LIMIT = 6
MAX_LABELS = 24

_LABEL = r'case\s+[^:;{}?]+:'
_NESTED = re.compile(rf'\belse\s*\{{\s*(?=case\b)((?:{_LABEL}\s*)+)')
_RUN = re.compile(rf'(?<![\w])(?:{_LABEL}\s*){{2,}}')
_ONE = re.compile(_LABEL)
_AFTER = re.compile(r'\s*break\s*;')
_BARRED = re.compile(r'\bcase\b|\bdefault\b|\bstatic\b|^\s*[A-Za-z_]\w*\s*:(?!:)'
                     r'|(?:^|[;{}])\s*(?!return\b|goto\b|else\b)[A-Za-z_]\w*\s+\**\s*[A-Za-z_]\w*\s*[=;\[]', re.M)
_PLAIN_END = re.compile(r'(?:break|continue|return\b[^;{}]*)\s*;')


def _switch_block(clean, opening, end, at):
    """The braces of the switch whose block holds `at` directly (no other block between), or None."""
    for match in re.finditer(r'\bswitch\s*\(', clean[opening:end]):
        paren = opening + match.end() - 1
        past = close(clean, paren, '(', ')')
        if past is None:
            continue
        brace = clean.find('{', past)
        stop = close(clean, brace, '{', '}') if brace >= 0 else None
        if stop is None or not brace < at < stop:
            continue
        before = clean[brace + 1:at]
        if before.count('{') == before.count('}'):
            return brace, stop
    return None


def _indent(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:])[0]


def _lines(body, indent):
    rows = [row.strip() for row in body.split('\n') if row.strip()]
    return ''.join(f'{indent}    {row}\n' for row in rows)


def _copies(labels, body, indent):
    """Each label with its own copy of `body` (which ends in its own jump)."""
    return ''.join(f'{indent}{label}\n{_lines(body, indent)}' for label in labels)


def _end_of_switch(source, clean, stop, indent, labels, jump):
    """The copies as the switch's last arms, after a `break;` of their own when the arm before them runs off."""
    close_brace = stop - 1
    at = len(source[:close_brace].rstrip())
    ends = re.search(r'\b(?:break|continue|return\b[^;{}]*|goto\s+\w+)\s*;\s*$', clean[:close_brace])
    fence = '' if ends else f'\n{indent}    break;'
    return at, at, fence + '\n' + _copies(labels, jump, indent).rstrip('\n')


def _plain_runs(source, clean, brace, stop):
    """(start, end, labels, body) for each stacked run in the switch whose body is plain statements."""
    for run in _RUN.finditer(clean, brace + 1, stop):
        leave = _PLAIN_END.search(clean, run.end(), stop)
        if not leave:
            continue
        between = clean[run.end():leave.end()]
        if '{' in between or '}' in between or _BARRED.search(between):
            continue
        labels = [source[run.start() + m.start():run.start() + m.end()] for m in _ONE.finditer(run[0])]
        if len(labels) <= MAX_LABELS:
            yield run.start(), leave.end(), labels, source[run.end():leave.end()]


def _apply(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    out = []
    for match in _NESTED.finditer(clean, opening, end):
        else_brace = clean.index('{', match.start())
        else_end = close(clean, else_brace, '{', '}')
        if else_end is None:
            continue
        after = _AFTER.match(clean, else_end)
        inside = clean[match.end():else_end - 1]
        if not after or not inside.strip() or _BARRED.search(inside) or re.search(r'\bbreak\b', inside):
            continue
        # the `if` this `else` ends: the nearest one whose then-block closes right before it
        owner = None
        for test in re.finditer(r'\bif\s*\(', clean[opening:match.start()]):
            paren = opening + test.end() - 1
            past = close(clean, paren, '(', ')')
            then = re.compile(r'\s*\{').match(clean, past) if past else None
            then_end = close(clean, then.end() - 1, '{', '}') if then else None
            if then_end is not None and not clean[then_end:match.start()].strip():
                owner = opening + test.start()
        if owner is None or re.search(r'\belse\s*$', clean[:owner]):
            continue
        found = _switch_block(clean, opening, end, owner)
        if not found:
            continue
        brace, stop = found
        labels = [source[match.start(1) + m.start():match.start(1) + m.end()] for m in _ONE.finditer(match[1])]
        if len(labels) > MAX_LABELS:
            continue
        body = source[match.end():else_end - 1].strip()
        first = _ONE.search(clean, brace + 1, owner)
        if not first:
            continue
        indent = _indent(source, first.start())
        inner = indent + '    '
        head = (else_brace + 1, else_end - 1, f'\n{inner}    {body}\n{inner}')
        tail_at = after.end()
        jump = f'{body}\nbreak;'
        copied = (tail_at, tail_at, '\n' + _copies(labels, jump, indent).rstrip('\n'))
        shared = (tail_at, tail_at, '\n' + ''.join(f'{indent}{label}\n' for label in labels)
                  + _lines(jump, indent).rstrip('\n'))
        others = [(start, stop_at, _copies(run, text, indent).strip())
                  for start, stop_at, run, text in _plain_runs(source, clean, brace, stop)
                  if stop_at <= owner or start >= tail_at]
        last = _end_of_switch(source, clean, stop, indent, labels, jump)
        if others:
            out.append((FAMILY, _apply(source, [head, last, *others])))
            out.append((FAMILY, _apply(source, [head, copied, *others])))
        out.append((FAMILY, _apply(source, [head, last])))
        out.append((FAMILY, _apply(source, [head, shared])))
    seen, kept = {source}, []
    for family, text in out:
        if text not in seen:
            seen.add(text)
            kept.append((family, text))
    return kept[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
