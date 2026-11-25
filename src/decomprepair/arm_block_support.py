"""Brace and statement helpers for the rewrites that move statements into or out of the arms of an `if`/`else` chain.

Not a C parser: it reads the comment-blanked text of one function, pairs its braces and cuts a block into its top-level
statements, which is all the arm rewrites need (call_into_each_arm, arm_constants_to_head, local_pointer_web_split,
shared_sum_local)."""
import re

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*'
KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'do', 'else', 'case', 'default', 'goto', 'break',
            'continue'}


def _python_brace_pairs(clean, lo, hi):
    """{index of `{`: index of its `}`} for the braces in clean[lo:hi]; None when they do not pair."""
    stack, found = [], {}
    for at in range(lo, hi):
        char = clean[at]
        if char == '{':
            stack.append(at)
        elif char == '}':
            if not stack:
                return None
            found[stack.pop()] = at
    return None if stack else found


brace_pairs = _python_brace_pairs
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def brace_pairs(clean, lo, hi):
        found = _scan.brace_pairs_strict(clean, lo, hi)
        return _python_brace_pairs(clean, lo, hi) if found is NotImplemented else found


def statements(clean, lo, hi):
    """The top-level statements of clean[lo:hi] as (start, end) spans, `end` just past the `;` or the closing `}` of a
    compound statement (an `if`/`else` chain and a `do { } while (...);` are one statement)."""
    spans, at, depth, begin = [], lo, 0, None
    while at < hi:
        char = clean[at]
        if begin is None:
            if char.isspace():
                at += 1
                continue
            begin = at
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                tail = clean[at + 1:hi].lstrip()
                if re.match(r'else\b', tail) or (re.match(r'while\b', tail) and re.search(r'\bdo\s*$', clean[begin:at])):
                    pass
                elif re.match(r'while\b', tail) and re.match(r'do\b', clean[begin:hi]):
                    pass
                else:
                    spans.append((begin, at + 1))
                    begin = None
        elif char == ';' and depth == 0:
            spans.append((begin, at + 1))
            begin = None
        at += 1
    return spans


def arm_chain(clean, pairs_by_close, closing):
    """The blocks of the `if`/`else` chain whose last `else` block closes at `closing`, first to last, as (open, close)
    spans; None when `closing` does not end an `else` block of an `if (...) { } else { }` chain written with braces."""
    blocks = []
    current = closing
    while True:
        opening = pairs_by_close.get(current)
        if opening is None:
            return None
        blocks.append((opening, current))
        before = clean[:opening].rstrip()
        if before.endswith('else'):
            before = before[:-4].rstrip()
            if not before.endswith('}'):
                return None
            current = len(before) - 1
            continue
        if not before.endswith(')'):
            return None
        depth, at = 0, len(before)
        while at > 0:
            at -= 1
            depth += (before[at] == ')') - (before[at] == '(')
            if depth == 0:
                break
        header = clean[:at].rstrip()
        if not re.search(r'\bif$', header):
            return None
        header = header[:-2].rstrip()
        if header.endswith('else'):
            header = header[:-4].rstrip()
            if not header.endswith('}'):
                return None
            current = len(header) - 1
            continue
        break
    blocks.reverse()
    return blocks if len(blocks) >= 2 else None


def line_start(text, at):
    return text.rfind('\n', 0, at) + 1


def indentation(text, at):
    start = line_start(text, at)
    return re.match(r'[ \t]*', text[start:at])[0]


def local_declaration(clean, opening, name):
    """(base type, stars) of the local `name`, from a plain declaration (`T a, *b;`, no initialiser) in the statements
    that open the function body (the ones before its first statement that is not a declaration); None otherwise."""
    pos = opening + 1
    while True:
        found = re.compile(r'\s*(?P<type>(?:(?:unsigned|signed|const|volatile|struct|union)\s+)*' + IDENT +
                           r'(?:\s+' + IDENT + r')*?)\s+(?P<decls>\*{0,3}\s*' + IDENT + r'(?:\[[^\]]*\])?(?:\s*,\s*\*{0,3}\s*' + IDENT +
                           r'(?:\[[^\]]*\])?)*)\s*;').match(clean, pos)
        if not found:
            return None
        for decl in found['decls'].split(','):
            decl = decl.strip()
            hit = re.fullmatch(r'(\*+)\s*(' + IDENT + r')|(' + IDENT + r')', decl)
            if hit and (hit.group(2) or hit.group(3)) == name:
                return found['type'].strip(), hit.group(1) or ''
        pos = found.end()


def mentions(text, name):
    return [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b(?!\s*\()', text)]
