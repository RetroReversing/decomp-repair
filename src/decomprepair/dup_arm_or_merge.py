"""An `||` the decompiler split into nested `if`s that write one arm twice, or jump past it, written back as one.

m2c writes `if (a || b) T else S` in whichever way it walked the branches: as `if (!a) { if (!b) S else T } else T`
(the arm `T` twice), or as `if (!a) { if (!b) { S; goto end; } } T` where the code after `T` is `end`. Both compile to
other branches than the `||` does (a `j`/`nop` pair where the target has a branch-likely, or the reverse), because
jump.c sees two copies of `T` where the source had one body reached by two tests. In one SN GCC 2.8.1 `-O2` function of
74 instructions the draft had both spellings, each in an arm of its own: rewriting either alone scored worse (1200 and
1460 against 860), both together were byte-identical. Hence one child with every site rewritten.

The m2c draft often stages the inner test's operands first (`v = G; k = 2; if (v != k)`): the staged locals are put
back into the test when no other read of them can see the staged value.

dup_arm_or_merge
    `if (a || b) T else S`: every site, then each alone.
dup_arm_and_merge
    The same tests written as `if (!a && !b) S else T`, which GCC lays out with `S` first.
"""
import re

from .c_scan import close, enclosing_block, header_before
from .csource import _blank, find

FAMILY = 'dup_arm_or_merge'
AND_FAMILY = 'dup_arm_and_merge'
FAMILIES = (FAMILY, AND_FAMILY)
LIMIT = 10
_IF = re.compile(r'\bif\s*\(')
_ELSE = re.compile(r'\s*else\b\s*')
_ASSIGN = re.compile(r'\s*([A-Za-z_]\w*)\s*=(?!=)\s*([^;{}=]*?)\s*;')
_LABEL = re.compile(r'(?m)^\s*(?!default\b|case\b)[A-Za-z_]\w*\s*:(?!:)')
_GOTO_END = re.compile(r'\bgoto\s+([A-Za-z_]\w*)\s*;\s*$')
_CASE = re.compile(r'\b(?:case|default)\b')
_OPPOSITE = {'==': '!=', '!=': '==', '<': '>=', '>=': '<', '>': '<=', '<=': '>'}
_COMPARE = re.compile(r'(?<![<>\-=!])(==|!=|<=|>=|<|>)(?![<>=])')
_SIMPLE = re.compile(r'!?\s*(?:[A-Za-z_]\w*|\d\w*)\Z')


def _skip(clean, at):
    while at < len(clean) and clean[at].isspace():
        at += 1
    return at


def _parse(clean, at):
    """(condition start, condition end, then `{`, then `}`, else `{` or -1, else `}` or -1) of the braced `if` at `at`."""
    match = _IF.match(clean, at)
    if not match:
        return None
    end = close(clean, match.end() - 1, '(', ')')
    if end < 0:
        return None
    opening = _skip(clean, end + 1)
    if not clean.startswith('{', opening):
        return None
    closing = close(clean, opening)
    if closing < 0:
        return None
    other = _ELSE.match(clean, closing + 1)
    if not other:
        return match.end(), end, opening, closing, -1, -1
    if not clean.startswith('{', other.end()):
        return None
    tail = close(clean, other.end())
    return (match.end(), end, opening, closing, other.end(), tail) if tail >= 0 else None


def _parenthesised(text):
    return text.startswith('(') and close(text, 0, '(', ')') == len(text) - 1


def _top(condition):
    """The condition with everything inside brackets blanked."""
    out, depth = [], 0
    for char in condition:
        depth -= char in ')]'
        out.append(char if depth == 0 else ' ')
        depth += char in '(['
    return ''.join(out)


def _negate(condition):
    text = condition.strip()
    while _parenthesised(text):
        text = text[1:-1].strip()
    if text.startswith('!') and not text.startswith('!='):
        rest = text[1:].strip()
        if _parenthesised(rest):
            return rest[1:-1].strip()
        if _SIMPLE.match(rest):
            return rest
    top = _top(text)
    found = list(_COMPARE.finditer(top))
    if len(found) == 1 and not any(mark in top for mark in ('&&', '||', '?', ',')):
        match = found[0]
        # `a & b == c` binds the comparison first, so exchanging it stays the negation only without such operators
        if not re.search(r'(?<!&)&(?!&)|(?<!\|)\|(?!\|)|\^', top):
            return text[:match.start()] + _OPPOSITE[match.group(1)] + text[match.end():]
    return f'!{text}' if _SIMPLE.match(text) and not text.startswith('!') else f'!({text})'


