"""A global table read inside a guarded loop through a pointer the guard's block sets: `if (..) { ..; do { } while
(T[k] == c); }` as `if (..) { T_t *tp = T; ..; do { } while (tp[k] == c); }`, and a long-lived alias of a table
(`H = T;` at the top, `u32 *lim = (u32 *)((char *)H + off);` in a guard) as one function-level pointer set in each guard.

KMC GCC 2.7.2 (`-O2`, N64), loop.c `scan_loop`: a constant's set is moved out of a loop only when it is used in its own
basic block, or is not a user variable, or is reached on every iteration and not used before it. A table address
written in the C (`T[k]`) is a compiler temporary: every loop around it moves it, `combine_movables` merges it with
the other loads of the same symbol (`done move-insn matches`) and it ends at the function entry, spilled and
rematerialised into the reload register (`lui $s7,%hi(T)` at each use). The same address set in a user variable inside
a guard (`maybe_never`) and used in a later block (the loop) stays where it is written: the target's `lui $v1,%hi(T);
addiu $v1,..` inside the guard. A pointer the strength reduction derives from it (the `T + 4k` the loop steps) starts
from that fresh register too. A long-lived alias (`H`, set once at the entry) is a pseudo with an equivalent constant:
reload rematerialises it into the reload register; one pointer variable assigned in several guards is set more than
once and is never moved, so each guard loads it fresh (the target's `lui $v0,%hi(H)` before `addu $s0,$t7,$v0`).

On a 681-instruction bit-stream decoder (canonical-code table builder): the code-assignment pass's inner test through a
guard-local pointer 290 -> 275, then the three later passes' bounds through one shared pointer 275 -> 235 (each source
checked on 1200 generated streams against the previous one). The rule above is read from loop.c (`scan_loop`, the
three cases before `CONSTANT_P (SET_SRC (set))`); that it is what the target's code shows is one function's evidence.

Two shapes, each child one rewrite:
- `guard_symbol_pointer`: in an `if (..) {` block, a `do { } while (..)` whose condition indexes a global array `T`
  (declared `extern E T[];` in the source or header): the block declares `E *<p> = T;` after its leading declarations
  (or first), and the condition reads `<p>[..]`.
- `guard_alias_pointer`: a pointer local `V` set once at the top level to a global array `T`, and block-local
  declarations `E *x = <expr naming V>;` inside `if (..) {` blocks: a new function-level `E *<p>;` and each such
  declaration as `E *x; <p> = T; x = <expr naming <p>>;`, for every subset of those blocks (up to four; past that all
  of them, all but one, and each alone): the shared pointer is the point, and on the decoder the three later passes
  needed it and the first did not.
Declines on `volatile`.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'guard_symbol_pointer'
ALIAS_FAMILY = 'guard_alias_pointer'
FAMILIES = (FAMILY, ALIAS_FAMILY)
LIMIT = 8

_TYPE = r'(?:unsigned\s+(?:int|short|char)|s32|u32|s16|u16|s8|u8|int|short|f32)'
_DECL = re.compile(rf'[ \t]*(?:{_TYPE}|struct\s+{IDENT})\s*\**\s*{IDENT}\s*(?:\[[^\]]*\])?\s*(?:=[^;]*)?;[ \t]*')


def _python_close(text, at, left, right):
    depth = 0
    for i in range(at, len(text)):
        depth += (text[i] == left) - (text[i] == right)
        if depth == 0:
            return i
    return None


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(text, at, left, right):
        found = _scan.close_every(text, at, left, right, False, None)
        return _python_close(text, at, left, right) if found is NotImplemented else found


def _globals(text):
    return {m.group(2): m.group(1) for m in re.finditer(rf'(?m)^[ \t]*extern\s+({_TYPE})\s+({IDENT})\s*\[[^\]]*\]\s*;', text)}


def _fresh(clean, stem):
    for n in ('', '2', '3', '4'):
        if not re.search(rf'\b{stem}{n}\b', clean):
            return stem + n
    return None


def _if_blocks(clean, lo, hi):
    for guard in re.finditer(r'\bif\s*\(', clean[lo:hi]):
        cond_open = lo + guard.end() - 1
        cond_close = _close(clean, cond_open, '(', ')')
        if cond_close is None:
            continue
        brace = re.compile(r'\s*\{').match(clean, cond_close + 1)
        if not brace:
            continue
        opening = brace.end() - 1
        closing = _close(clean, opening, '{', '}')
        if closing is not None:
            yield opening, closing


def _after_declarations(clean, opening, closing):
    """Offset of the line after the block's leading declarations, and that line's indent."""
    at = clean.find('\n', opening) + 1
    indent = re.match(r'[ \t]*', clean[at:]).group(0)
    while at < closing:
        line_end = clean.find('\n', at)
        line = clean[at:line_end]
        if not line.strip() or not _DECL.fullmatch(line):
            break
        at = line_end + 1
    return at, indent


def _symbol_children(source, clean, lo, hi, tables):
    out = []
    for opening, closing in _if_blocks(clean, lo, hi):
        block = clean[opening + 1:closing]
        for loop in re.finditer(r'\bdo\s*\{', block):
            body_open = opening + 1 + loop.end() - 1
            body_close = _close(clean, body_open, '{', '}')
            tail = re.compile(r'\s*while\s*\(').match(clean, body_close + 1) if body_close else None
            if not tail:
                continue
            cond_open = tail.end() - 1
            cond_close = _close(clean, cond_open, '(', ')')
            cond = clean[cond_open:cond_close + 1]
            for read in re.finditer(rf'(?<![\w.>])({IDENT})\s*\[', cond):
                table = read.group(1)
                if table not in tables:
                    continue
                stem = _fresh(clean, 'tp')
                if not stem:
                    continue
                kind = tables[table]
                first = clean.find('\n', opening) + 1
                indent = re.match(r'[ \t]*', clean[first:]).group(0)
                after, _ = _after_declarations(clean, opening, closing)
                use = (cond_open + read.start(1), cond_open + read.end(1), stem)
                for at in dict.fromkeys((after, first)):
                    out.append((FAMILY, edit(source, [(at, at, f'{indent}{kind} *{stem} = {table};\n'), use])))
    return out


def _alias_children(source, clean, lo, hi, tables):
    top = re.finditer(rf'(?m)^  ({IDENT})\s*=\s*({IDENT})\s*;', clean[lo:hi])
    out = []
    for alias in top:
        var, table = alias.group(1), alias.group(2)
        if table not in tables:
            continue
        sets = re.findall(rf'(?<![\w.>]){var}\s*=(?!=)', clean[lo:hi])
        declared = re.search(rf'(?m)^[ \t]*({_TYPE})\s*\*\s*{var}\s*;', clean[lo:hi])
        if len(sets) != 1 or not declared:
            continue
        kind = declared.group(1)
        stem = _fresh(clean, 'gp')
        if not stem:
            continue
        sites = []
        for opening, closing in _if_blocks(clean, lo, hi):
            for decl in re.finditer(rf'(?m)^([ \t]*)({_TYPE}\s*\*\s*)({IDENT})\s*=([^;]*\b{var}\b[^;]*);',
                                    clean[opening + 1:closing]):
                start, end = opening + 1 + decl.start(), opening + 1 + decl.end()
                if any(s[0] == start for s in sites):
                    continue
                expr = re.sub(rf'(?<![\w.>]){var}\b', stem, source[opening + 1 + decl.start(4):opening + 1 + decl.end(4)])
                text = f'{decl.group(1)}{decl.group(2)}{decl.group(3)}; {stem} = {table}; {decl.group(3)} ={expr};'
                sites.append((start, end, text))
        if not sites:
            continue
        declare_at = clean.rfind('\n', 0, declared.start() + lo) + 1
        new_decl = (declare_at, declare_at, f'  {kind} *{stem};\n')
        if len(sites) <= 4:  # every subset: which guards share the pointer is the search (all, or all but one)
            groups = [[s for b, s in enumerate(sites) if mask >> b & 1] for mask in range((1 << len(sites)) - 1, 0, -1)]
        else:
            groups = [sites] + [sites[:b] + sites[b + 1:] for b in range(len(sites))] + [[s] for s in sites]
        for group in groups:
            out.append((ALIAS_FAMILY, edit(source, [new_decl] + sorted(group))))
    return out


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(r'\bvolatile\b', clean[lo:hi]):
        return []
    tables = _globals(header + '\n' + source)
    if not tables:
        return []
    out = _symbol_children(source, clean, lo, hi, tables) + _alias_children(source, clean, lo, hi, tables)
    seen, kept = set(), []
    for family, text in out:
        if text != source and text not in seen:
            seen.add(text)
            kept.append((family, text))
    return kept[:LIMIT * 4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
