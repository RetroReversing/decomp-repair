"""Fall through to a function's trailing default constant return instead of repeating it in inner arms.

Hypothesis (confirmed in gcc-2.7.2-kmc jump.c lines 727-833 and 1014-1305): under -O1/-O2 on
MIPS (-mips2/-mips3, BRANCH_COST == 2), `return cond ? K : 0;` expands via store-flag (`sltu`/`sll`),
and a local `if (cond) { return K; } return 0;` whose adjacent zero-return label has a single use with
no intervening call or branch is likewise converted by `jump_optimize` into store-flag instructions.
When the inner arms omit `return 0;` and instead fall out of an enclosing `if`/`else if` chain to the
function's single trailing `return 0;`, the shared label has multiple uses across calls/branches so
`jump_optimize` leaves explicit conditional branches (`beqz`/`bnez`), which also creates cross-jump
partner labels in `jump2` and prevents over-merging earlier multi-flag blocks (10515 -> 0 on a
3756-instruction function where each sub-edit alone regressed to 12470..16430).
"""
import re

from .arm_block_support import brace_pairs, indentation, line_start, statements
from .integer_repair_support import IDENT, edit, plain_repair_view

FAMILY = 'trailing_default_return_fallthrough'
FAMILIES = (FAMILY,)

_INT_LIT = r'-?(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*'
_DISALLOWED_RE = re.compile(
    r'\b(?:setjmp|longjmp|__LINE__|__COUNTER__|__builtin_\w*|_Atomic|case|default)\b'
    r'|(?:^|[=(,{;:?])\s*&&\s*' + IDENT + r'\b'
    r'|^[ \t]*' + IDENT + r'\s*:(?!:)',
    re.M,
)


def _int_val(lit):
    text = lit.rstrip('uUlL')
    if text.startswith('-'):
        return -int(text[1:].lstrip(), 0)
    return int(text, 0)


def _return_lit(clean_stmt):
    m = re.match(r'^\s*return\b', clean_stmt)
    if not m or not clean_stmt.rstrip().endswith(';'):
        return None
    inner = clean_stmt[m.end():len(clean_stmt.rstrip()) - 1]
    _, stripped = _strip_outer_parens(inner, inner)
    if re.match(r'^-\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*$', stripped):
        stripped = '-' + stripped[1:].lstrip()
    return stripped if re.fullmatch(_INT_LIT, stripped) else None


def _strip_outer_parens(expr, clean_expr):
    expr_s = expr.strip()
    clean_s = clean_expr.strip()
    while len(clean_s) >= 2 and clean_s[0] == '(' and clean_s[-1] == ')':
        depth = 0
        wrapped = True
        for i, ch in enumerate(clean_s):
            depth += (ch == '(') - (ch == ')')
            if depth == 0 and i < len(clean_s) - 1:
                wrapped = False
                break
        if not wrapped:
            break
        expr_s = expr_s[1:-1].strip()
        clean_s = clean_s[1:-1].strip()
    return expr_s, clean_s


def _parse_if_chain(clean, pairs, lo, hi):
    """Parse `if (c1) { b1 } [else if (c2) { b2 }]* [else { bn }]` spanning clean[lo:hi].
    Returns list of (kind, cond_span_or_None, block_open, block_close), or None if not a braced chain.
    """
    arms = []
    at = lo
    first = True
    while at < hi:
        while at < hi and clean[at].isspace():
            at += 1
        if at >= hi:
            break
        if first:
            m = re.match(r'if\b', clean[at:hi])
            if not m:
                return None
            at += m.end()
            first = False
            kind = 'if'
        else:
            m = re.match(r'else\b', clean[at:hi])
            if not m:
                return None
            at += m.end()
            while at < hi and clean[at].isspace():
                at += 1
            m_if = re.match(r'if\b', clean[at:hi])
            if m_if:
                at += m_if.end()
                kind = 'elif'
            else:
                kind = 'else'
        cond_span = None
        if kind in ('if', 'elif'):
            while at < hi and clean[at].isspace():
                at += 1
            if at >= hi or clean[at] != '(':
                return None
            c_start = at + 1
            depth = 0
            while at < hi:
                ch = clean[at]
                depth += (ch == '(') - (ch == ')')
                at += 1
                if depth == 0:
                    break
            if depth != 0:
                return None
            cond_span = (c_start, at - 1)
        while at < hi and clean[at].isspace():
            at += 1
        if at >= hi or clean[at] != '{':
            return None
        b_open = at
        b_close = pairs.get(b_open)
        if b_close is None or b_close >= hi:
            return None
        arms.append((kind, cond_span, b_open, b_close))
        at = b_close + 1
        if kind == 'else':
            while at < hi and clean[at].isspace():
                at += 1
            return arms if at == hi else None
    return arms if arms else None


