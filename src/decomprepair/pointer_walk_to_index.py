"""A loop that steps a record pointer beside a counter, written as the counter indexing the base (and the reverse).

m2c writes a loop over an array of records with two induction variables, a counter and a pointer that steps one record
(a constant stride in bytes) each pass:

    n = 0;  p = base;  do { M2C_FIELD(p, s32 *, 4) = ...;  n += 1;  p += 0x18; } while (n < count);

gcc 2.8.1 (SN, `-mips2/-mips3 -O2`) keeps the pointer as a register of its own that is set before the loop and stepped at
the bottom, next to the counter's own step. The game's loop indexed the array, `for (i = 0; i < count; i++) base[i].f`,
and the compiler then makes ONE stepping pointer of its own, set after the constants it hoists out of the loop, so the
hoisted constants take the registers the walk had held and the loop's body schedules as in the target. Four N64 functions
(a particle update, a menu draw, a per-record scan and an object-list scan) were decided by this one change; the m2c
walk scored 470 to 2500 off and the indexed loop was exact.

`pointer_walk_to_index` takes a pointer `p` stepped once per pass by a constant (`p += K`, `p = p + K`, `p++`) at the top
level of a loop body, and a counter `n` stepped once per pass by one (`n += 1`, `n++`) at the top level of the same body
and set to `0` before the loop. The pointer's type gives the stride in bytes (`void *` and `s8`/`u8` pointers step bytes,
`s16 *` by 2, `s32 *`, `u32 *`, `f32 *` and pointers by 4; any other record type only for a step of one, which then
indexes the type itself). Every use of `p` in the body must be a field read or write (`M2C_FIELD(p, T *, off)` and the
function's own `F(p, T, off)` macros; for a record type also `p->f` and `*p`), `p` is not named after the loop or
written anywhere in it, the body has no `continue`, `goto` or label. Child: the step of `p` is removed and every use
indexes from `p`, which keeps the value it had before the loop (`M2C_FIELD(p, T *, off)` becomes
`M2C_FIELD(p, T *, n * K + off)`; `p->f` becomes `p[n].f`; a use that comes after one of the two steps and before the other
counts the difference: `(n + 1) * K`). One child per pointer, at most MAX_CHILDREN.

`index_to_pointer_walk` is the reverse, which four other functions needed (a table scan whose match steps one cursor, `e++`,
beside the counter): in `for (i = A; ...; i++)` whose body reads `X[i]` and `X[i].f` of a pointer or array `X` of a record
type the declarations show (`T *X`, `T X[]`) and nowhere else uses `i` as an index, with `X` not written in the loop, the
loop is rewritten with a cursor `T *cur_X;` set to `&X[A]` before the loop, stepped `i++, cur_X++` and read `cur_X->f`
(`(*cur_X)` for the record itself). A global `X` is only taken when the body calls nothing.

This module reads text only and never compiles or judges. The candidate is never a verdict: the judge decides."""
import re

from .c_scan import close, enclosing_block
from .csource import _blank
from .hand_found_support import declare, declaring, fresh, local_type
from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'pointer_walk_to_index'
REVERSE_FAMILY = 'index_to_pointer_walk'
FAMILIES = (FAMILY, REVERSE_FAMILY)

MAX_CHILDREN = 8
_SIZES = {'s8': 1, 'u8': 1, 'char': 1, 'void': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'f32': 4,
          'int': 4, 'float': 4, 'unsigned': 4, 'f64': 8, 'M2C_UNK': 1}
_MACRO = re.compile(rf'(?m)^[ \t]*#[ \t]*define[ \t]+(?P<name>{IDENT})\([ \t]*(?P<a>{IDENT})[ \t]*,[ \t]*(?P<b>{IDENT})'
                    rf'[ \t]*,[ \t]*(?P<c>{IDENT})[ \t]*\)[ \t]*\(\*\([ \t]*(?P=b)[ \t]*\)\(\(s8 \*\)[ \t]*\(?[ \t]*(?P=a)'
                    rf'[ \t]*\)?[ \t]*\+[ \t]*\(?[ \t]*(?P=c)[ \t]*\)?\)\)')


