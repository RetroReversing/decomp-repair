"""m2c's own spelling written as the plain C the families read, value for value.

A measurement of draft cleanups on 90 m2c drafts of an N64 game (decompdecomp's
docs/learnings/finding/draft-cleanup-measurement.md) found that most families never fired on a raw draft: they read
`*(T *)((u8 *)p + K)` and `s32`, while m2c writes `M2C_FIELD(p, T *, K)` and `M2C_UNK`. Expanding just those two
spellings in the same 90 drafts made ~60 more family runs produce a candidate (the indexed captures 0 -> 22 drafts,
the captured hypotheses 3 -> 22, the temporary hoists 57 -> 78), so callers that run families on m2c drafts run them
on `plain(draft)` too.

Both rewrites are what the preprocessor does itself, so the compiled function is the same:
- `M2C_FIELD(e, T *, off)` is the draft's own `#define M2C_FIELD(expr, type_ptr, offset)
  (*(type_ptr)((s8 *)(expr) + (offset)))`, written out (innermost first), with the brackets a simple name or
  number does not need left out. Only when the draft defines the macro exactly so.
- A frame view: `#define sp30 locals.sp30` inside a function, over a local struct that holds the stack slots the draft
  names (`struct { s32 sp30; ... } locals;`), is written out as `locals.sp30` and the `#define` dropped. A `#` line in the
  function's own text sends decompdecomp's proposal path down its macro-masking route, which cuts off after 120 s on a
  long function and leaves the registry's ~700 families (`call_weight_ladder`, `word_block_copy`, ...) unrun, so a saved
  best that carries nine of those lines had 17 families' children before and a hundred after (a 874-instruction KMC N64
  spawner; the names stay readable: the member is still `locals.sp30`).
- `M2C_UNK`, `M2C_UNK8`, `M2C_UNK16`, `M2C_UNK32` are the draft's typedefs of `s32`, `s8`, `s16`, `s32`, written as
  those types outside the macro block, again only when the draft declares them so.
The macro block itself stays: `M2C_BITWISE`, `M2C_ERROR` and the rest keep their definitions.
"""
import re

from .m2cfix import _closing, _split_top_level

_BLOCK = re.compile(r'#ifndef M2C_DEFINES\n.*?#endif\n?', re.S)
_FIELD = re.compile(r'^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s+'
                    r'\(\*\(type_ptr\)\(\(s8 \*\)\(expr\) \+ \(offset\)\)\)\s*$', re.M)
_TYPEDEFS = {'M2C_UNK': 's32', 'M2C_UNK8': 's8', 'M2C_UNK16': 's16', 'M2C_UNK32': 's32'}
# An operand that needs no brackets after a cast: a name, a member chain, `&name` or a number.
_SIMPLE = re.compile(r'&?[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*|0x[0-9A-Fa-f]+|\d+|-?0x[0-9A-Fa-f]+|-?\d+')
_NUMBER = re.compile(r'0x[0-9A-Fa-f]+|\d+')


def _bare(text: str, pattern) -> str:
    if pattern.fullmatch(text) or (text.startswith('(') and _closing(text, 1) == len(text)):
        return text
    return f'({text})'


def _expand_fields(body: str) -> str:
    """Every `M2C_FIELD(...)` in `body` as its macro's text, innermost (last) first so arguments are plain."""
    stop = len(body)
    while (i := body.rfind('M2C_FIELD(', 0, stop)) >= 0:
        if i and (body[i - 1].isalnum() or body[i - 1] == '_'):
            stop = i
            continue
        start = i + len('M2C_FIELD(')
        end = _closing(body, start)
        args = [a.strip() for a in _split_top_level(body[start:end - 1])]
        if end > len(body) or len(args) != 3 or not all(args):
            stop = i
            continue
        base, ctype, offset = args
        body = f'{body[:i]}(*({ctype})((s8 *){_bare(base, _SIMPLE)} + {_bare(offset, _NUMBER)})){body[end:]}'
        stop = i
    return body


_SLOT = re.compile(r'^[ \t]*#[ \t]*define[ \t]+(?P<name>[A-Za-z_]\w*)[ \t]+(?P<base>[A-Za-z_]\w*)\.(?P<field>[A-Za-z_]\w*)[ \t]*\n',
                   re.M)


def frame_slots(source: str) -> str:
    """`source` with each function-local `#define NAME base.member` written out where `base` is a local struct the text
    declares (`} base;` or `struct T base;`) and NAME is defined once and never undefined; unchanged otherwise."""
    for hit in list(_SLOT.finditer(source))[::-1]:
        name, base = hit['name'], hit['base']
        before, after = source[:hit.start()], source[hit.end():]
        inside = before.count('{') > before.count('}')
        declared = re.search(rf'}}\s*{re.escape(base)}\s*;|\b(?:struct|union)\s+\w+\s+{re.escape(base)}\s*;', before)
        redefined = re.search(rf'^[ \t]*#[ \t]*(?:define|undef)[ \t]+{re.escape(name)}\b', before + after, re.M)
        if not inside or not declared or redefined:
            continue
        after = re.sub(rf'(?<![\w.>]){re.escape(name)}\b', f"{base}.{hit['field']}", after)
        source = before + after
    return source


def plain(source: str) -> str:
    """`source` with m2c's field accesses and unknown types written as the C they stand for; unchanged when the
    draft does not define them the way m2c does."""
    source = frame_slots(source)
    block = _BLOCK.search(source)
    if not block:
        return source
    head, defines, tail = source[:block.start()], block.group(0), source[block.end():]
    if 'M2C_FIELD(' in tail and _FIELD.search(defines):
        tail = _expand_fields(tail)
    for macro, ctype in _TYPEDEFS.items():
        if re.search(rf'^\s*typedef\s+{ctype}\s+{macro}\s*;', defines, re.M):
            tail = re.sub(rf'\b{macro}\b', ctype, tail)
    return head + defines + tail


def variants(source: str, name: str) -> list[tuple[str, str]]:
    """The draft in plain spelling as one candidate (`m2c_spelling`), when it has any of m2c's own."""
    text = plain(source)
    return [('m2c_spelling', text)] if text != source else []
