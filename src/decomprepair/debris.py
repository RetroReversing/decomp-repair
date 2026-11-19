"""Changes the permuter's bugs left in saved C, taken out again.

Two of the random rewrites changed what the C means and were kept because the byte score went up:
- `_toggle_register` declared `register D_80102ED4 = 0;`, a new local where the C stored to a global (0.5.11);
- `_add_cast` cut a pointer to 16 bits inside a pointer cast, `(char *)((unsigned short)D_80109698) + 0xFC`, and cast
  type names, `((unsigned)char *)` (0.5.16), and narrowed hex literals, `(unsigned short)0xDA380003` storing 3 where an
  N64 function stored a display-list command (0.5.16), and `(unsigned short)` on a variable in arithmetic (0.5.19).
Neither is C anyone wrote, and every correct candidate scores worse than C holding them, so a search that starts from
such a best never improves it again. `clean` gives the C without them (or None when there is nothing to take out); the
caller judges it and keeps its real score, as decompdecomp's deep pass does for the `register` case.
"""
import re

INTEGER_CASTS = r'(?:unsigned\s+short|unsigned\s+char|unsigned|short|int|s32|u32|s16|u16|s8|u8|uInt|uLong)'
# an integer cast written onto a pointer cast's operand: `*)((unsigned short)X)` and `*)(unsigned short)X`
POINTER_CUT = re.compile(r'(\*\s*\)\s*\(\s*)\(\s*' + INTEGER_CASTS + r'\s*\)\s*([A-Za-z_]\w*)\s*\)')
# a cast written onto a type name: `((unsigned)char *)`
TYPE_CAST = re.compile(r'\(\s*' + INTEGER_CASTS + r'\s*\)\s*(char|short|int|long|void|float|double|s8|u8|s16|u16|s32|u32|f32)'
                       r'(\s*\*)')
# a 16-bit cast the permuter put on a variable that is an operand of arithmetic: m2c writes s16/u16, never these
# spellings, and `(unsigned short)flags | 1` kept only the low half of a word the game ORed whole (0.5.19)
VARIABLE_CUT = re.compile(r'\(\s*(?:unsigned\s+short|short)\s*\)\s*(?=[A-Za-z_]\w*\s*(?:[|&^+\-*/%]|<<|>>)(?!=))')
# a narrowing cast on a hex literal that doesn't fit the type (nobody writes `(u16)0xDA380003` for 3)
LITERAL_CAST = re.compile(r'\(\s*(unsigned\s+short|unsigned\s+char|short|s16|u16|s8|u8)\s*\)\s*(0[xX][0-9a-fA-F]+)[uU]?\b')
WIDTH = {'unsigned short': 0xFFFF, 'short': 0xFFFF, 's16': 0xFFFF, 'u16': 0xFFFF, 'unsigned char': 0xFF, 's8': 0xFF,
         'u8': 0xFF}
# value_repairs' pointer split, `q = (char *)(b); q += (s32)(K);`: one sum written as two (0.5.16 stopped it adding K
# times the element size; the split left in saved C still keeps gcc from treating `q` as `b`'s field address)
POINTER_SPLIT = re.compile(r'(?P<q>[A-Za-z_]\w*)\s*=\s*\(\s*char\s*\*\s*\)\s*\((?P<b>[^;()]*)\)\s*;\s*'
                           r'(?P=q)\s*\+=\s*\(\s*s32\s*\)\s*\((?P<k>[^;()]*)\)\s*;')
UNTYPED_REGISTER = re.compile(r'(?<![\w.])register\s+(?=[A-Za-z_]\w*\s*=(?!=))')


STATEMENT = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<lhs>[A-Za-z_]\w*)\s*=(?!=)(?P<rhs>[^;{}]*);[ \t]*\n')


def _read_before_set(text):
    """A statement that reads a local in the line just before the local's first assignment, swapped back (a random
    statement swap left `t = *(f32 *)((char *)(p) + 0x7C); p = D[i];` in an N64 function's best, reading `p` unset,
    which scored better than the C the game had)."""
    for first in STATEMENT.finditer(text):
        second = STATEMENT.match(text, first.end())
        if not second or second['indent'] != first['indent']:
            continue
        var = second['lhs']
        if var == first['lhs'] or not re.search(r'(?<![\w.>])' + var + r'\b', first['rhs']):
            continue
        # (a local: declared in this function's body, the last unindented line opening a block before it)
        heads = list(re.finditer(r'(?m)^\S[^\n]*\{[ \t]*$', text[:first.start()]))
        body = heads[-1].end() if heads else 0
        before = list(re.finditer(r'(?<![\w.>])' + var + r'\b', text[:first.start()]))
        # (nor one a call may have set through an address: `g(&sp38)` fills sp38..sp40)
        if len(before) != 1 or before[0].start() < body or re.search(r'&\s*[A-Za-z_]', text[body:first.start()]):
            continue
        line = text[text.rfind('\n', 0, before[0].start()) + 1:text.find('\n', before[0].start())]
        if not re.fullmatch(r'[ \t]*[A-Za-z_][\w ]*?[\s*]+' + var + r'\s*;[ \t]*', line):
            continue
        return text[:first.start()] + second.group(0) + first.group(0) + text[second.end():]
    return text


def clean(source: str | None) -> str | None:
    if not source:
        return None
    text = POINTER_CUT.sub(lambda m: f'{m[1]}{m[2]})', source)
    text = TYPE_CAST.sub(lambda m: f'{m[1]}{m[2]}', text)
    text = UNTYPED_REGISTER.sub('', text)
    text = _read_before_set(text)
    text = POINTER_SPLIT.sub(lambda m: f"{m['q']} = (char *)({m['b']}) + {m['k']};", text)
    text = VARIABLE_CUT.sub('', text)
    text = LITERAL_CAST.sub(lambda m: m[0] if int(m[2], 16) <= WIDTH[' '.join(m[1].split())] else m[2], text)
    return text if text != source else None