def _stride(kind):
    """Bytes of one element of a pointer of declared type `kind` (`void *`, `s32 *`), None when it is not a plain one."""
    hit = re.fullmatch(r'(?:(?:const|volatile)\s+)*(' + IDENT + r')\s*\*', (kind or '').strip())
    return _SIZES.get(hit[1]) if hit else None


def _field_macros(source, header):
    return {'M2C_FIELD'} | {m['name'] for m in _MACRO.finditer(f'{header or ""}\n{source}')}


def _dereference(before):
    """True when a `*` that follows `before` is a dereference and not a multiplication."""
    before = before.rstrip()
    return not before or before[-1] in '=(,;{}!&|<>+-*/%?:' and not before.endswith(('++', '--'))


def _arguments(clean, opening):
    """[(start, end)] of the top-level comma-separated arguments of the call whose `(` is at `opening`; the closing index."""
    end = close(clean, opening, '(', ')')
    if end < 0:
        return None, -1
    spans, depth, start = [], 0, opening + 1
    for i in range(opening + 1, end):
        c = clean[i]
        depth += c in '([{'
        depth -= c in ')]}'
        if c == ',' and depth == 0:
            spans.append((start, i))
            start = i + 1
    spans.append((start, end))
    return spans, end


def _loop_body(clean, opening, lo):
    """True when the block opening at `opening` is the body of a `do`, `for` or `while`."""
    before = clean[lo:opening].rstrip()
    if re.search(r'(?<![\w.])do$', before):
        return True
    if not before.endswith(')'):
        return False
    depth = 0
    for i in range(len(before) - 1, -1, -1):
        depth += before[i] == ')'
        depth -= before[i] == '('
        if depth == 0:
            return bool(re.search(r'(?<![\w.])(?:for|while)\s*$', before[:i]))
    return False


def _pointer_type(source, part, name):
    """The declared type text of `name`, a local or a parameter."""
    kind = local_type(part, name)
    if kind:
        return kind
    head = part.clean[:part.opening]
    hit = re.search(rf'[(,]\s*((?:(?:const|volatile)\s+)*{IDENT}\s*\*+)\s*{re.escape(name)}\s*[,)]', head[head.rfind('('):])
    return re.sub(r'\s+', ' ', hit[1]) if hit else None


def _counter_steps(clean, lo, hi):
    """[(name, start, end)] of the statements that step a variable by one (`n += 1;`, `n++;`, `n = n + 1;`)."""
    return [(m['name'], lo + m.start(), lo + m.end()) for m in re.finditer(
        rf'(?<![\w.>])(?P<name>{IDENT})\s*(?:\+=\s*1|\+\+|=\s*(?P=name)\s*\+\s*1)\s*;', clean[lo:hi])]


def _pointer_steps(clean, lo, hi):
    out = []
    for m in re.finditer(rf'(?<![\w.>])(?P<name>{IDENT})\s*(?:\+=\s*(?P<k>{NUMBER})|=\s*(?P=name)\s*\+\s*(?P<k2>{NUMBER})'
                         rf'|(?P<inc>\+\+))\s*;', clean[lo:hi]):
        k = 1 if m['inc'] else int(m['k'] or m['k2'], 0)
        out.append((m['name'], k, lo + m.start(), lo + m.end()))
    return out


def _depth_one(clean, lo, hi, at):
    """True when position `at` is directly in the block interior [lo, hi): no brace opens or closes between."""
    return clean.count('{', lo, at) == clean.count('}', lo, at)


def _line(source, start, end):
    """(start, end) widened over the whole line when the statement is alone on it."""
    a, b = source.rfind('\n', 0, start) + 1, source.find('\n', end)
    b = len(source) if b < 0 else b + 1
    return (a, b) if not source[a:start].strip() and not source[end:b].strip() else (start, end)


