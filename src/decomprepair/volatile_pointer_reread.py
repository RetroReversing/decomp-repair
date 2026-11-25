"""A volatile global pointer read through the global again, where the target reads it once into the local it stores through.

A game's track-marker (or camera, or player) pointer is declared `extern void *volatile G;`, so every direct read of `G`
is a load the compiler may not share, and a drafted function reads it where the draft needed a fresh pointer:

    marker = TRACK_MARKER;                       /* a plain read through a cast of &G: cse may share it */
    marker->f = marker->f - c;
    temp = ((T *) (G))->f;                       /* a second, volatile read */
    if (temp < 0.0f) { marker->f = 0.0f; ... }   /* the store goes through the FIRST pointer */

while the target loads the pointer once for that second step and stores through the same register
(`lw $v0,G; lwc1 $f0,0x12c($v0); ... swc1 $f2,0x12c($v0)`). Written the second way the first pointer's register is free
earlier, the store no longer slides below the volatile load in the scheduler, and the pointer lands in `$v0` instead of
a saved temporary (a 349-instruction state machine: 535 -> 320 for the first site, 300 -> 60 for the second, after
the arm's float local was split). The same read inside a condition (`if (((temp = ((T *) (G))->f) <= 0.0f) || ...`)
right after `marker = G;` folds into the local the same way: the volatile global is read once, not twice.

What is read: `((T *) (G))->` or `((T *) G)->` where `G` is declared `extern ... * volatile G;` in the source or the
header, and the function has a local `T *L;` (or `T *L = ...;`). `variants` gives, labelled `volatile_pointer_reread`:

  assign  the statement holding the read gets `L = G;` in front and reads through `L` (only when `L` is read again
          after the statement, so the new value is used), for each such read;
  fold    the read reads through `L` when `L = G;` is the nearest earlier assignment of `L` in an enclosing block;
  all     every assign/fold at once (the sites pay off together: each alone moves one pointer register).

A read in a loop header, in the condition of a `while`, or in a statement that also assigns `L` is left alone, and so is
any `G` whose cast type has no local. The program reads `G` once per site, as the target does.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'volatile_pointer_reread'
FAMILIES = (FAMILY,)
LIMIT = 24

VOLATILE_POINTER = re.compile(r'\bextern\s+[\w\s]*?\*\s*volatile\s+([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*;')


def _volatile_globals(source, header):
    return {m.group(1) for text in (source, header or '') for m in VOLATILE_POINTER.finditer(_blank(text))}


def _statement_start(clean, pos, opening):
    """Where the statement holding `pos` begins, or None when it sits in a `for`/`while` header (re-evaluated)."""
    depth = 0
    k = pos - 1
    while k > opening:
        ch = clean[k]
        if ch == ')':
            depth += 1
        elif ch == '(':
            if depth == 0:
                before = re.search(r'(\w+)\s*$', clean[opening:k])
                if before and before.group(1) in ('for', 'while'):
                    return None
            else:
                depth -= 1
        elif depth == 0 and ch in ';{}':
            return k + 1
        k -= 1
    return None


def _python_statement_end(clean, pos, end):
    """The `;` ending the statement that holds `pos` at its own nesting level, or None."""
    depth = 0
    k = pos
    while k < end:
        ch = clean[k]
        if ch in '({[':
            depth += 1
        elif ch in ')}]':
            depth -= 1
            if depth < 0:
                return None
        elif ch == ';' and depth == 0:
            return k
        k += 1
    return None


_statement_end = _python_statement_end
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _statement_end(clean, pos, end):
        found = _scan.statement_end(clean, pos, end, '({[', ')}]', False, True, None)
        return _python_statement_end(clean, pos, end) if found is NotImplemented else found


def _fold_source(clean, local, glob, ctype, pos, opening):
    """The start of the nearest earlier `local = G;` that dominates `pos` (no closing brace and no other write between)."""
    pattern = re.compile(r'(?<![\w.>])' + re.escape(local) + r'\s*=\s*(?:\(\s*' + re.escape(ctype) +
                         r'\s*\*\s*\)\s*)?\(?\s*' + re.escape(glob) + r'\s*\)?\s*;')
    found = None
    for m in pattern.finditer(clean, opening, pos):
        found = m
    if not found:
        return None
    between = clean[found.end():pos]
    depth = 0
    for ch in between:
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth < 0:
                return None
    if re.search(r'(?<![\w.>])' + re.escape(local) + r'\s*(?:=(?!=)|\+\+|--|[-+*/&|^]=)', between):
        return None
    if re.search(r'&\s*' + re.escape(local) + r'\b', clean[opening:pos]):
        return None
    return found


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    sites = []
    for glob in sorted(_volatile_globals(source, header)):
        read = re.compile(r'\(\(\s*([A-Za-z_]\w*)\s*\*\s*\)\s*\(?\s*' + re.escape(glob) + r'\s*\)?\s*\)\s*->')
        for m in read.finditer(clean, opening, end):
            ctype = m.group(1)
            locals_ = re.findall(r'(?m)^\s*(?:struct\s+)?' + re.escape(ctype) + r'\s*\*\s*([A-Za-z_]\w*)\s*(?:=[^;]*)?;',
                                 clean[opening:end])
            locals_ += re.findall(r'[{;]\s*' + re.escape(ctype) + r'\s*\*\s*([A-Za-z_]\w*)\s*=', clean[opening:end])
            for local in dict.fromkeys(locals_):
                if re.search(r'(?<![\w.>])' + re.escape(local) + r'\s*=(?!=)', clean[m.start():m.end() + 80].split(';')[0]):
                    continue
                folded = _fold_source(clean, local, glob, ctype, m.start(), opening)
                if folded:
                    sites.append(('fold', m, local, glob, None))
                    break
                start = _statement_start(clean, m.start(), opening)
                stop = _statement_end(clean, m.start(), end)
                if start is None or stop is None:
                    continue
                if not re.search(r'(?<![\w.])' + re.escape(local) + r'\s*->', clean[stop:end]):
                    continue
                statement = clean[start:stop]
                if re.search(r'(?<![\w.>])' + re.escape(local) + r'\s*=(?!=)', statement):
                    continue
                sites.append(('assign', m, local, glob, start))
                break
    if not sites:
        return []

    def apply(chosen):
        text = source
        for kind, m, local, glob, start in sorted(chosen, key=lambda s: s[1].start(), reverse=True):
            text = text[:m.start()] + local + '->' + text[m.end():]
            if kind == 'assign':
                lead = re.match(r'\s*', source[start:]).group()
                text = text[:start] + lead + f' {local} = {glob};' + text[start + len(lead):]
        return text

    result = []

    def emit(text):
        if text != source and text not in [t for _, t in result] and len(result) < LIMIT:
            result.append((FAMILY, text))

    for site in sites:
        emit(apply([site]))
    if len(sites) > 1:
        emit(apply(sites))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 60}
