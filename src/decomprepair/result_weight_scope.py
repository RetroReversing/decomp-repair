"""A call's result assigned to a local, or the guarded `if` that assigns it, in a one-shot scope: one reference more.

GCC 2.x hands registers to global pseudos in order of `floor_log2(refs) * refs / live length` (global.c), and flow.c
counts a reference once more per loop it sits in, so `do { x = f(..); } while (0);` is one reference more for `x` at no
instruction cost. `call_weight_ladder` and `argument_weight_scope` wrap call *statements* for their arguments; neither
reads a call whose result is stored, so a local that only needs one reference more to outrank another never got it.

A 1300-instruction KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) controller routine ended at 65 with two float locals
exchanged between `$f20` and `$f24` on thirteen rows: the stick value (`x = 0.0f; if (..) { if (m != 2 & m != 5) x =
getAxis(..); }`, 7 references over 56 instructions, 0.25) lost `$f20` to the scale it selects (6 over 36, 0.33). The
inner `if` written as a statement macro would be (`do { if (..) { x = getAxis(..); } } while (0);`, or just the assignment
in the scope) gives `x` 8 references (0.43) and the match: 65 -> 0. Read off the `-dl -dg` priority table; a
hypothesis about what the game's macro was, not confirmed in its source. The wrapper is scaffolding when no macro was
there: report it.

result_weight_scope
    Each statement `V = f(..);` (V a plain local, f a call) offered in a scope of its own, and, when it is the only
    statement of an `if` with no `else`, that `if` in a scope instead. One child per statement and form, those of the
    `if` first; at most LIMIT."""
import re

from .csource import _blank, find

FAMILY = 'result_weight_scope'
FAMILIES = (FAMILY,)
LIMIT = 16
IDENT = r'[A-Za-z_]\w*'
_KEYWORDS = frozenset({'if', 'while', 'for', 'switch', 'return', 'sizeof', 'do', 'else'})


def _span(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[span[0]:span[1]])
    return (span[0] + head.end() - 1, span[1]) if head else None


def _python_close(text, at, left, right):
    depth = 0
    for index in range(at, len(text)):
        if text[index] == left:
            depth += 1
        elif text[index] == right:
            depth -= 1
            if depth == 0:
                return index + 1
    return None


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(text, at, left, right):
        found = _scan.close_if_past(text, at, left, right, None)
        return _python_close(text, at, left, right) if found is NotImplemented else found


def _line(source, start, end):
    line = source.rfind('\n', 0, start) + 1
    stop = source.find('\n', end)
    return line, (len(source) if stop < 0 else stop + 1)


def _wrap(source, start, end):
    line, stop = _line(source, start, end)
    indent = re.match(r'[ \t]*', source[line:])[0]
    body = ''.join(f'  {text}\n' if text.strip() else '\n' for text in source[line:stop].rstrip('\n').split('\n'))
    return source[:line] + f'{indent}do\n{indent}{{\n{body}{indent}}}\n{indent}while (0);\n' + source[stop:]


def variants(source, name):
    span = _span(source, name)
    if not span:
        return []
    clean = _blank(source)
    statement = re.compile(rf'^[ \t]*(?P<var>{IDENT})\s*=\s*(?P<call>{IDENT})\s*\([^;{{}}]*\)\s*;[ \t]*$', re.M)
    guarded, plain = [], []
    for hit in statement.finditer(clean, span[0], span[1]):
        if hit['call'] in _KEYWORDS or hit['var'] in _KEYWORDS:
            continue
        if not re.search(rf'^[ \t]*[A-Za-z_][\w ]*?[ \t*]+{re.escape(hit["var"])}[ \t]*;', clean[span[0]:span[1]], re.M):
            continue
        before = clean[:hit.start()].rstrip()
        after = clean[hit.end():].lstrip()
        if before.endswith('{') and after.startswith('}'):
            opening = len(before) - 1
            prefix = clean[:opening].rstrip()
            if prefix.endswith(')'):
                # the `if` whose condition ends right before this block
                depth, at = 0, len(prefix) - 1
                while at >= 0:
                    depth += (prefix[at] == ')') - (prefix[at] == '(')
                    if depth == 0:
                        break
                    at -= 1
                keyword = re.search(r'\bif\s*$', prefix[:at])
                closing = _close(clean, opening, '{', '}')
                if keyword and closing and not re.match(r'\s*else\b', clean[closing:]):
                    guarded.append(_wrap(source, keyword.start(), closing - 1))
        plain.append(_wrap(source, hit.start('var'), hit.end()))
    out, seen = [], set()
    for child in guarded + plain:
        if child != source and child not in seen:
            seen.add(child)
            out.append((FAMILY, child))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