def _join(first, second, operator):
    parts = [p if _SIMPLE.match(p) or _parenthesised(p) or p.startswith('!') and _parenthesised(p[1:].strip())
             else f'({p})' for p in (first.strip(), second.strip())]
    return f' {operator} '.join(parts)


def _read_elsewhere(clean, lo, hi, variable, removed):
    """Whether some read of `variable` outside `removed` spans might see the value a removed assignment gave it."""
    for match in re.finditer(rf'(?<![\w.])(?<!->){variable}\b', clean[lo:hi]):
        at = lo + match.start()
        if any(a <= at < b for a, b in removed):
            continue
        before = clean[lo:at].rstrip()
        if before.endswith('&') and not before.endswith('&&'):
            return True
        after = clean[lo + match.end():hi]
        if re.match(r'\s*=(?!=)', after):
            continue
        if re.search(r'[\w*]\s*$', before) and re.match(r'\s*;', after) and not re.search(r'\breturn\s*$', before):
            statement = before[max(before.rfind(';'), before.rfind('{'), before.rfind('}')) + 1:]
            if re.fullmatch(r'\s*(?:(?:unsigned|signed|register|struct)\s+)*\w+[\s*]*', statement):
                continue  # its declaration
        if not _assigned_before(clean, lo, at, variable, removed):
            return True
    return False


def _assigned_before(clean, lo, at, variable, removed):
    """Whether a kept `variable = ...;` in this block or one around it comes first, with no label between."""
    for match in reversed(list(re.finditer(rf'(?<=[;{{}}])\s*{variable}\s*=(?!=)', clean[lo:at]))):
        start, end = lo + match.start(), lo + match.end()
        if any(a <= end - 1 < b for a, b in removed):
            continue
        block = enclosing_block(clean, start, lo)
        if block >= 0 and close(clean, block) < at:
            continue  # it sits in a block that is closed by now
        if ';' not in clean[end:at] or _LABEL.search(clean, start, at):
            return False
        return True
    return False


def _local(clean, lo, hi, variable):
    return bool(re.search(rf'(?m)^[ \t]*(?:(?:unsigned|signed|register|struct)[ \t]+)*(?!return\b|goto\b)[A-Za-z_]\w*'
                          rf'[ \t*]+{variable}[ \t]*;', clean[lo:hi]))


def _staged(source, clean, lo, hi, block):
    """The nested `if` of a block that holds only staged assignments before it: (position, condition, parsed), or None."""
    opening, closing = block
    at, staged = opening + 1, []
    while (match := _ASSIGN.match(clean, at, closing)):
        staged.append((match.group(1), source[match.start(2):match.end(2)], match.start(), match.end()))
        at = match.end()
    at = _skip(clean, at)
    parsed = _parse(clean, at)
    if not parsed:
        return None
    end = parsed[5] if parsed[4] >= 0 else parsed[3]
    if clean[end + 1:closing].strip():
        return None
    condition = source[parsed[0]:parsed[1]]
    removed = [(a, b) for _, _, a, b in staged] + [(parsed[0], parsed[1])]
    for variable, value, _, _ in reversed(staged):
        uses = list(re.finditer(rf'(?<![\w.])(?<!->){variable}\b', condition))
        if (len(uses) != 1 or re.search(r'[A-Za-z_]\w*\s*\(|\+\+|--', value) or not _local(clean, lo, hi, variable)
                or _read_elsewhere(clean, lo, hi, variable, removed)):
            return None
        value = value if _SIMPLE.match(value) or _parenthesised(value) else f'({value})'
        condition = condition[:uses[0].start()] + value + condition[uses[0].end():]
    return at, condition, parsed


def _plain_block(clean, opening):
    """Whether the block at `opening` is a bare block or an `if` or `else` arm: leaving it runs on, never loops."""
    header = header_before(clean, opening)
    header = re.sub(r'\Aelse\b\s*', '', header)
    if not header:
        return True
    match = _IF.match(header)
    return bool(match) and close(header, match.end() - 1, '(', ')') == len(header) - 1