def _always_returns(clean, pairs, b_open, b_close):
    """True when every path out of `{ ... }` ends at a `return` statement."""
    stmts = statements(clean, b_open + 1, b_close)
    if not stmts:
        return False
    last_lo, last_hi = stmts[-1]
    stmt_clean = clean[last_lo:last_hi].strip()
    if re.match(r'return\b', stmt_clean):
        return True
    if stmt_clean.startswith('{') and pairs.get(last_lo) == last_hi - 1:
        return _always_returns(clean, pairs, last_lo, last_hi - 1)
    chain = _parse_if_chain(clean, pairs, last_lo, last_hi)
    if chain and chain[-1][0] == 'else':
        return all(_always_returns(clean, pairs, ao, ac) for _, _, ao, ac in chain)
    return False


def _parse_ternary_return(source, clean, lo, hi, default_val):
    """If clean[lo:hi] is `return COND ? K : D;` with K != D == default_val, return (cond_text, k_text)."""
    sub_clean = clean[lo:hi]
    m = re.match(r'^\s*return\b', sub_clean)
    if not m or not sub_clean.rstrip().endswith(';'):
        return None
    expr_lo = lo + m.end()
    expr_hi = hi - len(sub_clean) + len(sub_clean.rstrip()) - 1
    expr_src, expr_clean = _strip_outer_parens(source[expr_lo:expr_hi], clean[expr_lo:expr_hi])
    q_pos = None
    c_pos = None
    depth = 0
    for i, ch in enumerate(expr_clean):
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif depth == 0:
            if ch == '?':
                if q_pos is not None:
                    return None
                q_pos = i
            elif ch == ':':
                if q_pos is None or c_pos is not None:
                    return None
                c_pos = i
    if q_pos is None or c_pos is None:
        return None
    cond_src, cond_clean = _strip_outer_parens(expr_src[:q_pos], expr_clean[:q_pos])
    if not cond_clean or '?' in cond_clean:
        return None
    t_src, t_clean = _strip_outer_parens(expr_src[q_pos + 1:c_pos], expr_clean[q_pos + 1:c_pos])
    f_src, f_clean = _strip_outer_parens(expr_src[c_pos + 1:], expr_clean[c_pos + 1:])
    if not (re.fullmatch(_INT_LIT, t_clean) and re.fullmatch(_INT_LIT, f_clean)):
        return None
    if _int_val(f_clean) != default_val or _int_val(t_clean) == default_val:
        return None
    return cond_src, t_src


def _delete_stmt_span(source, lo, hi):
    """Span to delete for statement [lo:hi], consuming its own line whitespace when on a dedicated line."""
    ls = line_start(source, lo)
    if source[ls:lo].strip() == '':
        end = hi
        while end < len(source) and source[end] in ' \t':
            end += 1
        if end < len(source) and source[end] == '\n':
            return (ls, end + 1, '')
        if end + 1 < len(source) and source[end:end + 2] == '\r\n':
            return (ls, end + 2, '')
    return (lo, hi, '')


def _apply_local_edits(text, base_offset, edits):
    if not edits:
        return text
    ordered = sorted(edits, key=lambda item: (item[0], item[1]))
    parts = []
    cursor = 0
    for s, e, rep in ordered:
        rel_s, rel_e = s - base_offset, e - base_offset
        parts.append(text[cursor:rel_s])
        parts.append(rep)
        cursor = rel_e
    parts.append(text[cursor:])
    return ''.join(parts)


