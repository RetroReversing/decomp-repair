"""A 0/1 flag that a block of tests computes, written as an inline predicate that returns as soon as it knows.

    if (id != -1) { c = v->ch; f = 0; if (c != 0xFF) { ...x, y...; f = 0; if (x == y) { f = 1; } } } else { f = 0; }
    if (f & 0xFF) { ... }
 -> static inline s32 NAME_flag(...) { if (id != -1) { c = v->ch; if (c != 0xFF) { ...; if (x == y) { return 1; } } }
                                       return 0; }
    f = NAME_flag(...);
    if (f & 0xFF) { ... }

Written in place, `f = 0; if (x == y) f = 1;` is a store-flag jump.c turns into `xor; sltiu`; the game's version
(KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) has `bne; move v0,zero; j; li v0,1`, the shape of an inline function's
`return 1;` jumping to its return label. On a 1315-instruction sound-sequence interpreter the predicate took the arm's
rows to the target's branches (9595 -> 9265; its two compared bytes as `s32` locals then 8720).

`flag_predicate_inline`
    A statement `S` (an `if`, with or without `else`) directly followed by `if (F ...)`, where `F` is a local that
    `S` only assigns `0` or `1`; each `F = 1;` is the last thing its path runs in `S`; every path that does not set
    `F = 1` sets `F = 0` (a top-level `F = 0;` in the block, or an `if`/`else` whose arms both do); the locals only
    `S` uses are declared in the predicate; the other locals and parameters `S` reads are passed in and never written
    by `S`. `S` becomes `F = NAME(args);` and the predicate has `S` with `F = 1;` as `return 1;`, `F = 0;` dropped,
    and `return 0;` at its end. The judge decides.
"""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'flag_predicate_inline'
FAMILIES = (FAMILY,)
KEYWORDS = {'if', 'else', 'while', 'do', 'for', 'switch', 'return', 'sizeof', 'struct', 'union', 'const', 'volatile',
            'register', 'static', 'unsigned', 'signed', 'char', 'short', 'int', 'long', 'float', 'double', 'void',
            'u8', 's8', 'u16', 's16', 'u32', 's32', 'u64', 's64', 'f32', 'f64', 'NULL', 'goto', 'break', 'continue'}


def _statement_end(clean, at, limit):
    """End of the statement starting at `at` (an `if` with its `else` chain, a block, or a simple statement)."""
    hit = re.compile(r'\s*if\s*\(').match(clean, at)
    if hit:
        after = close(clean, hit.end() - 1, '(', ')')
        if not after:
            return None
        end = _statement_end(clean, after, limit)
        if end is None:
            return None
        other = re.compile(r'\s*else\b').match(clean, end)
        return _statement_end(clean, other.end(), limit) if other else end
    brace = re.compile(r'\s*\{').match(clean, at)
    if brace:
        return close(clean, brace.end() - 1, '{', '}')
    semi = clean.find(';', at, limit)
    return semi + 1 if semi >= 0 else None


def _statements(clean, start, stop):
    """(start, end) of each top-level statement in `clean[start:stop]`."""
    found = []
    at = start
    while True:
        skip = re.compile(r'\s*').match(clean, at).end()
        if skip >= stop:
            return found
        end = _statement_end(clean, skip, stop)
        if end is None or end > stop:
            return None
        found.append((skip, end))
        at = end


def _zero_guaranteed(clean, start, stop, flag):
    """Whether every path through the block `clean[start:stop]` sets `flag = 0` (or returns 1, handled elsewhere)."""
    statements = _statements(clean, start, stop)
    if statements is None:
        return False
    for s_start, s_end in statements:
        if re.fullmatch(r'\s*' + re.escape(flag) + r'\s*=\s*0\s*;\s*', clean[s_start:s_end]):
            return True
    if not statements:
        return False
    last_start, last_end = statements[-1]
    return _if_both_zero(clean, last_start, last_end, flag)