def _plan(source, part, macros, step, counters, move=False):
    """The edits of the child for the pointer step `step` = (name, k, start, end), or None; with `move` the counter's
    step goes to the end of the body (only when the body names the counter nowhere else)."""
    p, k, s_start, s_end = step
    clean = part.clean
    opening = enclosing_block(clean, s_start, part.opening + 1)
    if opening < 0:
        return None
    ending = close(clean, opening)
    if ending < 0 or not _loop_body(clean, opening, part.opening) or not _depth_one(clean, opening + 1, ending, s_start):
        return None
    body = clean[opening + 1:ending]
    if re.search(r'(?<![\w.])(?:continue|goto)\b|(?m:^\s*\w+\s*:(?!:))', body):
        return None
    kind = _pointer_type(source, part, p)
    stride = _stride(kind)
    typed = stride is None and k == 1 and kind and re.fullmatch(rf'(?:struct\s+)?{IDENT}\s*\*', kind.strip())
    if stride is None and not typed:
        return None
    # the counter: stepped by one at the top level of the same body, set to 0 before the loop, stepped nowhere else
    chosen = None
    for n, c_start, c_end in counters:
        if opening < c_start < ending and _depth_one(clean, opening + 1, ending, c_start) and n != p:
            if len(re.findall(rf'(?<![\w.>]){re.escape(n)}\s*(?:\+=|\+\+|=\s*{re.escape(n)}\s*\+)', body)) != 1:
                continue
            inits = re.findall(rf'(?<![\w.>]){re.escape(n)}\s*=\s*([^;=]+?)\s*;', clean[part.opening:opening])
            if inits and re.fullmatch(r'0[uUlL]*', inits[-1]) and not re.search(
                    rf'(?<![\w.>]){re.escape(n)}\s*=(?!=)', body):
                chosen = (n, c_start, c_end)
                break
    if not chosen:
        return None
    n, c_start, c_end = chosen
    later = re.search(rf'(?<![\w.>]){re.escape(p)}\b(?P<set>\s*=(?!=))?', clean[ending + 1:part.end])
    if later and not later['set']:
        return None  # the pointer's last value is read after the loop (a set before any read is another walk's)
    edits = [(*_line(source, s_start, s_end), '')]
    if move:
        elsewhere = clean[opening + 1:c_start] + ' ' + clean[c_end:ending]
        end_line = source.rfind('\n', 0, ending) + 1
        if re.search(rf'(?<![\w.>]){re.escape(n)}\b', elsewhere) or source[end_line:ending].strip() \
                or ending < s_end:
            return None
        pad = re.match(r'[ \t]*', source[source.rfind('\n', 0, c_start) + 1:c_start])[0]
        edits += [(*_line(source, c_start, c_end), ''), (end_line, end_line, f'{pad}{source[c_start:c_end]}\n')]
        c_start = ending
    for m in re.finditer(rf'(?<![\w.>]){re.escape(p)}\b', body):
        at = opening + 1 + m.start()
        if s_start <= at < s_end:
            continue
        after = clean[at + len(p):].lstrip()
        before = clean[:at].rstrip()
        moved = (at > s_start) - (at > c_start)
        index = n if moved == 0 else f'({n} {"+" if moved > 0 else "-"} 1)'
        if typed:
            if after.startswith('->'):
                edits.append((at, clean.index('->', at) + 2, f'{p}[{index}].'))
            elif before.endswith('*') and _dereference(before[:-1]):
                edits.append((before.rindex('*'), at + len(p), f'{p}[{index}]'))
            else:
                return None
            continue
        paren = before.rfind('(') if before.endswith('(') else -1
        call = re.search(rf'(?<![\w.>])({IDENT})\s*$', clean[:paren]) if paren >= 0 else None
        if not call or call[1] not in macros:
            return None
        spans, _ = _arguments(clean, paren)
        if not spans or len(spans) != 3 or clean[spans[0][0]:spans[0][1]].strip() != p:
            return None
        offset = spans[2]
        text = clean[offset[0]:offset[1]].strip()
        stride_bytes = stride * k
        term = f'{index} * 0x{stride_bytes:X}' if stride_bytes > 9 else f'{index} * {stride_bytes}'
        edits.append((offset[0], offset[1], f' {term}' if text == '0' else f' {term} - {text[1:].strip()}'
                      if text.startswith('-') else f' {term} + {text}'))
    return edits if len(edits) > 1 + 2 * move else None


