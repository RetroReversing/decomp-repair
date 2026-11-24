"""A call's zero-test argument (`load != 0`, `load != NULL`) with its load staged in a local before the statement.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) projectile update of 2,503 instructions. Two calls pass a
flag computed from a member: `hit(..., (r->flags & 0x2000) != 0, 0)` and `cast(..., r->onHit != NULL, 0)`. The target
loads the member (and masks it) before the other arguments and tests it with `sltu` (a plain zero test); written in the
argument list, the single-bit test became `srl`/`andi 1` and the load moved next to the call. With the loaded value
in a local set just before the statement (`t = r->flags & 0x2000; hit(..., t != 0, 0);`) both came out as the target's
(20273 -> 19868 and 12071 -> 11576). Hypothesis from the match, not confirmed in the compiler source: expanding
`(x & 2^n) != 0` inside the call lets `do_store_flag` take its single-bit path, a variable's test does not.

call_test_argument_stage
    For a call argument `E != 0`, `E != NULL` or `E != 0U` (also parenthesised) whose `E` reads memory and has no call,
    assignment, `++`/`--` or `volatile`, a new local (`void *` for a `NULL` test, else `s32`) is declared at the top of
    the function, set to `E` on the line before the statement, and the argument becomes `local != 0` (`!= NULL`). The
    statement must start its own line (not an `else if`, `for` or `while` header). One child per argument, then one
    with every argument staged.

The exact judge decides every child.
"""
import re

FAMILY = 'call_test_argument_stage'
FAMILIES = (FAMILY,)
LIMIT = 10
PREFIX = 'stagedTest'

_ID = r'[A-Za-z_]\w*'
_CALL = re.compile(rf'\b({_ID})\s*\(')
_BAD_EXPR = re.compile(r'(?<![=!<>])=(?!=)|\+\+|--|\bvolatile\b')
_KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof'}


def _close(text, start):
    """Index of the parenthesis closing the one at `start`, or -1."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_args(text, start, end):
    """(start, end) spans of the top-level arguments between the call's parentheses."""
    spans, depth, at = [], 0, start
    for i in range(start, end):
        c = text[i]
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c == ',' and depth == 0:
            spans.append((at, i))
            at = i + 1
    spans.append((at, end))
    return spans


def _strip_parens(expr):
    expr = expr.strip()
    while expr.startswith('(') and _close(expr, 0) == len(expr) - 1:
        expr = expr[1:-1].strip()
    return expr


def _test(arg):
    """(loaded expression, 'NULL' or '0') when the argument is a zero test of a memory read, else None."""
    arg = _strip_parens(arg)
    found = re.fullmatch(r'(?P<e>.+?)\s*!=\s*(?P<z>NULL|0U?|\(\s*void\s*\*\s*\)\s*0)', arg, re.S)
    if not found:
        return None
    expr = _strip_parens(found.group('e'))
    if '*' not in expr and '->' not in expr and '[' not in expr:
        return None
    if _BAD_EXPR.search(expr) or any(m.group(1) not in _KEYWORDS and not _is_cast_word(m.group(1))
                                     for m in _CALL.finditer(expr)):
        return None
    return expr, ('NULL' if 'NULL' in found.group('z') or 'void' in found.group('z') else '0')


def _is_cast_word(word):
    return word in {'char', 'u8', 's8', 'u16', 's16', 'u32', 's32', 'f32', 'void', 'int', 'unsigned', 'signed'}


def _sites(source):
    """(line start, argument span, expression, zero) for every stageable argument of a call on its own line."""
    sites = []
    for line in re.finditer(r'(?m)^[ \t]*(?P<body>[^\n]*)$', source):
        body = line.group('body')
        if not body.endswith((';', '{')) or re.match(r'(?:\}\s*)?(?:else\b|for\b|while\b|do\b|case\b|default\b)', body):
            continue
        for call in _CALL.finditer(source, line.start('body'), line.end()):
            if call.group(1) in _KEYWORDS or _is_cast_word(call.group(1)):
                continue
            open_at = call.end() - 1
            close_at = _close(source, open_at)
            if close_at < 0 or close_at > line.end():
                continue
            for span in _split_args(source, open_at + 1, close_at):
                test = _test(source[span[0]:span[1]])
                if test:
                    sites.append((line.start(), span, test[0], test[1]))
    return sites


def _body_start(source, name):
    found = re.search(rf'(?m)^[^\n;]*\b{re.escape(name)}\s*\([^;{{]*\)\s*\{{[ \t]*\n', source) if name else None
    return found.end() if found else -1


def _stage(source, name, chosen):
    body = _body_start(source, name)
    if body < 0:
        return None
    taken = set(re.findall(rf'\b{PREFIX}\d+\b', source))
    names, number = [], 0
    for _ in chosen:
        while f'{PREFIX}{number}' in taken:
            number += 1
        names.append(f'{PREFIX}{number}')
        number += 1
    pairs = list(zip(chosen, names))
    text = source
    for line_start in sorted({site[0] for site in chosen}, reverse=True):
        group = sorted((pair for pair in pairs if pair[0][0] == line_start), key=lambda pair: -pair[0][1][0])
        for (_, span, _, zero), local in group:
            text = text[:span[0]] + f' {local} != {zero}' + text[span[1]:]
        lead = re.match(r'[ \t]*', text[line_start:]).group(0)
        staged = ''.join(f'{lead}{local} = {expr};\n' for (_, _, expr, _), local in reversed(group))
        text = text[:line_start] + staged + text[line_start:]
    declarations = ''.join(f'    {"void *" if zero == "NULL" else "s32 "}{local};\n'
                           for (_, _, _, zero), local in zip(chosen, names))
    return text[:body] + declarations + text[body:]


def variants(source, name):
    sites = [site for site in _sites(source) if site[0] > _body_start(source, name) >= 0]
    sets = [[site] for site in sites]
    if len(sites) > 1:
        sets.append(list(sites))
    result = []
    for chosen in sets:
        text = _stage(source, name, chosen)
        if text and text != source:
            result.append((FAMILY, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
