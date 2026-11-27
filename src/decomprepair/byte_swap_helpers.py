"""Byte swaps m2c spelled out, written as the small inline helpers that made them.

A loader for little-endian files on a big-endian machine swaps its words and halfwords through helpers the compiler
inlines, and m2c writes the expanded shifts and masks back with a temporary for the upper half. GCC then folds the two
shifts of the upper half into one `>> 24`, which no spelling of the expanded form fully undoes. This writes
`static __inline__` helpers instead: a `u16` parameter for the halfword swap (so each half of the word is converted to
a halfword of its own, as the target's `srl 16` shows) and a word swap built from two calls of it.

byte_swap_inline_helpers
    Every expanded word swap becomes `repair_swap32(x)` and every expanded halfword swap `repair_swap16(v)`; an upper
    half temporary and a halfword temporary that only fed a swap are folded into the call. The word swap returns its two
    halves summed in one expression.

byte_swap_inline_helpers_staged
    The same, with the word swap's shifted upper half named in a local before the lower half is swapped, so the shift
    stays ahead of the second swap.

shared_quotient_word
    Two or more statements `A = (s32) (X) / K;` with the same constant and a swapped or computed `X` load one local
    first: `word = X; A = word / K;`. A value read once per section and divided keeps its own register that way.

byte_swap_helpers_quotient
    The staged helpers and the shared dividend together.

Measured on one match, a Nintendo 64 image-header parser (100 instructions, `sn-n64-281 -G0 -mips3 -O2 -mgas
-mcpu=VR4300`): helpers instead of the expanded form 3405 -> 1870 on the hand-written rewrite, the named upper half
1100 -> 920, and the shared dividend 310 -> 0. Why the compiler wants them is a hypothesis from that one function. The
helpers are what a developer would write; the exact judge decides every child.
"""
import re

from .c_scan import close
from .integer_repair_support import IDENT, edit, view

PLAIN = 'byte_swap_inline_helpers'
STAGED = 'byte_swap_inline_helpers_staged'
QUOTIENT = 'shared_quotient_word'
BOTH = 'byte_swap_helpers_quotient'
FAMILIES = (PLAIN, STAGED, QUOTIENT, BOTH)

SWAP16 = 'repair_swap16'
SWAP32 = 'repair_swap32'
WORD = 'repair_word'

_CAST = r'(?:\(u32\)\s*)?'
_LOW = (rf'\(\(\((?P<x>{IDENT}) & 0xFF\) << 8\) \+ '
        rf'{_CAST}\({_CAST}\((?P=x) & 0xFF00\) >> 8\)\)')
_HIGH = rf'\({_LOW} << (?:0x10|16)\) \+ '
_WORDS = (
    re.compile(_HIGH + rf'\(\(\((?P<t>{IDENT}) & 0xFF\) << 8\) \+ \((?P=t) >> 8\)\)'),
    re.compile(_HIGH + r'\(\(\(\((?P=x) >> (?:0x10|16)\) & 0xFF\) << 8\) \+ '
               r'\(\(\((?P=x) >> (?:0x10|16)\) & 0xFF00\) >> 8\)\)'),
)
_HALF = re.compile(rf'\(\(\((?P<v>{IDENT}) & 0xFF\) << 8\) \+ \((?P=v) >> 8\)\)')
_TYPE = r'(?:u32|s32|u16|s16|unsigned\s+int|unsigned\s+short|unsigned|int)'

_HELPERS = {
    SWAP16: (f'static __inline__ u32 {SWAP16}(u16 v) {{\n'
             f'    return ((v & 0xFF) << 8) + ((v & 0xFF00) >> 8);\n}}\n'),
    PLAIN: (f'static __inline__ u32 {SWAP32}(u32 v) {{\n'
            f'    return ({SWAP16}(v) << 16) + {SWAP16}(v >> 16);\n}}\n'),
    STAGED: (f'static __inline__ u32 {SWAP32}(u32 v) {{\n'
             f'    u32 high;\n\n    high = {SWAP16}(v) << 16;\n'
             f'    return high + {SWAP16}(v >> 16);\n}}\n'),
}


def _count(text, name):
    return len(re.findall(rf'(?<![\w.>]){re.escape(name)}\b', text))


def _declared(body, name):
    found = list(re.finditer(rf'(?m)^[ \t]*(?P<type>{_TYPE})\s+{re.escape(name)};[ \t]*\n', body))
    return found[0] if len(found) == 1 else None


def _drop_declaration(body, name):
    found = _declared(body, name)
    if found and _count(body, name) == 1:
        return body[:found.start()] + body[found.end():]
    return body