def _falls_to(clean, closing, label, lo):
    """Whether control leaving the block that ends at `closing` runs straight to `label:`."""
    at = closing + 1
    while True:
        at = _skip(clean, at)
        if re.compile(rf'{label}\s*:(?!:)').match(clean, at):
            return True
        other = _ELSE.match(clean, at)
        if other:
            at = other.end()
            if clean.startswith('if', at):
                match = _IF.match(clean, at)
                end = close(clean, match.end() - 1, '(', ')') if match else -1
                if end < 0:
                    return False
                at = _skip(clean, end + 1)
            if not clean.startswith('{', at):
                return False
            at = close(clean, at) + 1
            if at <= 0:
                return False
            continue
        if not clean.startswith('}', at):
            return False
        opening = enclosing_block(clean, at, lo)
        if opening < 0 or not _plain_block(clean, opening):
            return False
        at += 1


def _text(source, opening, closing):
    return source[opening + 1:closing]


def _same(left, right):
    return ' '.join(left.split()) == ' '.join(right.split())


def _site(source, clean, lo, hi, at):
    """(start, end, condition for the shared arm, shared arm, other condition, other arm) at the `if` at `at`."""
    outer = _parse(clean, at)
    if not outer:
        return None
    first, last, opening, closing, other, tail = outer
    condition = source[first:last]
    if other >= 0:
        for nested, plain, reach in (((opening, closing), (other, tail), _negate(condition)),
                                     ((other, tail), (opening, closing), condition)):
            inner = _staged(source, clean, lo, hi, nested)
            if not inner or inner[2][4] < 0:
                continue
            _, test, parsed = inner
            shared = _text(source, *plain)
            then, otherwise = _text(source, parsed[2], parsed[3]), _text(source, parsed[4], parsed[5])
            if not shared.strip() or _CASE.search(clean, opening, tail):
                continue
            if _same(then, shared):
                test_for, rest = test, otherwise
            elif _same(otherwise, shared):
                test_for, rest = _negate(test), then
            else:
                continue
            if _LABEL.search(_blank(shared)) or _LABEL.search(_blank(rest)):
                continue
            return at, tail + 1, (reach, test_for), shared, rest
        return None
    inner = _staged(source, clean, lo, hi, (opening, closing))
    if not inner or inner[2][4] >= 0:
        return None
    _, test, parsed = inner
    body = _text(source, parsed[2], parsed[3]).rstrip()
    jump = _GOTO_END.search(body)
    block = enclosing_block(clean, at, lo)
    if not jump or block < 0:
        return None
    end = close(clean, block)
    rest = source[closing + 1:end]
    label = jump.group(1)
    if end < 0 or not rest.strip() or not _falls_to(clean, end, label, lo) or _CASE.search(clean, at, end):
        return None
    rest = re.sub(rf'\bgoto\s+{label}\s*;\s*$', '', rest.rstrip())
    if not _plain_block(clean, block) or not rest.strip() or _LABEL.search(_blank(body)):
        return None
    return at, end, (_negate(condition), _negate(test)), rest, body[:jump.start()]


def _braced(text, indent):
    return '{\n' + text.strip('\n').rstrip() + f'\n{indent}}}'


def _write(source, site, family):
    start, end, (first, second), shared, rest = site
    indent = source[source.rfind('\n', 0, start) + 1:start]
    indent = indent if not indent.strip() else ''
    if family == FAMILY:
        head, one, two = _join(first, second, '||'), shared, rest
    else:
        head, one, two = _join(_negate(first), _negate(second), '&&'), rest, shared
    text = f'if ({head}) {_braced(one, indent)}'
    if two.strip():
        text += f' else {_braced(two, indent)}'
    # the goto form runs to its block's closing brace, whose own indentation was part of the replaced text
    if source.startswith('}', end):
        text += '\n' + indent[:-4]
    return source[:start] + text + source[end:]


def _sites(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    lo, hi = clean.find('{', span[0]), span[1]
    sites, done = [], lo
    for match in _IF.finditer(clean, lo, hi):
        if match.start() < done:
            continue
        site = _site(source, clean, lo, hi, match.start())
        if site:
            sites.append(site)
            done = site[1]
    return sites


def variants(source, name):
    sites = _sites(source, name) if 'if' in source else []
    if not sites:
        return []
    result = []
    for family in FAMILIES:
        every = source
        for site in reversed(sites):
            every = _write(every, site, family)
        result.append((family, every))
    if len(sites) > 1:
        result += [(family, _write(source, site, family)) for family in FAMILIES for site in sites]
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
