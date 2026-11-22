"""A cursor stepped through a record's pointer array, written back as the indexed `for` loop the game had.

A saved best that came from m2c's draft (or a hand search that kept its shape) walks a record's member array with a
byte cursor that steps with a separate counter, reading each element through a cast of the cursor:

    char *q = (char *) cur;
    do {
        SNode *nb = ((volatile SNode *) q)->nbr[0];
        i++;
        if (nb != NULL && nb->cost == -1.0f) {
            ((volatile SNode *) q)->nbr[0]->cost = ...;
            call(((volatile SNode *) q)->nbr[0]);
        }
        q += sizeof(SNode *);
    } while (i < 16);

(or m2c's own `var_s0 = var_s1; do { ... M2C_FIELD(var_s0, void **, 0x14) ... var_s2 += 1; var_s0 += 4; } while
(var_s2 < 0x10U);`). The game wrote `for (i = 0; i < 16; i++) { ... cur->nbr[i] ... }`; the compiler's own strength
reduction made the stepped pointer (`addiu $s0,$s0,4` beside the counter's `sltiu`), and it keeps the loaded
element in the register the indexed form gives it. The cursor form gave the element another register and let the
delay slot of the float compare be filled from the join (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, a 222-instruction
graph search: 190 with the walk, 20 with the indexed loop, exact once the identical `if (x) { S } else { S }` arms
the search had left in it were collapsed too, which `scaffold_strip` does).

Offered only when the meaning is unchanged: the counter was last set to 0 where the loop is reached, the bound is a
positive constant (so the `for` loop's first test always passes like the `do` loop's first pass), the counter is
stepped once by one at the top level of the body and read nowhere else in it, the cursor starts at an identifier the
loop never assigns and steps once by the member array's element size as the body's last statement, every use of the
cursor is a read of element 0 of a member array of the record type the cursor's base points to (or an `M2C_FIELD`
of the cursor), the bound is within the array and nothing after the loop reads the cursor. The `volatile` the cast
carried goes with the cursor: that is a hypothesis about how the original was written, not a statement about the
compiler. `field_cursor_index_strip` is the same child with `scaffold_strip` applied, the combination that matched.
"""
import re

from . import scaffold_strip
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'field_cursor_index'
STRIPPED = 'field_cursor_index_strip'
FAMILIES = (FAMILY, STRIPPED)

ID = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
SCALAR_SIZE = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4,
               'f32': 4, 'float': 4, 'void': 1}
POINTER_SIZE = 4  # (the 32-bit consoles; the step has to equal the declared element's size anyway)
TYPED_USE = r'\(\s*\(\s*(?:volatile\s+)?(?:struct\s+)?({ID})\s*\*\s*\)\s*{cursor}\s*\)\s*->\s*({ID})\s*\[\s*0\s*\]'
FIELD_USE = r'M2C_FIELD\(\s*{cursor}\s*,\s*([^,()]+?)\s*,\s*({number})\s*\)'


def _step(var):
    v = re.escape(var)
    return rf'(?:{v}\s*\+=\s*1|{v}\s*\+\+|\+\+\s*{v}|{v}\s*=\s*{v}\s*\+\s*1)\s*;'


def _size(declaration):
    """Byte size of what a declaration's text declares (`struct SNode *`, `f32`), or None."""
    text = re.sub(r'\b(?:extern|static|const|volatile|struct|register|unsigned)\b', ' ', declaration)
    if '*' in text:
        return POINTER_SIZE
    words = text.split()
    return SCALAR_SIZE.get(words[-1]) if words else None


def _member(text, record, member):
    """(element size, length) of `member[N]` in the struct named or typedef'd `record`, or None."""
    for block in re.finditer(r'(?:typedef\s+)?struct\s*(' + ID + r')?\s*{', text):
        end = close(text, block.end() - 1, '{', '}')
        if not end:
            continue
        alias = re.match(rf'\s*({ID})\s*;', text[end:])
        if record not in (block[1], alias and alias[1]):
            continue
        for field in re.finditer(rf'([^;{{}}]*?)\b{re.escape(member)}\s*\[\s*({NUMBER})\s*\]\s*;', text[block.end():end]):
            size = _size(field[1])
            return (size, int(field[2], 0)) if size else None
    return None


def _literal_step(text):
    found = re.fullmatch(rf'\s*({NUMBER})[uUlL]*\s*', text)
    if found:
        return int(found[1], 0)
    found = re.fullmatch(r'\s*sizeof\s*\(\s*([\w \t*]+?)\s*\)\s*', text)
    return _size(found[1]) if found else None


def _counter_start_is_zero(clean, counter, loop_start):
    """The counter's last assignment before the loop sets 0 in a block that still encloses the loop."""
    last = None
    for hit in re.finditer(rf'(?<![\w.>])({re.escape(counter)})\s*(?:([-+*/|&^]|<<|>>)?=(?!=)|\+\+|--)|(?:\+\+|--)\s*{re.escape(counter)}\b',
                           clean[:loop_start]):
        last = hit
    if not last:
        return False
    if re.match(rf'{re.escape(counter)}\s*=\s*0[uUlL]*\s*[;,]', clean[last.start():]) is None:
        return False
    depth = 0
    for char in clean[last.end():loop_start]:
        depth += (char == '{') - (char == '}')
        if depth < 0:
            return False
    return True


