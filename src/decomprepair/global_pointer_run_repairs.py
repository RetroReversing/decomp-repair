"""A run of statements that re-reads a global pointer, using the local that already holds it.

A function that keeps `n = D_800EDA8C;` for its loop, then writes a block of field stores and updates through
`D_800EDA8C` again, reads the global afresh in the second block: gcc loads it into a temporary there (`$a1`), while
the target keeps working through the loop's register (`$a2`), so everything the block computes is one register off.
Written through the local, the block (and a MIPS function's 535) moved to 480, the register the target uses.

Where a local pointer `X` is assigned from a global `G` somewhere in the function, and a run of consecutive
statements without a call reads `G` at least three times, the run is offered as `X = G;` followed by the run with
`X` for `G`. The meaning changes only if a store in the run can reach `G` itself, which the judge's byte comparison
settles.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'global_pointer_run'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
CALL = re.compile(r'(?<![\w.>])(?!(?:if|while|for|switch|return|sizeof)\b)' + IDENT + r'\s*\(')
KEYWORDS = {'return', 'else', 'goto', 'break', 'continue', 'case', 'default', 'do'}


def _statements(clean, a, b):
    """(start, end) of each top-level statement of the block text between a and b."""
    result, pos = [], a
    while pos < b:
        while pos < b and clean[pos].isspace():
            pos += 1
        if pos >= b:
            break
        start, depth = pos, 0
        while pos < b:
            char = clean[pos]
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
            elif char == ';' and depth == 0:
                pos += 1
                break
            elif char == '{' and depth == 0:
                pos = close(clean, pos, '{', '}') or b
                rest = clean[pos:b]
                if re.match(r'\s*else\b', rest) or (clean[start:start + 2] == 'do' and re.match(r'\s*while\b', rest)):
                    continue
                break
            pos += 1
        result.append((start, pos))
    return result


def _blocks(clean, opening, end):
    yield opening + 1, end - 1
    for brace in re.finditer(r'\{', clean[opening + 1:end - 1]):
        at = opening + 1 + brace.start()
        stop = close(clean, at, '{', '}')
        if stop:
            yield at + 1, stop - 1


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    pairs = []
    for copy in re.finditer(r'(?<![\w.>])(' + IDENT + r')\s*=(?!=)\s*(' + IDENT + r')\s*;', body):
        x, g = copy.groups()
        declared = re.search(r'(?m)^[ \t]*[A-Za-z_][\w ]*\*[ \t]*' + x + r'[ \t]*;', body)
        if (x in KEYWORDS or g in KEYWORDS or not declared or re.search(r'(?m)^[ \t]*[\w ]+[ \t*]' + g + r'[ \t]*;', body)
                or (x, g) in pairs):
            continue
        pairs.append((x, g))
    result = []
    for x, g in pairs:
        word = r'(?<![\w.>])' + g + r'\b'
        copies = re.compile(r'(?<![\w.>])' + x + r'\s*=(?!=)\s*' + g + r'\s*;')
        for a, b in _blocks(clean, opening, end):
            stmts = _statements(clean, a, b)
            index = 0
            while index < len(stmts):
                run = []
                while index < len(stmts):
                    text = clean[stmts[index][0]:stmts[index][1]]
                    if CALL.search(text) or re.search(r'\b(?:return|goto|break|continue)\b', text):
                        break
                    run.append(stmts[index])
                    index += 1
                if not run:
                    index += 1
                    continue
                # the run starts at its first statement that reads G (a copy `X = G;` there is the copy it wants)
                already = False
                while run and (not re.search(word, clean[run[0][0]:run[0][1]])
                               or copies.fullmatch(clean[run[0][0]:run[0][1]].strip())):
                    already = already or bool(copies.fullmatch(clean[run[0][0]:run[0][1]].strip()))
                    run.pop(0)
                reads = sum(len(re.findall(word, clean[s:e])) for s, e in run)
                written = ''.join(clean[s:e] for s, e in run)
                if reads < 3 or re.search(r'(?<![\w.>])(?:' + x + '|' + g + r')\s*(?:[-+*/&|^]|<<|>>)?=(?!=)', written):
                    continue
                first = run[0][0]
                run_text = source[first:run[-1][1]]
                already = already or re.search(r'(?<![\w.>])' + x + r'\s*=(?!=)\s*' + g + r'\s*;\s*$', clean[:first])
                text = source[:first] + ('' if already else f'{x} = {g}; ') + re.sub(word, x, run_text) + source[run[-1][1]:]
                if (FAMILY, text) not in result:
                    result.append((FAMILY, text))
    return result
