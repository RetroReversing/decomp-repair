"""A chained assignment `a = b = t;` written as separate statements, and two adjacent ones joined into a chain.

GCC expands `a = b = t;` as one value: `t` is evaluated once into a register that both stores read, and the register of
`b`'s store is the value of the whole expression. Written as `b = t; a = b;` the second store reads `b` back (a load
for a field or a global, since a store through a pointer or to a global is not forwarded across a barrier), and written
as `b = t; a = t;` both read `t`. Hand matches on N64 SN GCC 2.8.1 code needed the field read-back
(`p->a = p->b = t;` against `p->b = t; p->a = p->b;`: one load and one `lwc1` the chain never emits, and the call that
followed took its argument from the last field stored, func_8007F898/func_800730E0-shaped functions), and the
reverse for m2c output that split a chain the original had.

A third shape is the temporary fan-out m2c writes for a value copied to two fields and then passed on:
`t = SRC; A = t; B = t; dist = f(o, 0, t);` against `A = SRC; B = SRC; dist = f(o, 0, B);` (the field loaded twice, the
call's argument read back from the last field stored: a function whose three fields held one value in the original).
For three consecutive lines `t = SRC;`, `A = t;`, `B = t;` (t a local identifier, SRC free of calls) whose later uses
of `t` are all within the next four lines (and none after), the children store SRC to each field and read the later
uses of `t` from `B`, from `A`, or as SRC again.

Children, for each statement `A = B = E;` (A and B each an identifier, a member, an index or a dereference, E free of
a call, `++`/`--` or a second assignment): `B = E; A = B;` (the read-back), and `B = E; A = E;` when E is a plain
name, member or literal (no side effect to repeat). And for each pair of adjacent statements `B = E; A = B;` (the
second reading exactly the first's target): the chain `A = B = E;`. A chain of two stores of one constant is left to
`arm_local_return_fold`. At most `LIMIT` children; a function with `volatile`, `asm` or a preprocessor line is left
alone. Proposals only; the judge decides."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'chained_assignment_split'
FAMILIES = (FAMILY,)
LIMIT = 8
_LINE = re.compile(r'(?m)^([ \t]*)([^\n;{}]+);[ \t]*$')
_LVALUE = re.compile(rf'\*?\s*\(?\s*{IDENT}(?:\s*(?:->|\.)\s*{IDENT}|\s*\[[^\[\]=;]*\])*\s*\)?')
_LITERAL = re.compile(r'-?(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?[fF]?)$')
_NOT_STATEMENT = {'if', 'while', 'for', 'switch', 'return', 'case', 'else', 'do', 'goto'}


def _assignments(text):
    """The parts of `text` split at its top-level plain `=` signs (a compound assignment or compare is not one)."""
    parts, depth, last = [], 0, 0
    for i, c in enumerate(text):
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c == '=' and depth == 0:
            before, after = text[i - 1:i], text[i + 1:i + 2]
            if before in '=!<>+-*/%&|^' and before or after == '=':
                if after == '=':
                    return None
                continue
            parts.append(text[last:i])
            last = i + 1
    parts.append(text[last:])
    return [part.strip() for part in parts]


def _free(expr):
    return not re.search(rf'{IDENT}\s*\(|\+\+|--|[^=!<>]=[^=]', expr)


def _plain(expr):
    return bool(re.fullmatch(rf'-?{IDENT}(?:\s*(?:->|\.)\s*{IDENT})*', expr.strip()) or _LITERAL.match(expr.strip()))


_FANOUT = re.compile(rf'(?m)^([ \t]*)(?P<t>{IDENT})\s*=(?!=)\s*(?P<src>[^;=\n]+);[ \t]*\n'
                     rf'[ \t]*(?P<a>[^;=\n]+?)\s*=(?!=)\s*(?P=t)\s*;[ \t]*\n[ \t]*(?P<b>[^;=\n]+?)\s*=(?!=)\s*(?P=t)\s*;[ \t]*$')


def _fanout(source, part):
    out = []
    for hit in _FANOUT.finditer(part.clean, part.opening + 1, part.end):
        t, src, a, b = hit['t'], hit['src'].strip(), hit['a'].strip(), hit['b'].strip()
        if t in _NOT_STATEMENT or not _free(src) or a == b or re.search(rf'\b{t}\b', a + b) or not re.search(r'->|\*|\[', src):
            continue
        rest = part.clean[hit.end():part.end]
        window_end = 0
        for _ in range(5):  # the rest of the third line, then four more
            nxt = rest.find('\n', window_end) + 1
            if not nxt:
                window_end = len(rest)
                break
            window_end = nxt
        later = [m.start() for m in re.finditer(rf'(?<![\w.>]){t}\b', rest)]
        if not later or any(at >= window_end for at in later):
            continue
        for use in (b, a, f'({src})' if '*' in src else src):
            tail = re.sub(rf'(?<![\w.>]){t}\b', lambda _, use=use: use, rest[:window_end])
            text = f'{hit[1]}{a} = {src};\n{hit[1]}{b} = {src};'
            out.append((FAMILY, source[:hit.start()] + text + tail + source[hit.end() + window_end:]))
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    if re.search(r'\b(?:volatile|asm|__asm__)\b|^\s*#', body, re.M):
        return []
    out = []
    lines = [(m, _assignments(m[2])) for m in _LINE.finditer(part.clean, part.opening + 1, part.end)]
    for hit, parts in lines:
        if not parts or len(parts) != 3:
            continue
        a, b, e = parts
        if a.split()[0] in _NOT_STATEMENT or not _free(e) or not _LVALUE.fullmatch(a) or not _LVALUE.fullmatch(b) or not e:
            continue
        indent = hit[1]
        forms = [f'{b} = {e};\n{indent}{a} = {b};']
        if _plain(e) and not _LITERAL.match(e):
            forms.append(f'{b} = {e};\n{indent}{a} = {e};')
        for text in forms:
            out.append((FAMILY, edit(source, [(hit.start(2), hit.end(), text)])))
    for (first, one), (second, two) in zip(lines, lines[1:]):
        if not one or not two or len(one) != 2 or len(two) != 2 or source[first.end():second.start()].strip():
            continue
        b, e = one
        a, again = two
        if b.split()[0] in _NOT_STATEMENT or a == b or again != b or not e or not _free(e):
            continue
        if not _LVALUE.fullmatch(a) or not _LVALUE.fullmatch(b):
            continue
        out.append((FAMILY, edit(source, [(first.start(2), second.end(), f'{a} = {b} = {e};')])))
    out += _fanout(source, part)
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
