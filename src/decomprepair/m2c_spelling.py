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


def plain(source: str) -> str:
    """`source` with m2c's field accesses and unknown types written as the C they stand for; unchanged when the
    draft does not define them the way m2c does."""
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