def _collect_edits(source, clean, pairs, b_open, b_close, default_val, is_root=False):
    stmts = statements(clean, b_open + 1, b_close)
    if not stmts:
        return []
    edits = []
    work = stmts[:-1] if is_root else list(stmts)

    if not is_root:
        while len(work) >= 2:
            last_lo, last_hi = work[-1]
            lit = _return_lit(clean[last_lo:last_hi])
            if lit is not None and _int_val(lit) == default_val:
                edits.append(_delete_stmt_span(source, last_lo, last_hi))
                work.pop()
            else:
                break

    if not work:
        return edits

    last_lo, last_hi = work[-1]

    # Guarded-return sequence ending in `return K;` (K != default_val)
    if not is_root:
        nondef_lit = _return_lit(clean[last_lo:last_hi])
        if nondef_lit is not None and _int_val(nondef_lit) != default_val and len(work) >= 2:
            seq_arms = []
            idx = len(work) - 2
            while idx >= 0:
                s_lo, s_hi = work[idx]
                chain = _parse_if_chain(clean, pairs, s_lo, s_hi)
                if chain and len(chain) == 1 and chain[0][0] == 'if':
                    _, cond_span, ao, ac = chain[0]
                    if _always_returns(clean, pairs, ao, ac):
                        seq_arms.append((s_lo, s_hi, cond_span, ao, ac))
                        idx -= 1
                        continue
                break
            if seq_arms:
                seq_arms.reverse()
                arm_Rewrites = []
                any_inner_change = False
                for s_lo, s_hi, cond_span, ao, ac in seq_arms:
                    inner_edits = _collect_edits(source, clean, pairs, ao, ac, default_val, is_root=False)
                    if inner_edits:
                        any_inner_change = True
                    cond_txt = source[cond_span[0]:cond_span[1]].strip()
                    body_txt = _apply_local_edits(source[ao:ac + 1], ao, inner_edits)
                    arm_Rewrites.append((cond_txt, body_txt))
                if any_inner_change:
                    ind = indentation(source, seq_arms[0][0])
                    ret_stmt = source[last_lo:last_hi].strip()
                    pieces = []
                    for i, (cond_txt, body_txt) in enumerate(arm_Rewrites):
                        prefix = f'{ind}if ({cond_txt}) ' if i == 0 else f' else if ({cond_txt}) '
                        pieces.append(prefix + body_txt)
                    pieces.append(f' else {{\n{ind}    {ret_stmt}\n{ind}}}')
                    span_start = line_start(source, seq_arms[0][0])
                    if source[span_start:seq_arms[0][0]].strip() != '':
                        span_start = seq_arms[0][0]
                        pieces[0] = pieces[0].lstrip()
                    edits.append((span_start, last_hi, ''.join(pieces)))
                    return edits

        # Ternary `return COND ? K : D;`
        tern = _parse_ternary_return(source, clean, last_lo, last_hi, default_val)
        if tern is not None:
            cond_src, k_src = tern
            ind = indentation(source, last_lo)
            rep = f'if ({cond_src}) {{\n{ind}    return {k_src};\n{ind}}}'
            edits.append((last_lo, last_hi, rep))
            return edits

    # Plain compound block `{ ... }`
    if clean[last_lo:last_hi].lstrip().startswith('{'):
        open_pos = clean.find('{', last_lo, last_hi)
        if pairs.get(open_pos) == last_hi - 1:
            edits.extend(_collect_edits(source, clean, pairs, open_pos, last_hi - 1, default_val, is_root=False))
            return edits

    # Braced `if` / `else if` / `else` chain
    chain = _parse_if_chain(clean, pairs, last_lo, last_hi)
    if chain:
        for _, _, ao, ac in chain:
            edits.extend(_collect_edits(source, clean, pairs, ao, ac, default_val, is_root=False))

    return edits


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    part = plain_repair_view(source, name, header)
    if not part or _DISALLOWED_RE.search(part.body):
        return []
    pairs = brace_pairs(part.clean, part.opening, part.end)
    fn_close = pairs.get(part.opening) if pairs is not None else None
    if fn_close is None or part.clean[fn_close + 1:part.end].strip():
        return []
    top_stmts = statements(part.clean, part.opening + 1, fn_close)
    if len(top_stmts) < 2:
        return []
    ret_lo, ret_hi = top_stmts[-1]
    top_lit = _return_lit(part.clean[ret_lo:ret_hi])
    if top_lit is None:
        return []
    default_val = _int_val(top_lit)
    edits = _collect_edits(source, part.clean, pairs, part.opening, fn_close, default_val, is_root=True)
    if not edits:
        return []
    rewritten = edit(source, edits)
    return [(FAMILY, rewritten)] if rewritten != source else []


REPAIR = {
    'families': FAMILIES,
    'variants': variants,
    'needs': ('source', 'name', 'header', 'flags'),
}
