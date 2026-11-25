"""A narrow loop counter that a `switch` dispatches on: an `s32` copy of it at the top of the loop body.

    s16 j;                                         s16 j; s32 jj;
    for (j = 0; j < 3; j++) {                      for (j = 0; j < 3; j++) {
        do { do { SLOT(j) = 0; } while (0); }          do { jj = j; } while (0);
            while (0);                                 SLOT(jj) = 0;
        if (g && j == 1) continue;           ->        if (g && jj == 1) continue;
        SLOT(j) = f(e);                                do { SLOT(jj) = f(e); } while (0);
        if (SLOT(j)) switch (j) { ... }                if (SLOT(jj)) switch (jj) { ... }

KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`). Every use of an `s16` counter is a fresh `sign_extend` of its
HImode pseudo, and `expand_end_case` copies the switch's index into a new pseudo (`(set (reg 264) (reg 141))` in
the `.cse` dump). When cse's path reaches the dispatch from the loop top the copy is folded away; when a loop note
(`do { } while (0)`, cse.c `cse_end_of_basic_block` stops at NOTE_INSN_LOOP_END before loop.c) ends the path
first, the dispatch recomputes the extension, cse2 turns it into a copy of the first one and the copy survives as a
`move $v1, $s0` with the dispatch reading `$v1` (both live: global.c cannot tie them). Without the note the copy
goes, but the loop then has fewer insns and loop.c (`move_movables`: `threshold * savings * lifetime >=
insn_count`) hoists a float constant the target keeps in its arm. An `s32` user variable set from the counter
at the top of the body is one pseudo every use and the dispatch reads directly (no index copy), so the notes the
constants need can stay: around the copy, which also weighs the counter's references (its register against a
sign-extended `s16` parameter copy at 0.27 against 0.28), and around the call statement before the dispatch,
which keeps loop.c's count where the target's is.

Measured with the exact judge on a 534-instruction menu builder (two outer loops, a `for (j = 0; j < 3; j++)`
over an `s16 j` with a three-arm `switch (j)`): the saved best 255 (the `move` and three register rows, an arm's
float pair swapped, one hoisted `la` order); the copy with the old wrappers 1427 (34.0f hoisted); with the call
statement wrapped 190 (the move, the hoisted constant and the `la` order fixed); with the copy wrapped and the
first statement's wrappers moved onto it 140.

Children, for a `for` loop whose counter is declared `s16`, `short`, `u16`, `unsigned short`, `s8`, `u8` or
`char`, that the loop body never assigns and that a `switch` in the body dispatches on: the copy at the top of the
body with every use renamed (one child), the copy wrapped in `do { } while (0);` (a second), that with the
wrappers of the simple statements between the copy and the switch taken off (a third), and each of the three with
one statement that calls a function (between the copy and the switch, not already wrapped) wrapped. The judge
decides every child.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'switch_index_wide_copy'
FAMILIES = (FAMILY,)
_NARROW = r'(?:s16|u16|s8|u8|short|unsigned\s+short|signed\s+short|char|signed\s+char|unsigned\s+char)'
_WRAP = re.compile(r'(?P<open>(?:do\s*\{\s*)+)(?P<body>[^{};]*;)(?P<close>(?:\s*\}\s*while\s*\(\s*0\s*\)\s*;)+)')


def _python_match(clean, at):
    """The index of the bracket that closes the one at `at`."""
    depth = 0
    pair = {'(': ')', '{': '}'}[clean[at]]
    for i in range(at, len(clean)):
        if clean[i] == clean[at]:
            depth += 1
        elif clean[i] == pair:
            depth -= 1
            if depth == 0:
                return i
    return -1


_match = _python_match
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _match(clean, at):
        opener = clean[at]
        closer = {'(': ')', '{': '}'}[opener]
        found = _scan.close_if(clean, at, opener, closer, -1)
        return _python_match(clean, at) if found is NotImplemented else found


def _fresh(clean, base):
    for name in (base * 2, base + '_index', base + '_wide', base + '_copy'):
        if not re.search(rf'\b{re.escape(name)}\b', clean):
            return name
    return None


def _loops(part):
    """(counter, body opening brace, body closing brace) for each narrow-counter `for` loop with a `switch` on it."""
    clean = part.clean
    for hit in re.finditer(rf'\bfor\s*\(\s*(?P<v>{IDENT})\s*=', clean[:part.end]):
        if hit.start() < part.opening:
            continue
        var = hit['v']
        if not re.search(rf'(?:[;{{}}(,]|^)\s*{_NARROW}\s+(?:[\w\s,*]*,\s*)?{re.escape(var)}\s*[;,=]',
                         clean[part.opening:hit.start()], re.M):
            continue
        head = clean.index('(', hit.start())
        close = _match(clean, head)
        rest = clean[close + 1:]
        lead = len(rest) - len(rest.lstrip())
        if close < 0 or not rest.lstrip().startswith('{'):
            continue
        opening = close + 1 + lead
        end = _match(clean, opening)
        body = clean[opening:end]
        if not re.search(rf'\bswitch\s*\(\s*{re.escape(var)}\s*\)', body):
            continue
        if re.search(rf'(?<![\w.>]){re.escape(var)}\s*(?:=(?!=)|\+\+|--|[-+*/%&|^]=|<<=|>>=)'
                     rf'|(?:\+\+|--)\s*{re.escape(var)}\b|&\s*{re.escape(var)}\b', body):
            continue
        yield var, opening, end


def _rename(text, clean, old, new):
    """`text` with `old` renamed `new` where `clean` (the same span, comments and strings blanked) names it."""
    out, last = [], 0
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(old)}\b', clean):
        out.append(text[last:hit.start()] + new)
        last = hit.end()
    return ''.join(out) + text[last:]


def _children(source, part, var, opening, end):
    clean = part.clean
    new = _fresh(clean, var)
    if not new:
        return []
    decl = re.search(rf'(?m)^(?P<lead>[ \t]*){_NARROW}\s+{re.escape(var)}\s*;[^\n]*\n', clean[part.opening:opening])
    if not decl:
        return []
    decl_end = part.opening + decl.end()
    lead = decl['lead']
    switch = re.search(rf'\bswitch\s*\(\s*{re.escape(var)}\s*\)', clean[opening:end]).start() + opening
    body, cbody = source[opening + 1:end], clean[opening + 1:end]
    indent = re.match(r'\n?([ \t]*)', body[body.find('\n'):] if '\n' in body else '')
    pad = indent.group(1) if indent else '    '
    split = switch - opening - 1
    before, after = body[:split], body[split:]
    cbefore, cafter = cbody[:split], cbody[split:]

    def assemble(copy, head, chead):
        text = source[:decl_end] + f'{lead}s32 {new};\n' + source[decl_end:opening + 1]
        renamed = _rename(head, chead, var, new) + _rename(after, cafter, var, new)
        return text + f'\n{pad}{copy}' + renamed + source[end:]

    plain, wrapped = f'{new} = {var};', f'do {{ {new} = {var}; }} while (0);'
    heads = [(plain, before, cbefore), (wrapped, before, cbefore)]
    spans = [(m.start(), m.end(), m.start('body'), m.end('body')) for m in _WRAP.finditer(cbefore)]
    if spans:
        head, chead, last = [], [], 0
        for start, stop, inner, inner_end in spans:
            head.append(before[last:start] + before[inner:inner_end])
            chead.append(cbefore[last:start] + cbefore[inner:inner_end])
            last = stop
        heads.append((wrapped, ''.join(head) + before[last:], ''.join(chead) + cbefore[last:]))
    out = [assemble(*one) for one in heads]
    for copy, head, cleaned in heads:
        for stmt in re.finditer(r'(?m)^(?P<lead>[ \t]*)(?P<s>[^;{}\n]*\b[A-Za-z_]\w*\s*\([^;{}]*\)[^;{}]*;)', cleaned):
            text = stmt['s']
            if re.match(r'\s*(?:if|while|for|switch|return|do)\b', text) or '(' not in text:
                continue
            if re.search(r'\bdo\s*\{\s*$', cleaned[:stmt.start('s')]):
                continue
            at, stop = stmt.start('s'), stmt.end('s')
            changed = head[:at] + f'do {{ {head[at:stop]} }} while (0);' + head[stop:]
            cchanged = cleaned[:at] + f'do {{ {cleaned[at:stop]} }} while (0);' + cleaned[stop:]
            out.append(assemble(copy, changed, cchanged))
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for var, opening, end in _loops(part):
        out.extend(_children(source, part, var, opening, end))
    return [(FAMILY, child) for child in dict.fromkeys(out) if child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