def _variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    types = header + '\n' + source
    out = []
    for do in re.finditer(r'\bdo\s*{', clean[span[0]:span[1]]):
        start = span[0] + do.start()
        opening = span[0] + do.end() - 1
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        tail = re.match(rf'\s*while\s*\(\s*({ID})\s*<\s*\(?\s*({NUMBER}[uUlL]*)\s*\)?\s*\)\s*;', clean[end:span[1]])
        if not tail or int(tail[2].rstrip('uUlL'), 0) < 1:
            continue
        counter, bound, loop_end = tail[1], int(tail[2].rstrip('uUlL'), 0), end + tail.end()
        before = clean[span[0]:start]
        init = re.search(rf'(?:(?:[A-Za-z_][\w \t]*?)\s*\*\s*)?\b({ID})\s*=\s*(?:\(\s*[\w \t]*\*\s*\)\s*)?({ID})\s*;[ \t]*\n?\s*$', before)
        if not init or init[1] in (counter, init[2]):
            continue
        cursor, base = init[1], init[2]
        body = clean[opening + 1:end - 1]
        step = list(re.finditer(rf'\b{re.escape(cursor)}\s*\+=\s*([^;]+?)\s*;\s*$', body))
        if not step:
            continue
        stride = _literal_step(step[0][1])
        count = list(re.finditer(_step(counter), body))
        if not stride or len(count) != 1:
            continue
        inner = body[:step[0].start()]
        counted = inner[:count[0].start()] + ' ' * (count[0].end() - count[0].start()) + inner[count[0].end():]
        if (re.search(r'\b(?:continue|break|goto)\b', inner)
                or re.search(rf'\b{re.escape(counter)}\b', counted)
                or re.search(rf'\b{re.escape(base)}\s*(?:[-+*/|&^]?=(?!=)|\+\+|--)|(?:&|\+\+|--)\s*{re.escape(base)}\b', inner)
                or re.search(rf'\b{re.escape(cursor)}\b', clean[loop_end:span[1]])):
            continue
        if not _counter_start_is_zero(clean, counter, start):
            continue
        replace = []  # (start, end, text) in the source, whole-file offsets
        base_decl = re.search(rf'\b({ID})\s*\*+\s*{re.escape(base)}\b', _blank(types))
        typed = re.compile(TYPED_USE.format(ID=ID, cursor=re.escape(cursor)))
        field = re.compile(FIELD_USE.format(cursor=re.escape(cursor), number=NUMBER))
        for use in typed.finditer(inner):
            record, member = use[1], use[2]
            shape = _member(_blank(types), record, member)
            if not shape or shape[0] != stride or bound > shape[1] or not base_decl or base_decl[1] != record:
                replace = None
                break
            replace.append((opening + 1 + use.start(), opening + 1 + use.end(), f'{base}->{member}[{counter}]'))
        if replace is None:
            continue
        for use in field.finditer(inner):
            offset = f'{use[2]} + {counter} * {stride}'
            replace.append((opening + 1 + use.start(), opening + 1 + use.end(),
                            f'M2C_FIELD({base}, {use[1]}, {offset})'))
        if not replace or len(replace) != len(re.findall(rf'\b{re.escape(cursor)}\b', inner)):
            continue  # (the cursor used any other way than the reads above)
        replace += [(opening + 1 + count[0].start(), opening + 1 + count[0].end(), ''),
                    (opening + 1 + step[0].start(), opening + 1 + step[0].end(), '')]
        pieces = sorted(replace, reverse=True)
        body_src = source[opening + 1:end - 1]
        for lo, hi, new in pieces:
            body_src = body_src[:lo - opening - 1] + new + body_src[hi - opening - 1:]
        body_src = re.sub(r'\n[ \t]*\n', '\n', body_src)
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:]).group()
        loop = f'for ({counter} = 0; {counter} < {tail[2]}; {counter}++) {{{body_src.rstrip()}\n{indent}}}'
        init_start = span[0] + init.start()
        declaration = re.match(r'(?:[A-Za-z_][\w \t]*?)\s*\*', clean[init_start:])
        result = source[:init_start] + loop + source[loop_end:]
        if not declaration:  # (the cursor was declared elsewhere: drop the declaration when nothing names it now)
            gone = re.sub(rf'(?m)^[ \t]*[A-Za-z_][\w \t]*?\s*\*\s*{re.escape(cursor)}\s*;[ \t]*\n', '', result, count=1)
            if gone != result and len(re.findall(rf'\b{re.escape(cursor)}\b', _blank(gone))) == 0:
                result = gone
        out.append((FAMILY, result))
    return out


def variants(source, name, header=''):
    found = _variants(source, name, header)
    result = list(found)
    for _, text in found:
        plain = scaffold_strip.strip(text, name, header)
        if plain and plain != text:
            result.append((STRIPPED, plain))
    return result[:6]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 97}
