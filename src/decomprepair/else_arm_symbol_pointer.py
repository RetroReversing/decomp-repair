"""A dispatch's later arms reading a small global array through a pointer of their own, set inside a one-shot scope.

KMC GCC 2.7.2 at `-O1`: `if (..T[0].. T[1]..) {..} else if (T[0] == n + 1 && T[1] == m) {..} else if (T[0] != n - 1 ||
T[1] != m) f = 1; else if (..) f = 1;` where the target takes `T`'s address once for the later arms (`lui; addiu` into
a register, `lb 1(reg)`) and the first arm keeps a pointer of its own. A plain local `p = T;` is not enough: the
compiler folds `p[1]` back into the symbol's own address. The target's shape needs three things together, none of which
moves the score on its own (a controlled 740 -> 0):

  the later arms read a local `p`, set by `do { p = T; } while (0);` at the start of the `else`;
  an `if (A || B) S;` among those arms written as `if (A) S; else if (B) S;`;
  the whole `if`/`else` chain in one `do { } while (0);`.

Children are the pointer alone and with each of the other two, so a greedy search sees the combination as one step.
The wrappers are scaffolding no developer wrote; polishing removes them once the function is recorded as matched. That
the loop note stops the symbol folding is a hypothesis read from the output, not from the compiler's source.
"""
import re

from . import interpreter_arm_steps, run_weight_scope
from .integer_repair_support import IDENT, edit, view
from .statement_across_call import _blocks, _statements

FAMILY = 'else_arm_symbol_pointer'
FAMILIES = (FAMILY,)
LIMIT = 24
_ARRAY = re.compile(rf'\bextern\s+(?P<type>(?:(?:unsigned|signed|const)\s+)?{IDENT})\s+(?P<name>{IDENT})\s*\[[^\]\n]*\]\s*;')
_BARRED = re.compile(r'\b(?:break|continue|goto|case|default|asm|__asm__|volatile|setjmp|longjmp)\b|(?<![\w?])[A-Za-z_]\w*\s*:(?!:)')
_ELSE_IF = re.compile(r'\belse\s+(?=if\b)')


def _reads(text, symbol):
    return set(re.findall(rf'(?<![\w.>&]){re.escape(symbol)}\s*\[\s*(\d+)\s*\]', text))


def _chain(clean, opening, end, at):
    """The innermost block statement starting with `if` (its whole `else` chain) that holds position `at`."""
    found = None
    for lo, hi in _blocks(clean, opening + 1, end):
        for start, _, _ in _statements(clean, lo, hi):
            if start >= at or not re.match(r'if\b', clean[start:]):
                continue
            stop = run_weight_scope._statement_end(clean, start, end - 1)
            if at < stop and (found is None or stop - start < found[1] - found[0]):
                found = start, stop
    return found


def _split_or(source, clean, start, end):
    """The first `if (A || B) S;` inside [start, end) written as two `if`s: (from, to, text)."""
    for m in re.finditer(r'(?<![\w.])if\s*\(', clean[start:end]):
        head = start + m.start()
        paren = start + m.end() - 1
        close = run_weight_scope._match(clean, paren, '(', ')')
        if close < 0:
            continue
        # one top-level `||` (written with spaces round it, as m2c and the app write it)
        parts = interpreter_arm_steps._split_top(source[paren + 1:close - 1], '||')
        if not parts or interpreter_arm_steps._split_top(parts[1], '||'):
            continue
        first, second = parts
        statement = re.compile(rf'\s*(?P<s>{IDENT}\s*=(?!=)\s*[^;{{}}()=]+;)').match(clean, close)
        if not statement:
            continue
        s = source[statement.start('s'):statement.end('s')]
        return head, statement.end('s'), f'if ({first}) {s} else if ({second}) {s}'
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    if _BARRED.search(body) or 'else' not in body:
        return []
    arrays = [m for m in _ARRAY.finditer(clean[:part.opening]) if _reads(body, m['name'])]
    if not arrays:
        return []
    out = []
    for m in _ELSE_IF.finditer(clean, part.opening, part.end):
        start = m.end()
        end = run_weight_scope._statement_end(clean, start, part.end - 1)
        if end < 0:
            continue
        chain = _chain(clean, part.opening, part.end, m.start())
        if not chain:
            continue
        for array in arrays:
            symbol = array['name']
            # two different elements read after the `else`, and the symbol read before it: a dispatch's later arms
            if len(_reads(clean[start:end], symbol)) < 2 or not _reads(clean[chain[0]:m.start()], symbol):
                continue
            local = f'p_{symbol}'
            if re.search(rf'\b{re.escape(local)}\b', source):
                continue
            declare = (part.opening + 1, part.opening + 1, f' {array["type"]} *{local};')
            reads = [(start + r.start(), start + r.start() + len(symbol), local)
                     for r in re.finditer(rf'(?<![\w.>&]){re.escape(symbol)}(?=\s*\[)', clean[start:end])]
            for split in (True, False):
                found = _split_or(source, clean, start, end) if split else None
                if split and not found:
                    continue
                inner = source[start:end]
                shifted = [(a - start, b - start, text) for a, b, text in reads]
                if found:
                    a, b, text = found
                    text = re.sub(rf'(?<![\w.>&]){re.escape(symbol)}(?=\s*\[)', local, text)
                    shifted = [item for item in shifted if not a - start <= item[0] < b - start]
                    shifted.append((a - start, b - start, text))
                tail = f'{{ do {{ {local} = {symbol}; }} while (0); {edit(inner, shifted)} }}'
                for wrap in (True, False):
                    if wrap:
                        whole = source[chain[0]:start] + tail + source[end:chain[1]]
                        edits = [(chain[0], chain[1], f'do {{ {whole} }} while (0);'), declare]
                    else:
                        edits = [(start, end, tail), declare]
                    out.append((FAMILY, edit(source, edits)))
    return list(dict.fromkeys(item for item in out if item[1] != source))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 92, 'archs': ('mips',)}
