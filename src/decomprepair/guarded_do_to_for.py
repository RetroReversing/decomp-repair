"""A guarded `do { } while` counted loop, written as the `for` the compiler was given (GCC 2.7.2, KMC, N64).

    if (n > 0) { i = 0; do { BODY i += 1; } while (i < n); }

is how m2c (and the saved bests built on it) spell a loop the game wrote as `for (i = 0; i < n; i++) { BODY }`. The two
compile to the same loop, but not to the same frame: jump.c copies a `for`'s test in front of the loop *before* cse and
the copy leaves stale pseudos that reload gives frame slots, so a function whose counted loop was a `for` has a frame 8
bytes larger than the one with the explicit guard, and every stack row after the prologue differs (a 417-instruction
input handler, 840 -> 770: the frame, the loop counter's register order and the spill slots all matched once the loop
was the `for`; before it the only rows left were stack offsets).

Offered for `if (BOUND > 0) { [declarations] C = 0; do { BODY C += 1; } while (C < BOUND); }` (also `0 < BOUND`, and
`C++;` or `++C;` for the step) when the body has no `continue` (the `for` step would then run where the `do`'s did
not). The `if` goes with its braces; the declarations stay. A candidate rewrite; the exact judge decides.

The counter's `C = 0;` may also be the statement just before the `if`, and the guard's bound may differ from the loop's
by `(s32)`/`(int)` casts (a search's spelling). A 392-instruction object initialiser had both loops written that way, and
its frame was 16 bytes short until both were `for` loops (22 -> 0 with the next child; 8 bytes per loop). Its second
bound read a halfword through a cast helper (`inline static u32 f(s16 a) { return (u32) a; }`), and a `for` whose
bound calls a helper keeps its test at the bottom: a second child writes the helper's call as its casts and an
unsigned bound's `>> k` as `/ 2^k` (the `>> 2` spelling made gcc combine a `sra` the target does not have: 1020 vs 0).
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'guarded_do_to_for'
FAMILIES = (FAMILY,)
_IF = re.compile(r'\bif\s*\(')
_SHAPE = re.compile(
    rf'\A(?P<pre>(?:\s*[A-Za-z_][\w \t*]*;)*)\s*(?P<c>{IDENT})\s*=\s*0\s*;\s*do\s*\{{(?P<body>.*)\}}\s*'
    rf'while\s*\(\s*(?P=c)\s*<\s*(?P<bound>[^;]+?)\s*\)\s*;\s*\Z', re.S)
_BARE = re.compile(
    rf'\A(?P<pre>(?:\s*[A-Za-z_][\w \t*]*;)*)\s*do\s*\{{(?P<body>.*)\}}\s*'
    rf'while\s*\(\s*(?P<c>{IDENT})\s*<\s*(?P<bound>[^;]+?)\s*\)\s*;\s*\Z', re.S)
_WIDE_CAST = re.compile(r'\(\s*(?:s32|int|signed(?:\s+int)?)\s*\)')
_CAST_HELPER = re.compile(rf'\binline\s+static\s+(?P<ret>[\w \t]+?)\s+(?P<name>{IDENT})\s*\(\s*(?P<ptype>[\w \t]+?)\s+'
                          rf'(?P<arg>{IDENT})\s*\)\s*\{{\s*return\s*\(\s*(?P=ret)\s*\)\s*(?P=arg)\s*;\s*\}}')


def _plain(text):
    """The operand with spacing and one layer of outer parentheses ignored."""
    text = re.sub(r'\s+', '', text)
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1]
    return text


def _loose(text):
    """The operand compared modulo `(s32)`/`(int)` casts, spacing and outer parentheses."""
    return _plain(_WIDE_CAST.sub('', text))


def _call_end(text, opening):
    depth = 0
    for i in range(opening, len(text)):
        depth += {'(': 1, ')': -1}.get(text[i], 0)
        if depth == 0:
            return i
    return -1


def _expanded(bound, helpers):
    """The bound with each cast helper's call written as its casts and an unsigned `>> k` as `/ 2^k`, or None."""
    changed, text = False, bound
    for name, (ret, ptype) in helpers.items():
        while True:
            hit = re.search(rf'\b{re.escape(name)}\s*\(', text)
            if not hit:
                break
            end = _call_end(text, hit.end() - 1)
            if end < 0:
                return None
            text = text[:hit.start()] + f'(({ret}) ({ptype}) ({text[hit.end():end].strip()}))' + text[end + 1:]
            changed = True
    shifted = re.sub(r'\)\s*>>\s*([1-9])\b', lambda m: f') / {1 << int(m[1])}', text)
    if shifted != text and re.search(r'\(\s*(?:u32|unsigned(?:\s+int)?)\s*\)', text):
        text, changed = shifted, True
    return text if changed else None