def _words(body):
    """Every expanded word swap as a call; the upper half's temporary goes with it."""
    for _ in range(64):  # offsets move with every edit, so each pass takes one site
        hit = min((m for m in (p.search(body) for p in _WORDS) if m), key=lambda m: m.start(), default=None)
        if not hit:
            break
        x, temp = hit['x'], hit.groupdict().get('t')
        word = _declared(body, x)
        call = f'{SWAP32}({x})'
        if temp:
            # The setter is the nearest assignment above the use; it must read the same word.
            setters = [m for m in re.finditer(
                rf'(?m)^[ \t]*{re.escape(temp)} = (?:\(u32\) )?(?P<of>{IDENT}) >> (?:0x10|16);[ \t]*\n', body)
                if m.end() <= hit.start()]
            declared = _declared(body, temp)
            # A signed word or half would shift its sign in, and a word written in between would not be the same one.
            if (not setters or setters[-1]['of'] != x or not declared or declared['type'] != 'u32'
                    or not word or word['type'] != 'u32' or _count(body[setters[-1].end():], temp) != 2
                    or re.search(rf'(?<![\w.>]){re.escape(x)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)',
                                 body[setters[-1].end():hit.start()])):
                return None
            setter = setters[-1]
            body = body[:setter.start()] + body[setter.end():hit.start()] + call + body[hit.end():]
            body = _drop_declaration(body, temp)
        else:
            body = body[:hit.start()] + call + body[hit.end():]
    return body


def _halves(body):
    """Every expanded halfword swap of a `u16` local as a call; a local read from memory only for it is folded in."""
    start = 0
    for _ in range(64):
        hit = _HALF.search(body, start)
        if not hit:
            break
        v = hit['v']
        declared = _declared(body, v)
        whole = (re.search(r'(?<![=!<>+\-*/%&|^])= (?:\((?:u16|s16)\) )?$', body[:hit.start()])
                 and body.startswith(';', hit.end()))  # elsewhere the unsigned result could change the arithmetic
        if not whole or not declared or declared['type'] not in ('u16', 'unsigned short'):
            start = hit.end()
            continue
        call = f'{SWAP16}({v})'
        # `v = READ; WRITE = (u16) SWAP(v);` as neighbours, with no other use of v
        setter = re.search(rf'(?m)^[ \t]*{re.escape(v)} = (?P<read>[^;\n]+);[ \t]*\n(?=[^\n]*$)',
                           body[:body.rfind('\n', 0, hit.start()) + 1])
        if setter and _count(body, v) == 4:
            line = body[setter.end():hit.start()]
            tail = body[hit.end():]
            body = body[:setter.start()] + line + f'{SWAP16}({setter["read"]})' + tail
            body = _drop_declaration(body, v)
        else:
            body = body[:hit.start()] + call + body[hit.end():]
    return body


def _helpers(source, name, staged):
    part = view(source, name)
    if not part or re.search(rf'\b(?:{SWAP16}|{SWAP32}|asm|__asm__|volatile)\b', part.clean):
        return None
    low, high = part.opening + 1, part.end - 1
    body = _words(source[low:high])
    if body is None:
        return None
    body = _halves(body)
    if body == source[low:high]:
        return None
    word = f'{SWAP32}(' in body
    definitions = _HELPERS[SWAP16] + (_HELPERS[STAGED if staged else PLAIN] if word else '')
    head = list(re.finditer(rf'(?m)^(?=[^\n#]*\b{re.escape(name)}\s*\()', source[:low]))
    if not head or (staged and not word):
        return None
    at = head[-1].start()
    return edit(source, [(at, at, definitions), (low, high, body)])


def _one_term(text):
    """Whether `text` is one bracketed expression or one call, nothing outside its outermost brackets."""
    opening = text.find('(')
    return (opening >= 0 and re.fullmatch(rf'(?:{IDENT})?', text[:opening]) is not None
            and close(text, opening, '(', ')') == len(text) - 1)


def _quotient(source, name):
    part = view(source, name)
    if not part or re.search(rf'\b(?:{WORD}|asm|__asm__|volatile)\b', part.clean):
        return None
    low, high = part.opening + 1, part.end - 1
    body = source[low:high]
    # `A = (s32) X / K;`, or m2c's `A = (s32) ((s32) X / K);`: only a signed dividend keeps its meaning in an s32 local
    lines = re.finditer(r'(?m)^(?P<indent>[ \t]*)(?P<left>[^=;\n{}]+?) = (?P<wrap>\(s32\) \()?\(s32\) (?P<value>[^;\n]+?)'
                        r' / (?P<k>2|4|8|16|32)(?(wrap)\));[ \t]*$', body)
    signed = [hit for hit in lines if _one_term(hit['value'])]
    if len(signed) < 2 or len({hit['k'] for hit in signed}) != 1:
        return None
    changes = [(low + hit.start(), low + hit.end(),
                f'{hit["indent"]}{WORD} = {hit["value"]};\n{hit["indent"]}{hit["left"]} = {WORD} / {hit["k"]};')
               for hit in signed]
    return edit(source, [(low, low, f'\n    s32 {WORD};'), *changes])


def variants(source, name, header=''):
    if len(source) > 128000:
        return []
    out, seen = [], {source}

    def offer(family, text):
        if text is not None and text not in seen:
            seen.add(text)
            out.append((family, text))

    staged = None
    if '0xFF00' in source or '& 0xFF) << 8' in source:
        staged = _helpers(source, name, True)
        combined = _quotient(staged, name) if staged else None
        offer(BOTH, combined)
        offer(STAGED, staged)
        offer(PLAIN, _helpers(source, name, False))
    offer(QUOTIENT, _quotient(source, name))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
