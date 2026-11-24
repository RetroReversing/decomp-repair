"""A guard over a do-while with the same test, whose block only sets up the loop, written as the `while` it was:
`if (T[k] == c) { u32 hb = 1 << c; u32 *tp = T; do { B(hb) } while (tp[k] == c); }` as `while (T[k] == c) { B(1 << c) }`.

KMC GCC 2.7.2 (`-O2`, N64): a `while` loop's entry test is copied in front of the loop by jump.c and its invariants are
moved by loop.c into the loop's own preheader, after that copy: the target's guard block (`bne ..; sll $v0,$t3,2` then
`li; sllv` for `1 << c`) is the preheader. Written as the guard and the do-while, the same block is the C's: its
statements are where cse saw them, and cse gave the guard's table address (a temporary loop.c later hoists to the
entry and spills) to the pointer the block set, so the step the loop derives from it started from the reload register
(`lui $s7,%hi(T)`) where the target loads it fresh (`lui $v1,%hi(T)`), the loop's own copy of the test being a
temporary of its own.

On a 681-instruction bit-stream decoder's code-assignment pass: 230 -> 215 (checked on 1200 generated streams), with no
pointer local and no constant local left; the same rewrite of the later passes' `if (H[c] != 0) { do { } while (*lim >=
i); }` as `for (i = 1; i <= H[c]; i++, k++)` kept 215 without their shared pointer.

Offered for `if (C) { [E *p = T;] [E v = X;] .. do { B } while (C2); }` when the block holds only those declarations and
the loop, C2 is C once each pointer `p` set to a global array is read as that array, each other declared `v` is used
only in B, X has no call, assignment or increment, and neither `v` nor X's names are assigned in B. The declared values
are substituted in B (`(X)`) and the guard becomes `while (C) { B }`. Declines on `volatile`, `continue` or `break` in B.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'guarded_do_while_loop'
FAMILIES = (FAMILY,)
LIMIT = 6

_TYPE = r'(?:unsigned\s+(?:int|short|char)|s32|u32|s16|u16|s8|u8|int|short|f32)'
_DECL = re.compile(rf'\s*({_TYPE})\s*(\*?)\s*({IDENT})\s*=\s*([^;]+);')


def _close(text, at, left, right):
    depth = 0
    for i in range(at, len(text)):
        depth += (text[i] == left) - (text[i] == right)
        if depth == 0:
            return i
    return None


def _norm(text):
    return re.sub(r'\s+', '', text)


def _assigned(text, name):
    return re.search(rf'(?<![\w.>])(?:{name}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))|(?:\+\+|--)\s*{name}\b)', text)


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(r'\bvolatile\b', clean[lo:hi]):
        return []
    tables = set(re.findall(rf'(?m)^[ \t]*extern\s+{_TYPE}\s+({IDENT})\s*\[', header + '\n' + source))
    out = []
    for guard in re.finditer(r'\bif\s*\(', clean[lo:hi]):
        cond_open = lo + guard.end() - 1
        cond_close = _close(clean, cond_open, '(', ')')
        brace = re.compile(r'\s*\{').match(clean, cond_close + 1) if cond_close else None
        if not brace:
            continue
        opening = brace.end() - 1
        closing = _close(clean, opening, '{', '}')
        if closing is None or re.compile(r'\s*else\b').match(clean, closing + 1):
            continue
        at, decls = opening + 1, []
        while True:
            found = _DECL.match(clean, at)
            if not found:
                break
            decls.append(found)
            at = found.end()
        loop = re.compile(r'\s*do\s*\{').match(clean, at)
        if not loop:
            continue
        body_open = loop.end() - 1
        body_close = _close(clean, body_open, '{', '}')
        tail = re.compile(r'\s*while\s*\(').match(clean, body_close + 1) if body_close else None
        if not tail:
            continue
        c2_open = tail.end() - 1
        c2_close = _close(clean, c2_open, '(', ')')
        end = re.compile(r'\s*;\s*').match(clean, c2_close + 1)
        if not end or end.end() != closing:
            continue
        body = source[body_open + 1:body_close]
        if re.search(r'\b(?:continue|break)\b', clean[body_open + 1:body_close]):
            continue
        cond, cond2 = source[cond_open + 1:cond_close], source[c2_open + 1:c2_close]
        ok = True
        for decl in decls:
            var, value, pointer = decl.group(3), decl.group(4).strip(), decl.group(2)
            if pointer and value in tables:
                cond2 = re.sub(rf'(?<![\w.>]){var}\b', value, cond2)
                body = re.sub(rf'(?<![\w.>]){var}\b', value, body)
                continue
            if (re.search(r'\(\s*[^)]*\)\s*\(|\+\+|--|(?<![=!<>])=(?!=)', value) or re.search(rf'\b{var}\b', cond2)
                    or _assigned(body, var)
                    or any(_assigned(body, ident) for ident in re.findall(IDENT, value))):
                ok = False
                break
            body = re.sub(rf'(?<![\w.>]){var}\b', f'({value})', body)
        if not ok or _norm(cond2) != _norm(cond):
            continue
        indent = re.match(r'[ \t]*', clean[clean.rfind('\n', 0, guard.start() + lo) + 1:]).group(0)
        # the body was one level deeper: dedent it by the guard block's step
        inner = re.match(r'\n([ \t]*)', source[body_open + 1:])
        step = (len(inner.group(1)) - len(indent)) // 2 if inner else 0
        if step > 1:
            body = re.sub(r'(?m)^' + ' ' * (2 * (step - 1)), '', body)
        text = f'while ({cond}) {{{body}}}'
        out.append((FAMILY, edit(source, [(lo + guard.start(), closing + 1, text)])))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