def _if_both_zero(clean, start, end, flag):
    hit = re.compile(r'\s*if\s*\(').match(clean, start)
    if not hit:
        return False
    after = close(clean, hit.end() - 1, '(', ')')
    then_end = _statement_end(clean, after, end)
    other = re.compile(r'\s*else\b').match(clean, then_end) if then_end else None
    if not other:
        return False
    return _arm_zero(clean, after, then_end, flag) and _arm_zero(clean, other.end(), end, flag)


def _arm_zero(clean, start, end, flag):
    brace = re.compile(r'\s*\{').match(clean, start)
    if brace:
        return _zero_guaranteed(clean, brace.end(), end - 1, flag)
    if re.compile(r'\s*if\b').match(clean, start):
        return _if_both_zero(clean, start, end, flag)
    return bool(re.fullmatch(r'\s*' + re.escape(flag) + r'\s*=\s*0\s*;\s*', clean[start:end]))


def _terminal(clean, at, s_start, s_end):
    """Whether nothing in `S` runs after the statement ending at `at` on its path (only closing braces and skipped
    `else` arms follow, up to the end of `S`)."""
    while at < s_end:
        rest = re.compile(r'\s*').match(clean, at).end()
        if rest >= s_end:
            return True
        if clean[rest] == '}':
            at = rest + 1
            continue
        other = re.compile(r'else\b').match(clean, rest)
        if other:
            end = _statement_end(clean, other.end(), s_end)
            if end is None:
                return False
            at = end
            continue
        return False
    return True


