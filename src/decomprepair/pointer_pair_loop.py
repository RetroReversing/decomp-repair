"""A search loop m2c wrote with two stepped pointers and a `goto`, written as the one-pointer `do`/`while` it came from.

m2c writes a record scan as

    base = first; mark = base + 2; key = *(u16 *)base;          (a second pointer into the same record)
    again:
    if (key == wanted) { ...match, reading mark + 2, writing mark + 6...; base += 8; use(base); (*(u16 *)mark)++; }
    else { base += 0x1c; key = *(u16 *)base; mark += 0x1c; if (key != 0xffff) goto again; }

A game wrote `p->count`, `p->offset`, `p->addr` through one pointer and let the compiler find the second one. Three
facts decided a KMC gcc 2.7.2 function's rows (165 -> 100, the last row being a sentinel `andi` no spelling reached):

1. `goto_match_break_loop`: the backward `goto` is `do { if (c) { A break; } B } while (d);` (loop.c then treats it as
   a loop: it hoists the sentinel constant out of the loop where the goto form reloads it every pass);
2. `derived_pointer_fold`: the second pointer is dropped, its reads and writes made `base + k`, and the match arm's
   `base += 8` sunk into the uses after it (`use(base + 8)`), so the loop pass reduces the field addresses itself
   (one `$s0 = base + 2` that steps with the base, which is the target's pair of registers) where the explicit second
   pointer plus an arm that moved `base` made it derive a different one;
3. `sentinel_halfword_local`: a `u32` local only ever loaded with `*(u16 *)` and tested as `(u16)key != 0xffff` is a
   `u16` local (the cast goes), which keeps the sentinel test's `andi` the target has.
Each step alone is neutral or worse; the whole set is one child here with the shorter combinations as stepping stones.
The reasons are hypotheses read from the output (cc1 -dr/-dc dumps), not from compiler source.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'pointer_pair_loop'
FAMILIES = (FAMILY, 'goto_match_break_loop', 'derived_pointer_fold', 'sentinel_halfword_local')

PLAIN = re.compile(r'\b(?:goto|break|continue|return|switch|do|while|for|case|default|volatile|asm|__asm__)\b|^\s*#',
                   re.M)
LABEL = re.compile(rf'(?<![\w.:?])({IDENT})\s*:(?![:=])')


def _python_span(clean, at, open_char, close_char):
    """The index just past the balanced group whose opener is at `at`, or None."""
    depth = 0
    for index in range(at, len(clean)):
        depth += (clean[index] == open_char) - (clean[index] == close_char)
        if depth == 0:
            return index+1
    return None


_span = _python_span
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _span(clean, at, open_char, close_char):
        found = _scan.close_every(clean, at, open_char, close_char, True, None)
        return _python_span(clean, at, open_char, close_char) if found is NotImplemented else found


def _number(text):
    return int(re.sub(r'[uUlL]+$', '', text), 0)


class _Loop:
    """The one `label: if (c) { A } else { B; if (d) goto label; }` that ends its block, as offsets in the source."""

    def __init__(self, part):
        self.part = part
        clean = part.clean
        found = None
        for label in LABEL.finditer(clean, part.opening, part.end):
            name = label[1]
            if name in ('default', 'case') or len(re.findall(rf'\bgoto\s+{name}\s*;', clean[part.opening:part.end])) != 1:
                continue
            head = re.compile(r'\s*if\s*\(').match(clean, label.end())
            if not head:
                continue
            cond_end = _span(clean, head.end()-1, '(', ')')
            then = re.compile(r'\s*\{').match(clean, cond_end) if cond_end else None
            then_end = _span(clean, then.end()-1, '{', '}') if then else None
            other = re.compile(r'\s*else\s*\{').match(clean, then_end) if then_end else None
            other_end = _span(clean, other.end()-1, '{', '}') if other else None
            tail = re.compile(r'\s*\}').match(clean, other_end) if other_end else None
            closing = re.search(rf'\bif\s*\(([^;{{}}]*)\)\s*goto\s+{name}\s*;\s*$', clean[other.end():other_end-1]) \
                if other_end else None
            if not tail or not closing:
                continue
            at = other.end()
            self.start, self.end = label.start(), other_end
            self.cond = (head.end(), cond_end-1)
            self.then = (then.end(), then_end-1)
            self.rest = (at, at+closing.start())
            self.goto = (at+closing.start(), other_end-1)
            self.d = (at+closing.start(1), at+closing.end(1))
            self.label = name
            found = True
            break
        self.ok = bool(found) and not PLAIN.search(clean[self.then[0]:self.then[1]]) \
            and not PLAIN.search(clean[self.rest[0]:self.rest[1]]) \
            and not LABEL.search(clean[self.then[0]:self.then[1]]) and not LABEL.search(clean[self.rest[0]:self.rest[1]]) \
            if found else False

    def text(self, span):
        return self.part.source[span[0]:span[1]]

    def clean(self, span):
        return self.part.clean[span[0]:span[1]]


def _written(name, text):
    return re.search(rf'\b{name}\s*(?:=(?!=)|[-+*/%&|^]=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*{name}\b|&\s*{name}\b', text)


def _pair(loop):
    """(base, mark, step, offset): two pointers stepped alike in the loop's else arm, the mark made from the base."""
    part = loop.part
    steps = {}
    for step in re.finditer(rf'\b({IDENT})\s*\+=\s*({NUMBER})\s*;', loop.clean(loop.rest)):
        steps.setdefault(_number(step[2]), []).append(step[1])
    before = part.clean[part.opening:loop.start]
    for amount, names in steps.items():
        for mark in names:
            for base in names:
                if base == mark or names.count(mark) != 1 or names.count(base) != 1:
                    continue
                init = list(re.finditer(rf'\b{mark}\s*=\s*{base}\s*\+\s*({NUMBER})\s*;', before))
                every = list(re.finditer(rf'\b{mark}\s*=(?!=)', part.clean[part.opening:part.end]))
                after = part.clean[loop.end:part.end]
                if (len(init) == 1 and len(every) == 1
                        and not re.search(rf'\b{mark}\b', after)
                        and not re.search(rf'\b{mark}\b|\b{base}\b', loop.clean(loop.cond))
                        and not re.search(rf'\b{base}\b', after)
                        and not re.search(rf'&\s*(?:{mark}|{base})\b', part.clean[part.opening:part.end])):
                    return base, mark, amount, _number(init[0][1]), init[0]
    return None


