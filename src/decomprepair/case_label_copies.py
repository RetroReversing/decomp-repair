"""Case labels that share one body, written as a copy of the body each.

`case 1: case 2: case 3: if (x) { p->state = y; } break;` and three arms with that same body compile to one block:
cross-jumping merges the tails. It does so after register allocation, so each copy still counts: the references it
makes raise a variable's allocation priority over a pseudo it lost to by a fraction. In a 1177-instruction state
machine (KMC GCC 2.7.2, -O1) the object pointer had 38 references and one saved register too high a number, with a
held address in the register it should have had (270: every difference that swap). Three bodies for the three states
that shared one were exact.
"""
import re

from .integer_repair_support import view

FAMILY = 'case_label_copies'
FAMILIES = (FAMILY,)
_LABEL = r'case\s+[^:;{}?]+:'
_RUN = re.compile(rf'(?<![\w])(?:{_LABEL}\s*){{2,}}')
_ONE = re.compile(_LABEL)
_NOT_COPIED = re.compile(r'\bcase\b|\bdefault\b|\bstatic\b|^\s*[A-Za-z_]\w*\s*:(?!:)', re.M)
MAX_LABELS = 6


def _body_end(clean, start):
    """The offset just past the `break;` or `return ...;` that ends the arm starting at `start`, or None."""
    depth = 0
    i = start
    while i < len(clean):
        c = clean[i]
        if c in '{(':
            depth += 1
        elif c in '})':
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and (i == start or not (clean[i - 1].isalnum() or clean[i - 1] == '_')):
            before = clean[start:i].rstrip()
            if (not before or before[-1] in ';{}'):
                if re.match(r'(?:case|default)\b', clean[i:]):
                    return None
                leave = re.match(r'(?:break|return\b[^;{}]*|continue)\s*;', clean[i:])
                if leave:
                    return i + leave.end()
        i += 1
    return None


def _runs(part):
    for run in _RUN.finditer(part.clean, part.opening, part.end):
        labels = [(m.start() + run.start(), m.end() + run.start()) for m in _ONE.finditer(run[0])]
        if len(labels) > MAX_LABELS:
            continue
        end = _body_end(part.clean, run.end())
        if end is None or _NOT_COPIED.search(part.clean[run.end():end]):
            continue
        yield labels, run.end(), end


def _split(source, labels, start, end):
    line = source.rfind('\n', 0, labels[0][0]) + 1
    indent = re.match(r'[ \t]*', source[line:])[0]
    body = source[start:end]
    text = f'\n{indent}'.join(f'{source[a:b]}\n{indent}    {body}' for a, b in labels)
    return labels[0][0], end, text


def _apply(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    edits = [_split(source, *run) for run in _runs(part)]
    out = [(FAMILY, _apply(source, [edit])) for edit in edits]
    if len(edits) > 1:
        out.append((FAMILY, _apply(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
