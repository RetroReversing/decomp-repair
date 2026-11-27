"""m2c's `-1` sentinel countdown, written back as the `while (n-- != 0)` it stands for.

GCC 2.7.2 rewrites a `while (n-- != 0)` over an unsigned `n` as a comparison of `n - 1` with -1, so m2c draws it as

    n = E - 1;
    if (n != -1) {
        for (;;) {                      /* or do { ... } while (n != -1); */
            n -= 1;
            BODY
            if (n == -1) { goto after; }
        }
    }
    after:

The two run BODY the same E times and both leave `n` at -1, but the compiler does not see them as one program: the
spelled-out form makes its own entry test and its own -1, and the registers and delay slots follow. This writes

    n = E;
    while (n-- != 0) {
        BODY
    }

only when `n` is a 32-bit local that BODY and the statements before the guard never mention, and BODY has no jump of
its own (`break`, `continue`, `goto`). The exit inside a `for (;;)` may be `break;`, a `goto` to the label right after
the guard, or the `return` that also follows the guard.

Measured on one match (an N64 directory lookup, `sn-n64-281 -G0 -mips3 -O2 -mfp64`, the last step): 785 -> 0.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'sentinel_countdown_postdec'
FAMILIES = (FAMILY,)

WIDE = r'(?:u32|s32|unsigned\s+int|signed\s+int|unsigned|int|unsigned\s+long|long)'
NEG = r'(?:\(\s*-\s*(?:1|0x1)\s*\)|-\s*(?:1|0x1)(?!\w)|0xFFFFFFFFU?(?!\w))'
ONE = r'(?:1|0x1)(?!\w)'


def _sum_only(text):
    """Whether `text - 1` subtracts from the whole of `text`: no operator outside brackets binds looser than `-`."""
    flat, depth = [], 0
    for char in text:
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
            flat.append('x' if depth == 0 else '')
        elif depth == 0:
            flat.append(char)
    return depth == 0 and re.fullmatch(r'(?:[\w\s.+*]|->|-)+', ''.join(flat)) is not None


def _skip(text, at):
    while at < len(text) and text[at].isspace():
        at += 1
    return at


def _block(clean, opening):
    """The index just past the `}` that closes the `{` at `opening`, or None."""
    end = close(clean, opening, '{', '}')
    return end if end and end > opening else None


def _loop(clean, at, limit, counter, after):
    """(body_start, body_end, loop_end, exit_label) of the loop at `at`, or None. Spans are into `clean`."""
    name = re.escape(counter)
    step = rf'\s*(?:{name}\s*-=\s*{ONE}|{name}\s*--|--\s*{name}\b|{name}\s*=\s*{name}\s*-\s*{ONE})\s*;'
    head = re.compile(r'(?P<kind>for\s*\(\s*;\s*;\s*\)|do)\s*\{').match(clean, at, limit)
    if not head:
        return None
    opening = head.end() - 1
    end = _block(clean, opening)
    if end is None or end > limit:
        return None
    first = re.compile(step).match(clean, opening + 1, end - 1)
    if not first:
        return None
    start = first.end()
    if head['kind'] == 'do':
        tail = re.compile(rf'\s*while\s*\(\s*{name}\s*!=\s*{NEG}\s*\)\s*;').match(clean, end, limit)
        return (start, end - 1, tail.end(), None) if tail else None
    leave = (rf'if\s*\(\s*{name}\s*==\s*{NEG}\s*\)\s*\{{\s*(?P<exit>break|goto\s+(?P<label>{IDENT})|return\b[^;{{}}]*)\s*;'
             r'\s*\}(?:\s*continue\s*;)?(?:\s*break\s*;)?\s*$')
    last = re.compile(leave).search(clean, start, end - 1)
    if not last:
        return None
    label = last['label']
    if label and not re.compile(rf'\s*{label}\s*:(?!:)').match(clean, after):
        return None
    if last['exit'].startswith('return'):
        follows = re.compile(rf'(?:\s*{IDENT}\s*:(?!:))*\s*(return\b[^;{{}}]*);').match(clean, after)
        if not follows or follows[1].split() != last['exit'].split():
            return None
    return start, last.start(), end, label


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    if re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    out = []
    starts = re.compile(rf'(?<=[;{{}}])\s*(?P<name>{IDENT})\s*=(?!=)(?P<value>[^;{{}}]+?)\s*-\s*{ONE}\s*;')
    for init in starts.finditer(clean, part.opening, part.end):
        counter, value = init['name'], init['value'].strip()
        word = re.escape(counter)
        if len(re.findall(rf'(?<![\w.>])(?:{WIDE})\s+{word}\s*;', part.body)) != 1 or re.search(rf'&\s*{word}\b\s*[),;]', part.body):
            continue
        if not _sum_only(value) or re.search(rf'\b{word}\b', value):
            continue
        guard = re.compile(rf'\bif\s*\(\s*{word}\s*!=\s*{NEG}\s*\)\s*\{{').search(clean, init.end(), part.end)
        if not guard:
            continue
        between = clean[init.end():guard.start()]
        if re.search(rf'\b{word}\b|[{{}}]|\b(?:goto|return|if|for|while|do|switch)\b|(?<!:):(?!:)', between):
            continue
        guard_end = _block(clean, guard.end() - 1)
        if guard_end is None or re.compile(r'\s*else\b').match(clean, guard_end):
            continue
        found = _loop(clean, _skip(clean, guard.end()), guard_end - 1, counter, guard_end)
        if not found:
            continue
        body_start, body_end, loop_end, label = found
        if clean[loop_end:guard_end - 1].strip():
            continue
        body = clean[body_start:body_end]
        if re.search(rf'\b{word}\b|\b(?:break|continue|goto|case|default)\b', body):
            continue
        indent = source[source.rfind('\n', 0, guard.start()) + 1:guard.start()]
        indent = indent if not indent.strip() else '    '
        inner = source[body_start:body_end].strip('\n').rstrip()
        loop = f'while ({counter}-- != 0) {{\n{inner}\n{indent}}}'
        value_text = source[init.start('value'):init.end('value')].strip()
        edits = [(init.start('value'), init.end(), f' {value_text};'), (guard.start(), guard_end, loop)]
        if label and len(re.findall(rf'\bgoto\s+{label}\b', part.body)) == 1:
            marker = re.compile(rf'\s*{label}\s*:').match(clean, guard_end)
            empty = re.compile(r'\s*;').match(clean, marker.end())
            edits.append((guard_end, empty.end() if empty else marker.end(), ''))
        out.append((FAMILY, edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