def _blocks(clean):
    """(open, close) offsets of every brace block of `clean` that is not nested in another, in order."""
    out, depth, start = [], 0, 0
    for index, char in enumerate(clean):
        if char == '{':
            if depth == 0:
                start = index
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                out.append((start, index))
    return out


def _sink(text, clean, base):
    """The match arm with each `base += c;` deleted and the base's later reads in that block read `(base + c)`, or None
    when one is read outside the block it was stepped in (the step could not move)."""
    edits = []
    for step in re.finditer(rf'\b{base}\s*\+=\s*({NUMBER})\s*;[ \t]*', clean):
        depth = clean[:step.start()].count('{')-clean[:step.start()].count('}')
        end, level = len(clean), depth
        for index in range(step.end(), len(clean)):
            level += (clean[index] == '{')-(clean[index] == '}')
            if level < depth:
                end = index
                break
        edits.append((step.start(), step.end(), ''))
        amount = _number(step[1])
        for use in re.finditer(rf'\b{base}\b(?!\s*\+=)', clean[step.end():end]):
            at = step.end()+use.start()
            lone = re.search(r'[(,]\s*$', clean[:at]) and re.match(r'\s*[,)]', clean[at+len(base):])
            edits.append((at, at+len(base), f'{base} + {amount}' if lone else f'({base} + {amount})'))
        if re.search(rf'\b{base}\b', clean[end:]):
            return None
    return edit(text, edits)


