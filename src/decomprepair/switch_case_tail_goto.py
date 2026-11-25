"""A `switch` case whose last statement repeats the whole body of another case, written as a jump to that case.

Several cases of one `switch` often end the same way: `mode = 5; kind = 1; break;`, `flags |= 0x1000; kind = 1;
break;`, and a case group that is nothing but `kind = 1; break;`. GCC 2.7.2's cross-jumping (jump.c, after reload)
merges the identical tails into that last group's code, so most of those cases come out as `...; j L; <delay slot>`
where `L` sets the flag. Whether a case's tail merges depends on the order the first scheduler left it in: in a case
that also updates a word (`lw; ori; sw`), the scheduler put the flag's constant first, and the case's `ori; sw; j` then
matched another case that ends with the same word update instead, so the case jumped into the middle of that one and
set the flag in its delay slot. Written as `flags |= 0x1000; goto L;` with `L:` on the shared group's statement, the
case carries no copy of the flag store and its code is the target's `lw; ori; j L; sw` (an 874-instruction N64 object
spawner, KMC GCC 2.7.2 `-O2`: 465 -> 15; docs/learnings/function/spawner-clean-typed-rewrite.md).

`switch_case_tail_goto` offers, for each case whose last statement before its `break;` equals the whole body of
another case group (`S; break;`), a child with that tail written as `goto L;` and `L:` put on the other group's
statement, and one child with every such case at once. Only a simple statement qualifies (no braces, `goto`,
`return` or label). The judge decides which, if any, the target had.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'switch_case_tail_goto'
FAMILIES = (FAMILY,)
LIMIT = 12
LABEL = re.compile(r'(?:case\b[^:;{}]*|default\s*):')
TAIL = re.compile(r'(?P<statement>[^;{}:]+;)\s*break\s*;(?=\s*$)')
SIMPLE_BAD = re.compile(r'\b(?:goto|return|break|continue|case|default|if|else|for|while|do|switch)\b')
PLAIN_LABEL = re.compile(rf'^\s*(?P<label>{IDENT})\s*:(?!:)\s*')


def _python_match(clean, opening):
    depth = 0
    for index in range(opening, len(clean)):
        if clean[index] == '{':
            depth += 1
        elif clean[index] == '}':
            depth -= 1
            if depth == 0:
                return index
    return None


_match = _python_match
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _match(clean, opening):
        found = _scan.close_if(clean, opening, '{', '}', None)
        return _python_match(clean, opening) if found is NotImplemented else found


def _labels(clean, start, end):
    """The case/default labels at the switch body's own level, as (start, end) spans."""
    found, depth, index = [], 0, start
    while index < end:
        char = clean[index]
        if char in '({[':
            depth += 1
        elif char in ')}]':
            depth -= 1
        elif depth == 0 and re.match(r'\b(?:case|default)\b', clean[index:index + 8]) and (index == 0 or not (clean[index - 1].isalnum() or clean[index - 1] == '_')):
            found_label = LABEL.match(clean, index)
            if found_label:
                found.append((index, found_label.end()))
                index = found_label.end()
                continue
        index += 1
    return found


def _segments(clean, start, end):
    """Each case group's body (between its last label and the next label or the switch's closing brace)."""
    labels = _labels(clean, start, end)
    segments = []
    for number, (_, label_end) in enumerate(labels):
        stop = labels[number + 1][0] if number + 1 < len(labels) else end
        if clean[label_end:stop].strip():
            segments.append((label_end, stop))
    return segments


def _norm(text):
    return ' '.join(text.split())


def _simple(statement):
    return not SIMPLE_BAD.search(statement) and '{' not in statement and '}' not in statement


def _fresh_label(source):
    name, number = 'shared_tail', 1
    while re.search(rf'\b{name}\b', source):
        number += 1
        name = f'shared_tail_{number}'
    return name


def variants(source, name, header=''):
    part = view(source, name)
    if not part or part.opening < 0:
        return []
    clean = part.clean
    children = []
    for found in re.finditer(r'\bswitch\s*\(', clean[part.opening:part.end]):
        head = part.opening + found.start()
        opening = clean.find('{', head)
        closing = _match(clean, opening) if opening >= 0 else None
        if closing is None or closing > part.end:
            continue
        segments = _segments(clean, opening + 1, closing)
        tails = []
        for seg_start, seg_end in segments:
            text = clean[seg_start:seg_end]
            tail = TAIL.search(text)
            if not tail or not _simple(tail['statement']):
                continue
            lead = len(tail['statement']) - len(tail['statement'].lstrip())
            tails.append((seg_start, seg_end, seg_start + tail.start('statement') + lead, seg_start + tail.end(),
                          tail['statement'].strip()))
        for target in tails:
            t_start, t_end, s_start, s_end, statement = target
            body = clean[t_start:s_start]
            label = None
            if body.strip():
                existing = PLAIN_LABEL.match(body)
                if not existing or body[existing.end():].strip():
                    continue        # the target group must be nothing but `[L:] S; break;`
                label = existing['label']
            jumpers = [other for other in tails if other is not target and _norm(other[4]) == _norm(statement)
                       and clean[other[0]:other[2]].strip()]
            if not jumpers:
                continue
            fresh = label or _fresh_label(source)
            indent = clean[clean.rfind('\n', 0, s_start) + 1:s_start]
            insert = [] if label else [(s_start, s_start, f'{fresh}:\n' + (indent if not indent.strip() else ' '))]
            def child(chosen, insert=insert, fresh=fresh):
                edits = list(insert)
                for other in chosen:
                    edits.append((other[2], other[3], f'goto {fresh};'))
                return edit(source, edits)
            for other in jumpers:
                children.append(child([other]))
            if len(jumpers) > 1:
                children.append(child(jumpers))
    result = []
    for text in children:
        if text != source and text not in result:
            result.append(text)
        if len(result) >= LIMIT:
            break
    return [(FAMILY, text) for text in result]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
