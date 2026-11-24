"""A whole-body null guard written as an early jump to the function's final `return 0`.

m2c and long searches leave a function that tests its list or object pointer once at the top as

    if (list != NULL) {
        ... the whole search ...                /* every success path returns 1 */
    }
    if (found == NULL) {
        return 0;
    }
    ...                                           /* copy the hit out, return 1 */

The game's code jumps from the guard straight to the zero return: the target's first branch goes to a
`j end; move $v0, $zero` of its own, after a `bnez found, copy; nop`. Written as above, cse knows `found` is still
NULL on the guard's path and jump threading folds the guard into the end, so the zero exit is merged into the epilogue
branch's delay slot (`beqz found, end; move $v0, $zero`) and the layout differs. With the guard as
`if (list == NULL) goto label;` and the label on that `return 0;` the two exits share one copy, as in the game.

Two KMC GCC 2.7.2 N64 collision functions needed it: a 1134-instruction ray caster (`ret0`, 1585 -> 890 with its
other tail edits) and a 1928-instruction collision sweep (3708 -> 3188 alone). Variants: the guard turned (`!= NULL`,
`!= 0` or a bare pointer test) when the block it opens ends just before the zero-return test, nothing but labels
between them."""
import re

from .integer_repair_support import view
from .pattern_repairs import close

FAMILY = 'guard_zero_return_label'
FAMILIES = (FAMILY,)
LABEL = '__guard_zero'
IDENT = r'[A-Za-z_]\w*'
GUARD = re.compile(rf'\bif\s*\(\s*(?:({IDENT})\s*!=\s*(?:NULL|0)|({IDENT}))\s*\)\s*\{{')
ZERO = re.compile(rf'(?:\s*{IDENT}\s*:(?!:))*\s*if\s*\(\s*(?:{IDENT}\s*==\s*(?:NULL|0)|!\s*{IDENT})\s*\)\s*\{{\s*(return\s+0\s*;)\s*\}}')


def _depth(clean, base, at):
    depth = 0
    for char in re.findall(r'[{}]', clean[base:at]):
        depth += 1 if char == '{' else -1
    return depth


def variants(source, name):
    part = view(source, name)
    if not part or LABEL in source:
        return []
    clean = part.clean
    base, end = part.opening + 1, part.end - 1
    out = []
    for guard in GUARD.finditer(clean, base, end):
        if _depth(clean, base, guard.start()) != 0 or not re.search(r'[;{}:]\s*$', clean[base - 1:guard.start()]):
            continue  # nested, or the body of an `if`/`else` without braces
        opening = guard.end() - 1
        stop = close(clean, opening, '{', '}')
        if not stop or stop > end or re.match(r'\s*else\b', clean[stop:end]):
            continue
        zero = ZERO.match(clean, stop, end)
        if not zero:
            continue
        tested = guard[1] or guard[2]
        test = f'{tested} == NULL' if guard[1] else f'!{tested}'
        line = clean.rfind('\n', 0, guard.start()) + 1
        indent = re.match(r'[ \t]*', clean[line:guard.start()])[0]
        head = f'if ({test})\n{indent}{{\n{indent}  goto {LABEL};\n{indent}}}\n{indent}{{'
        ret = zero.start(1)
        text = (source[:guard.start()] + head + source[guard.end():ret] + f'{LABEL}:\n{indent}    '
                + source[ret:])
        if text != source:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
