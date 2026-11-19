"""Changes the permuter's bugs left in saved C, taken out again.

Two of the random rewrites changed what the C means and were kept because the byte score went up:
- `_toggle_register` declared `register D_80102ED4 = 0;`, a new local where the C stored to a global (0.5.11);
- `_add_cast` cut a pointer to 16 bits inside a pointer cast, `(char *)((unsigned short)D_80109698) + 0xFC`, and cast
  type names, `((unsigned)char *)` (0.5.16).
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
UNTYPED_REGISTER = re.compile(r'(?<![\w.])register\s+(?=[A-Za-z_]\w*\s*=(?!=))')


def clean(source: str | None) -> str | None:
    if not source:
        return None
    text = POINTER_CUT.sub(lambda m: f'{m[1]}{m[2]})', source)
    text = TYPE_CAST.sub(lambda m: f'{m[1]}{m[2]}', text)
    text = UNTYPED_REGISTER.sub('', text)
    return text if text != source else None