def _guarded_bound(cond):
    """BOUND of `BOUND > 0` or `0 < BOUND`, else None."""
    cond = cond.strip()
    for pattern in (r'(?P<b>.+?)\s*>\s*0', r'0\s*<\s*(?P<b>.+)'):
        hit = re.fullmatch(pattern, cond, re.S)
        if hit:
            return hit['b']
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    helpers = {m['name']: (re.sub(r'\s+', ' ', m['ret']), re.sub(r'\s+', ' ', m['ptype']))
               for m in _CAST_HELPER.finditer(clean)}
    sites = []
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1)
        if not shut:
            continue
        bound = _guarded_bound(clean[hit.end():shut - 1])
        block = re.match(r'\s*\{', clean[shut:])
        if bound is None or not block:
            continue
        open_at = shut + block.end() - 1
        end = close(clean, open_at, '{', '}')
        if not end or re.match(r'\s*else\b', clean[end:]):
            continue
        inside = clean[open_at + 1:end - 1]
        shape, start = _SHAPE.match(inside), hit.start()
        if not shape:
            shape = _BARE.match(inside)
            before = shape and re.search(rf'(?m)^[ \t]*{re.escape(shape["c"])}[ \t]*=[ \t]*0[ \t]*;[ \t]*\n[ \t]*\Z',
                                         clean[part.opening + 1:hit.start()])
            if not before or re.search(rf'\b{re.escape(shape["c"])}\b', bound):
                continue
            start = part.opening + 1 + before.start()
        if _plain(shape['bound']) != _plain(bound) and _loose(shape['bound']) != _loose(bound):
            continue
        counter = shape['c']
        body_at = open_at + 1 + shape.start('body')
        body = clean[body_at:open_at + 1 + shape.end('body')]
        # the step is the body's last statement
        tail = re.search(rf'(?:{IDENT}\s*\+=\s*1|{IDENT}\s*\+\+|\+\+\s*{IDENT})\s*;\s*\Z', body)
        if not tail or counter not in tail[0] or re.search(r'\bcontinue\b', body):
            continue
        main = source[body_at:body_at + tail.start()].rstrip()
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, hit.start()) + 1:])[0]
        pre = source[open_at + 1:open_at + 1 + shape.end('pre')].strip('\n')
        loop_bound = source[open_at + 1 + shape.start('bound'):open_at + 1 + shape.end('bound')]
        bound_text = (source[hit.end() + clean[hit.end():shut - 1].index(bound):][:len(bound)]
                      if _plain(shape['bound']) == _plain(bound) else loop_bound)
        bounds = [bound_text]
        expanded = _expanded(loop_bound, helpers)
        if expanded:
            bounds.append(expanded)
        texts = []
        for text in bounds:
            loop = (f'{indent}  for ({counter} = 0; {counter} < {text}; {counter}++)\n{indent}  {{'
                    f'{main}\n{indent}  }}')
            body_text = f'{{\n{pre}\n{loop}\n{indent}}}' if pre.strip() else f'{{\n{loop}\n{indent}}}'
            if start != hit.start():
                body_text = indent + body_text
            texts.append(body_text)
            out.append((FAMILY, edit(source, [(start, end, body_text)])))
        sites.append((start, end, texts))
    # every loop at once: each `for` leaves its own stale frame slot, so a frame several slots short moves only
    # when all of them change (the object initialiser above: 22 -> 22 for each alone, 22 -> 0 together)
    sites = [site for i, site in enumerate(sites) if all(site[0] >= other[1] or site[1] <= other[0]
                                                         for other in sites[:i])]
    if len(sites) > 1:
        out.append((FAMILY, edit(source, [(a, b, texts[0]) for a, b, texts in sites])))
        if any(len(texts) > 1 for _, _, texts in sites):
            out.append((FAMILY, edit(source, [(a, b, texts[-1]) for a, b, texts in sites])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
