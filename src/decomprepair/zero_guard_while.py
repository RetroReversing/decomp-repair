"""m2c's guard on a register it knew held zero, before a counted `do`, written as a `while` with the counter zeroed first.

For a counted loop gcc 2.7.2 copies the exit test in front of the body, and cse replaces the counter's known zero in
that copy with any register in the same equivalence class, the oldest first (`canon_reg`). m2c then reads the copy
literally, with the other register, and puts the counter's zero inside it:

    if (flag < n) {                      i = 0;
        i = 0;                           if (flag < n) {
        p = base + 4;          ->            p = base + 4;
        do {                                 while (i < n) {
            ...                                  ...
            i += 1;                              i += 1;
        } while (i < n);                     }
    }                                    }

Compiled as m2c wrote it, the zero is set after the guard, the delay-slot filler takes the join's first instruction
(`beqz; li $v0,-1`) instead of the zero, and every later branch offset moves. With the zero before the guard the slot
holds `move $s0,$zero` as in the target. A second child drops the guard altogether (the `while` test is the same test
when the guarded register is zero). On a 996-instruction KMC gcc 2.7.2 collision sweep the first child went 2522 -> 807
on one loop (827 on the other; the target's instruction count and the later loops' registers), the second 947.
Not the whole story there (a hypothesis): with the zero first, cse puts the counter in the guard and combine folds
the compare, leaving a condition-code `use` that costs an 8-byte stack slot, while the target keeps the `sltu`.

The children are equivalent to the source only when the guard's left operand is zero there, which is what m2c's
spelling means (the compiler's equivalence) but nothing here can check: a hypothesis per loop, for the judge.
Offered when the `do` test compares the counter that the statements before the `do` zero, against the guard's right
side, the guard's left side is not that counter, and the body has no `continue` or `goto`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'zero_guard_while'
UNGUARDED = 'zero_guard_while_unguarded'
FAMILIES = (FAMILY, UNGUARDED)
IDENT = r'[A-Za-z_]\w*'


def _norm(text):
    return re.sub(r'\s+', '', text)


def _split_less(condition):
    """`a < b` at the top level of `condition`: (a, b), or None."""
    depth = 0
    for i, ch in enumerate(condition):
        depth += (ch in '([') - (ch in ')]')
        if depth == 0 and ch == '<' and condition[i + 1:i + 2] not in ('<', '=') and condition[i - 1:i] != '<':
            return condition[:i].strip(), condition[i + 1:].strip()
    return None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    result = []
    for guard in re.finditer(r'(?m)^(?P<ind>[ \t]*)if\s*\(', clean[span[0]:span[1]]):
        at = span[0] + guard.start()
        ind = guard['ind']
        open_paren = span[0] + guard.end() - 1
        end = close(clean, open_paren)
        if end is None:
            continue
        parts = _split_less(clean[open_paren + 1:end - 1])
        if not parts:
            continue
        block = re.match(r'\s*\{', clean[end:])
        if not block:
            continue
        brace = end + block.end() - 1
        block_end = close(clean, brace, '{', '}')
        if block_end is None:
            continue
        do = re.search(r'(?m)^[ \t]*do\s*\{', clean[brace + 1:block_end])
        if not do:
            continue
        prelude_end = brace + 1 + do.start()
        prelude = source[brace + 1:prelude_end]
        do_brace = brace + 1 + do.end() - 1
        body_end = close(clean, do_brace, '{', '}')
        tail = re.match(r'\s*while\s*\(', clean[body_end:]) if body_end else None
        if not tail:
            continue
        test_open = body_end + tail.end() - 1
        test_end = close(clean, test_open)
        after = re.match(r'\s*;\s*\}', clean[test_end:]) if test_end else None
        if not after or test_end + after.end() != block_end:
            continue
        test = clean[test_open + 1:test_end - 1]
        test_parts = _split_less(test)
        if not test_parts or _norm(test_parts[1]) != _norm(parts[1]):
            continue
        zero = re.search(r'(?m)^[ \t]*(' + IDENT + r')\s*=\s*0\s*;[ \t]*\n', prelude)
        if not zero or not re.search(r'(?<![\w.>])' + zero[1] + r'\b', test_parts[0]):
            continue
        counter = zero[1]
        if re.search(r'(?<![\w.>])' + counter + r'\b', parts[0]):
            continue
        inside = clean[do_brace + 1:body_end - 1]
        if re.search(r'\b(?:continue|goto)\b', inside):
            continue
        rest = prelude[:zero.start()] + prelude[zero.end():]
        body = source[do_brace + 1:body_end - 1]
        test_text = source[test_open + 1:test_end - 1].strip()
        guarded = (f'{counter} = 0;\n{ind}' + source[at + len(ind):end] + f'\n{ind}{{' + rest +
                   f'{ind}  while ({test_text})\n{ind}  {{{body}}}\n{ind}}}')
        unguarded = (f'{counter} = 0;' + rest.rstrip() + f'\n{ind}while ({test_text})\n{ind}{{{body}}}')
        stop = block_end
        result.append((FAMILY, source[:at + len(ind)] + guarded + source[stop:]))
        result.append((UNGUARDED, source[:at + len(ind)] + unguarded + source[stop:]))
    return result[:6]