def variants(source, name):
    part = view(source, name)
    span = find(source, name)
    if not part or not span:
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end - 1]
    declared = {}
    for hit in re.finditer(r'(?m)^\s*((?:register\s+)?(?:(?:unsigned|signed)\s+)?' + IDENT + r'(?:\s+' + IDENT + r')??[\s*]+)('
                           + IDENT + r')\s*;', body):
        kind = re.sub(r'^register\s+', '', hit[1].strip())
        if kind.split()[0] not in ('return', 'goto', 'break', 'continue'):
            declared.setdefault(hit[2], (kind, part.opening + 1 + hit.start(), part.opening + 1 + hit.end()))
    params = {}
    head = re.search(r'\b' + re.escape(name) + r'\s*\(([^)]*)\)\s*$', clean[span[0]:part.opening])
    for piece in (head[1].split(',') if head else []):
        piece = piece.strip()
        hit = re.search(r'(' + IDENT + r')\s*$', piece)
        if hit and piece != 'void' and hit[1] != piece:
            params[hit[1]] = piece[:hit.start()].strip()
    outside = _blank(source[:span[0]] + source[span[1]:])
    results = []
    for test in re.finditer(r'\bif\s*\(\s*(' + IDENT + r')\b', clean[part.opening:part.end]):
        flag = test[1]
        if flag not in declared:
            continue
        test_at = part.opening + test.start()
        # S: the statement just before `if (F`
        prefix = clean[part.opening + 1:test_at].rstrip()
        candidates = [m.start() for m in re.finditer(r'\bif\s*\(', clean[part.opening:test_at])]
        statement = None
        for start in reversed(candidates):
            start += part.opening
            end = _statement_end(clean, start, test_at)
            if end is not None and not clean[end:test_at].strip():
                statement = (start, end)
                break
            if end is not None and end < len(prefix) + part.opening + 1:
                continue
        if not statement:
            continue
        s_start, s_end = statement
        text = clean[s_start:s_end]
        writes = list(re.finditer(r'\b' + re.escape(flag) + r'\s*=(?!=)\s*([^;]*);', text))
        if not writes or any(w[1].strip() not in ('0', '1') for w in writes) or not any(w[1].strip() == '1' for w in writes):
            continue
        reads = [m for m in re.finditer(r'\b' + re.escape(flag) + r'\b', text)
                 if not re.match(r'\s*=(?!=)', text[m.end():])]
        if reads or re.search(r'\b(?:return|goto|break|continue)\b', text) or re.search(r'(?m)^\s*' + IDENT + r'\s*:(?!:)', text):
            continue
        if not all(_terminal(clean, s_start + w.end(), s_start, s_end) for w in writes if w[1].strip() == '1'):
            continue
        # every path that does not return 1 has set the flag to 0
        hit = re.compile(r'\s*if\s*\(').match(clean, s_start)
        after = close(clean, hit.end() - 1, '(', ')')
        then_end = _statement_end(clean, after, s_end)
        other = re.compile(r'\s*else\b').match(clean, then_end)
        if not other or not (_arm_zero(clean, after, then_end, flag) and _arm_zero(clean, other.end(), s_end, flag)):
            # `if (c) {...}` without `else`: the flag must be 0 before it
            before = clean[part.opening + 1:s_start].rstrip()
            if other or not re.search(r'\b' + re.escape(flag) + r'\s*=\s*0\s*;$', before):
                continue
        names = []
        for token in re.findall(r'(?<![\w])' + IDENT, text):
            if token not in names and token not in KEYWORDS and token != flag:
                names.append(token)
        private, shared = [], []
        ok = True
        for token in names:
            if token in declared:
                uses = len(re.findall(r'\b' + re.escape(token) + r'\b', body))
                inside = len(re.findall(r'\b' + re.escape(token) + r'\b', text))
                if uses == inside + 1:
                    private.append(token)
                    continue
                shared.append(token)
            elif token in params:
                shared.append(token)
            elif re.search(r'\b' + re.escape(token) + r'\b', outside):
                continue
            elif re.search(r'\w[\s*]+' + re.escape(token) + r'\s*[;=\[]', text) or re.search(
                    r'\(\s*\*\s*' + re.escape(token) + r'\s*\)', text):
                continue
            else:
                ok = False
                break
        if not ok:
            continue
        if any(re.search(r'(?<![\w.>])' + re.escape(v) + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + re.escape(v)
                         + r'\b|\b' + re.escape(v) + r'\s*(?:\+\+|--)|&\s*' + re.escape(v) + r'\b(?!\s*[\[.])', text.replace('&&', '  '))
               for v in shared):
            continue
        helper = f'{name}_flag'
        n = 2
        while re.search(r'\b' + re.escape(helper) + r'\b', source):
            helper = f'{name}_flag{n}'
            n += 1
        original = source[s_start:s_end]
        converted = re.sub(r'\b' + re.escape(flag) + r'\s*=\s*1\s*;', 'return 1;', original)
        converted = re.sub(r'(?m)^[ \t]*' + re.escape(flag) + r'\s*=\s*0\s*;[ \t]*\n', '', converted)
        converted = re.sub(r'\b' + re.escape(flag) + r'\s*=\s*0\s*;', ';', converted)
        signature = ', '.join(f'{params.get(v) or declared[v][0]} {v}' for v in shared) or 'void'
        kind = declared[flag][0]
        locals_ = ''.join(f'  {declared[v][0]} {v};\n' for v in private)
        indent = re.match(r'[ \t]*', original.split('\n')[-1] if '\n' in original else '').group(0)
        lines = converted.split('\n')
        width = min((len(line) - len(line.lstrip()) for line in lines[1:] if line.strip()), default=len(indent))
        width = min(width, len(indent))
        body_text = '  ' + lines[0] + ''.join('\n  ' + line[width:] if line.strip() else '\n' for line in lines[1:])
        definition = f'static inline {kind} {helper}({signature})\n{{\n{locals_}{body_text}\n  return 0;\n}}\n\n'
        call = f'{flag} = {helper}({", ".join(shared)});'
        edits = [(span[0], span[0], definition), (s_start, s_end, call)]
        before = clean[part.opening + 1:s_start].rstrip()
        zero = re.search(r'\b' + re.escape(flag) + r'\s*=\s*0\s*;$', before)
        if zero and not other:
            edits.append((part.opening + 1 + zero.start(), part.opening + 1 + zero.end(), ''))
        for v in private:
            start, stop = declared[v][1], declared[v][2]
            edits.append((start, stop, ''))
        results.append((FAMILY, edit(source, edits)))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
