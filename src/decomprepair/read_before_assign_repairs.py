"""A local that m2c's draft reads before its first assignment, the assignment moved up to that read.

m2c sometimes places a temporary's assignment after a statement that already uses it (it orders statements by
where their results are stored, and a value kept in a register from an earlier load is "assigned" late). The
compiler then reads an uninitialised variable: the draft is wrong C and can be hundreds of points off. An N64
function was 235 points off and exact once `temp_a0 = arg0->unk6C;` moved from after its first use to the top of
the body. Each variant moves one such assignment, a whole statement at the function's top level, to just before
the first statement that reads the variable, or to the start of the statements, when nothing it reads is
assigned in between.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'read_before_assign'
FAMILIES = (FAMILY,)

IDENT = re.compile(r'[A-Za-z_]\w*')
KEYWORDS = frozenset('''auto break case char const continue default do double else enum extern float for goto if int
long register return short signed sizeof static struct switch typedef union unsigned void volatile while'''.split())


def _statements(clean, opening, end):
    """Top-level statements of the body between `opening` ({) and `end` (index of its }): (start, stop) spans."""
    spans = []
    i, start, paren = opening + 1, opening + 1, 0
    while i < end:
        c = clean[i]
        if c == '(':
            paren += 1
        elif c == ')':
            paren -= 1
        elif c == '{' and paren == 0:
            stop = close(clean, i, '{', '}')
            if not stop:
                return []
            i = stop
            # (a block statement ends at its brace, unless an `else` or `while (...);` continues it)
            follow = clean[i:end].lstrip()
            if follow.startswith('else') or follow.startswith('while'):
                continue
            spans.append((start, i))
            start = i
            continue
        elif c == ';' and paren == 0:
            spans.append((start, i + 1))
            start = i + 1
        i += 1
    return [(a, b) for a, b in spans if clean[a:b].strip()]


def _assigned(text, var):
    """True when `text` assigns `var` (=, op=, ++, --)."""
    return bool(re.search(rf'(?<![\w.>]){re.escape(var)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', text)
                or re.search(rf'(?:\+\+|--)\s*{re.escape(var)}\b|\b{re.escape(var)}\s*(?:\+\+|--)', text))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    end -= 1
    statements = _statements(clean, opening, end)
    declared = []
    first_code = None
    for index, (a, b) in enumerate(statements):
        text = clean[a:b].strip()
        decl = re.fullmatch(r'(?:register\s+|static\s+|volatile\s+|const\s+|unsigned\s+|signed\s+)*'
                            r'(?:struct\s+|union\s+|enum\s+)?[A-Za-z_]\w*[\s*]+([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)*;', text)
        if decl and decl[1] not in KEYWORDS:
            declared.append(decl[1])
        elif first_code is None:
            first_code = index
    if first_code is None:
        return []
    result = []
    for var in declared:
        word = re.compile(rf'\b{re.escape(var)}\b')
        assign = re.compile(rf'\s*{re.escape(var)}\s*=(?!=)')
        first_read = first_assign = None
        for index in range(first_code, len(statements)):
            a, b = statements[index]
            text = clean[a:b]
            if assign.match(text) and text.rstrip().endswith(';') and first_assign is None:
                rhs = text[text.index('=') + 1:]
                if word.search(rhs):
                    break  # (x = f(x): a read first; nothing to move)
                first_assign = index
                break
            if word.search(text):
                if first_read is None:
                    first_read = index
        if first_assign is None or first_read is None:
            continue
        a, b = statements[first_assign]
        moved = source[a:b].strip()
        rhs_names = set(IDENT.findall(clean[a:b][clean[a:b].index('=') + 1:])) - KEYWORDS
        for target in dict.fromkeys((first_read, first_code)):
            between = ''.join(clean[x:y] for x, y in statements[target:first_assign])
            if any(_assigned(between, other) for other in rhs_names):
                continue  # (its value would change)
            if re.search(r'\b(?:goto|return|break|continue)\b|^\s*\w+\s*:(?!:)', between, re.M):
                continue  # (control flow between the two places: moving it could skip or repeat it)
            if any(c in between for c in '{}') and target != first_read:
                continue
            ta = statements[target][0]
            stripped = source[ta:statements[target][1]]
            indent = re.match(r'\s*', stripped)[0]
            insert = ta + len(indent)
            line_indent = indent.rsplit('\n', 1)[-1]
            # (the statement's span starts at the previous one's end, so its own line break and indentation go too)
            text = source[:insert] + moved + '\n' + line_indent + source[insert:a] + source[b:]
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result
