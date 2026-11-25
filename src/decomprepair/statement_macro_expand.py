"""A function-like `#define` used inside the function, written out where it is used.

A saved best that a search built often carries a statement macro: `#define VERTICES(step, read) q = p + 2; ... ++p` above
the function, `VERTICES(3, (x = q[0], ...));` in four arms, or a packing macro (`TRI(a, b, c)`) around a bit-field word.
The compiler sees the expanded text, so the macro changes nothing in the bytes, but every family that reads a function's
text works on the macro's *call*, not on its statements: a loop inside the macro is invisible to the loop families, a local
assigned in it to the local-splitting ones, a cursor stepped in it to the cursor folds, and `integer_repair_support.view`
declines a body whose macros it cannot read. The 559-instruction display-list builder (`gcc-2.7.2-kmc -G0 -mips3 -mgp32
-mfp32 -O2`) that this came from had four statement-macro loops: written out, `local_web_split`, `region_local_split`,
`cursor_base_index_loop` and `frame_struct_unwrap` all had something to offer (3370 -> 2375 -> 1970 -> 950 -> 55 in the
steps that followed), and none of them had before.

`variants` offers the function with every function-like macro it uses written out (`statement_macro_expand`), the
`#define` kept when anything still names it. The expansion is the preprocessor's own, textually: each parameter replaced
by its argument as written (no parentheses added), nested uses expanded, a macro that stringifies (`#`), pastes (`##`),
is variadic or takes the same-named argument in a way that cannot be matched is left alone. Object-like macros are not
touched.
"""
import re

from .csource import find
from .pattern_repairs import close

FAMILY = 'statement_macro_expand'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_DEFINE = re.compile(rf'(?m)^[ \t]*#[ \t]*define[ \t]+(?P<name>{_ID})\((?P<params>[^)]*)\)[ \t]*(?P<body>(?:[^\n\\]|\\\n)*)$')
MAX_DEPTH = 4


def _macros(source, upto):
    found = {}
    for hit in _DEFINE.finditer(source, 0, upto):
        body = hit['body'].replace('\\\n', ' ').strip()
        params = [p.strip() for p in hit['params'].split(',') if p.strip()] if hit['params'].strip() else []
        if '...' in hit['params'] or '#' in body or any(not re.fullmatch(_ID, p) for p in params):
            continue
        found[hit['name']] = (params, body, hit)
    return found


def _python_arguments(text, at):
    """The arguments of the call whose `(` is at `at` and the position after its `)`, or None."""
    end = close(text, at)
    if not end:
        return None
    args, depth, start = [], 0, at + 1
    for pos in range(at + 1, end - 1):
        char = text[pos]
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif char == ',' and depth == 0:
            args.append(text[start:pos].strip())
            start = pos + 1
    args.append(text[start:end - 1].strip())
    return args, end


_arguments = _python_arguments
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _arguments(text, at):
        end = close(text, at)
        if not end:
            return None
        spans = _scan.argument_spans_all(text, at + 1, end - 1)
        if spans is NotImplemented:
            return _python_arguments(text, at)
        return [text[a:b].strip() for a, b in spans], end


def _expand(text, macros, depth=0):
    """`text` with each call of a known macro replaced by its body, parameters substituted, to a bounded depth."""
    if depth > MAX_DEPTH:
        return None
    out, pos = [], 0
    for call in re.finditer(rf'(?<![\w.>])({_ID})\s*\(', text):
        if call.start() < pos or call[1] not in macros:
            continue
        params, body, _ = macros[call[1]]
        got = _arguments(text, call.end() - 1)
        if not got:
            return None
        args, end = got
        if len(params) == 0 and args == ['']:
            args = []
        if len(args) != len(params):
            return None
        mapping = dict(zip(params, args))
        replaced = re.sub(rf'(?<![\w.>])({_ID})\b', lambda w, mapping=mapping: mapping.get(w[1], w[1]), body)
        nested = _expand(replaced, macros, depth + 1)
        if nested is None:
            return None
        out.append(text[pos:call.start()])
        out.append(nested)
        pos = end
    out.append(text[pos:])
    return ''.join(out)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    macros = _macros(source, span[0])
    if not macros:
        return []
    text = source[span[0]:span[1]]
    if not any(re.search(rf'(?<![\w.>]){re.escape(m)}\s*\(', text) for m in macros):
        return []
    expanded = _expand(text, macros)
    if expanded is None or expanded == text:
        return []
    child = source[:span[0]] + expanded + source[span[1]:]
    for macro, (_, _, define) in macros.items():
        if not re.search(rf'(?<![\w.>#]){re.escape(macro)}\s*\(', child.replace(define.group(0), '', 1)):
            child = child.replace(define.group(0), '', 1)
    return [(FAMILY, child)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 96, 'directives': True}