def forward(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    macros = _field_macros(source, header)
    clean = part.clean
    counters = _counter_steps(clean, part.opening, part.end)
    out = []
    for step in _pointer_steps(clean, part.opening, part.end):
        for move in (False, True):  # the counter's step where it is, then at the end of the body
            edits = _plan(source, part, macros, step, counters, move)
            if edits:
                out.append((FAMILY, edit(source, edits)))
    return out


_FOR = re.compile(rf'(?<![\w.])for\s*\(\s*(?P<i>{IDENT})\s*=\s*(?P<init>[^;{{}}]+?)\s*;\s*(?P<cond>[^;{{}}]+?)\s*;\s*'
                  rf'(?P<step>(?P=i)\s*\+\+|\+\+\s*(?P=i)|(?P=i)\s*\+=\s*1)\s*\)\s*\{{')


def _element_type(source, part, x):
    """The record type of `X` when `T *X` (a local, parameter or `extern`) or `T X[]` shows one, else None."""
    pattern = rf'(?:^|[\s(,;]|extern\s)((?:struct\s+)?{IDENT})\s*(\*)?\s*{re.escape(x)}\s*(\[[^\]]*\])?\s*[;,)=]'
    for text in (part.clean[:part.opening], part.clean[part.opening:part.end], _blank(source)):
        for m in re.finditer(pattern, text):
            kind = m[1]
            if kind in {'return', 'else', 'sizeof'} or (not m[2] and not m[3]) or kind in _SIZES or kind == 'void':
                continue
            return kind
    return None


def reverse(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    taken = set(re.findall(IDENT, source))
    out = []
    for loop in _FOR.finditer(clean, part.opening, part.end):
        opening = loop.end() - 1
        ending = close(clean, opening)
        i, init = loop['i'], loop['init']
        body = clean[opening + 1:ending]
        if ending < 0 or re.search(rf'(?<![\w.>])(?:{re.escape(i)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(i)}\b|{re.escape(i)}\s*(?:\+\+|--)|&\s*{re.escape(i)}\b)', body):
            continue
        indexed = {m['x'] for m in re.finditer(rf'(?<![\w.>])(?P<x>{IDENT})\s*\[\s*{re.escape(i)}\s*\]', body)}
        for x in sorted(indexed):
            if x in {'D', i} or re.search(rf'(?<![\w.>]){re.escape(x)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(x)}\b|'
                                          rf'{re.escape(x)}\s*(?:\+\+|--)|&\s*{re.escape(x)}\b(?!\s*\[)', body):
                continue
            kind = _element_type(source, part, x)
            local = local_type(part, x) is not None or re.search(rf'[(,]\s*[\w\s*]*\b{re.escape(x)}\s*[,)]', clean[:part.opening])
            if not kind or (not local and re.search(rf'(?<![\w.>]){IDENT}\s*\(', re.sub(r'\b(?:if|while|for|switch|sizeof)\b', '', body))):
                continue
            # every use of `i` inside the body must be a subscript of a pointer we walk, or an `i`-free statement
            cursor = fresh('cur', taken, x)
            if re.search(rf'(?<![\w.>]){re.escape(i)}\b(?!\s*\])', re.sub(
                    rf'(?<![\w.>]){re.escape(x)}\s*\[\s*{re.escape(i)}\s*\]', ' ', body)) or re.search(
                        rf'(?<![\w.>])(?!{re.escape(x)}\b){IDENT}\s*\[\s*{re.escape(i)}\s*\]', body):
                continue
            edits = []
            for m in re.finditer(rf'(?<![\w.>]){re.escape(x)}\s*\[\s*{re.escape(i)}\s*\](?P<dot>\s*\.)?', body):
                a = opening + 1 + m.start()
                edits.append((a, opening + 1 + m.end(), f'{cursor}->' if m['dot'] else f'(*{cursor})'))
            start = '' if re.fullmatch(r'0[uUlL]*', init.strip()) else f'&{x}[{init.strip()}]'
            pointer = start or x
            line = source.rfind('\n', 0, loop.start()) + 1
            pad = re.match(r'[ \t]*', source[line:loop.start()])[0]
            edits.append((loop.start(), loop.start(), f'{cursor} = {pointer};\n{pad}'))
            edits.append((loop.start('step'), loop.end('step'), f'{loop["step"].strip()}, {cursor}++'))
            edits.append(declare(source, part, [declaring(f'{kind} *', cursor)]))
            out.append((REVERSE_FAMILY, edit(source, edits)))
    return out


def variants(source, name, header=''):
    """Proposals: a stepped record pointer beside a counter as the counter's index, and an indexed loop as a cursor."""
    return list(dict.fromkeys(forward(source, name, header) + reverse(source, name, header)))[:MAX_CHILDREN]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 66,
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