def _fold(loop, pair):
    """New `then` and `rest` text with the mark pointer gone."""
    base, mark, amount, offset, _ = pair
    then, rest = loop.text(loop.then), loop.text(loop.rest)
    then_clean = loop.clean(loop.then)
    if _written(base, then_clean.replace(f'{base} +=', '')) or re.search(rf'\b{base}\s*=(?!=)', then_clean):
        return None
    sunk = _sink(then, then_clean, base)
    if sunk is None:
        return None
    then = sunk
    then = re.sub(rf'\b{mark}\s*\+\s*({NUMBER})', lambda m: f'{base} + {offset+_number(m[1])}', then)
    then = re.sub(rf'\b{mark}\b', f'({base} + {offset})', then)
    step = re.compile(rf'\b{mark}\s*\+=\s*{NUMBER}\s*;[ \t]*')
    if len(step.findall(rest)) != 1 or re.search(rf'\b{mark}\b', step.sub('', rest)):
        return None
    return then, step.sub('', rest)


def _declaration(part, mark):
    return re.search(rf'(?m)^[ \t]*(?:char|u8|s8|u16|s16|u32|s32|void)\s*\*\s*{mark}\s*;[ \t]*\n?|'
                     rf'(?<=[;{{}} \t])(?:char|u8|s8|u16|s16|u32|s32|void)\s*\*\s*{mark}\s*;[ \t]*',
                     part.clean[part.opening:part.end])


def _sentinel(source, name):
    """Edits that make a halfword-loaded `u32` local a `u16` local, or None."""
    part = view(source, name)
    clean = part.clean
    for decl in re.finditer(rf'(?<![\w*])(?:u32|s32|int|unsigned int)\s+({IDENT})\s*;', clean[part.opening:part.end]):
        local = decl[1]
        body = clean[part.opening:part.end]
        sets = list(re.finditer(rf'(?<![\w.]){local}\s*=(?!=)\s*([^;]*);', body))
        if not sets or any(not re.fullmatch(r'\*\s*\(\s*u16\s*\*\s*\)[^;]*', s[1].strip()) for s in sets):
            continue
        if re.search(rf'&\s*{local}\b|\b{local}\s*(?:[-+*/%&|^]=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*{local}\b', body):
            continue
        casts = list(re.finditer(rf'\(\s*u16\s*\)\s*{local}\b', body))
        if not casts and not re.search(rf'\b{local}\s*[!=]=\s*0[xX][fF]{{4}}\b', body):
            continue
        base = part.opening
        found = [(base+decl.start(), base+decl.end(), decl[0].replace(decl[0].split()[0], 'u16', 1)
                  if decl[0].startswith(('u32', 's32', 'int')) else 'u16 '+local+';')]
        found += [(base+c.start(), base+c.end(), local) for c in casts]
        return found
    return None


def _children(source, name):
    part = view(source, name)
    if not part:
        return []
    loop = _Loop(part)
    out = []
    pair = _pair(loop) if loop.ok else None
    narrow = _sentinel(source, name)

    def build(do, fold, halfword):
        edits = []
        if do or fold:
            if not loop.ok or fold and not pair:
                return None
            then, rest = loop.text(loop.then), loop.text(loop.rest)
            if fold:
                folded = _fold(loop, pair)
                if not folded:
                    return None
                then, rest = folded
                init = pair[4]
                edits.append((part.opening+init.start(), part.opening+init.end(), ''))
                mark = _declaration(part, pair[1])
                if mark:
                    edits.append((part.opening+mark.start(), part.opening+mark.end(), ''))
            cond = loop.text(loop.cond)
            if do:
                text = f'do {{ if ({cond}) {{{then} break; }}{rest}}} while ({loop.text(loop.d)});'
            else:
                text = f'{loop.label}:\nif ({cond}) {{{then}}} else {{{rest}{loop.text(loop.goto)}}}'
            edits.append((loop.start, loop.end, text))
        if halfword:
            if not narrow:
                return None
            edits += narrow
        return edit(source, edits) if edits else None

    for do, fold, halfword, family in ((True, True, True, FAMILY), (True, True, False, FAMILY),
                                       (False, True, True, 'derived_pointer_fold'),
                                       (True, False, True, 'goto_match_break_loop'),
                                       (True, False, False, 'goto_match_break_loop'),
                                       (False, True, False, 'derived_pointer_fold'),
                                       (False, False, True, 'sentinel_halfword_local')):
        text = build(do, fold, halfword)
        if text and text != source and all(text != seen for _, seen in out):
            out.append((family, text))
    return out


def variants(source, name):
    return _children(source, name)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
