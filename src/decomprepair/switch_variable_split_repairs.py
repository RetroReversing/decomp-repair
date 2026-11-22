"""A local that holds one value before a `switch` and unrelated ones inside it, split in two.

m2c reuses a variable's name whenever the value it held is dead, so the selector of a switch came back as

    temp_v1 = *(s16 *)(state + 0x7A);
    switch (temp_v1) {
        case 3:  ...  temp_v1 = 4;  goto done;
        ...
        done:  *(s16 *)(ptr + 0x7A) = temp_v1;

and the pointer that was loaded for the first statements was loaded again at each exit under the same name. GCC
2.7.2 gives a variable one pseudo register for all of its uses, so the selector (and the pointer) stay live through
every arm, the arms' own moves are pushed to other registers, and the tails come out as `lw $a2 / li $a1` where the
game's code has `lw $v1 / li $v0` (a function 1,200 points off; exact once the arms' values had their own names).
Split, the arm values are short pseudos that get the first free registers, as in the game.

Offered for each local that is mentioned before the switch, whose first mention inside the switch body is an
assignment, whose every read inside the body comes after an assignment there, and that nothing mentions after the
switch: its mentions inside the body are renamed to a new variable of the same type, declared next to the old one.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'switch_variable_split'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
_DECLARATION = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<type>[A-Za-z_][\w \t*]*?[ \t*])(?P<name>' + IDENT + r')[ \t]*;[ \t]*$')
_KEYWORDS = {'return', 'goto', 'break', 'continue', 'else', 'case', 'default', 'register'}
_SWITCH = re.compile(r'\bswitch\s*\(')
LIMIT = 6


def _mentions(text, name):
    return [m for m in re.finditer(r'(?<![\w.>])' + re.escape(name) + r'\b', text)]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    text = source[span[0]:span[1]]
    clean = _blank(text)
    result = []
    for switch in _SWITCH.finditer(clean):
        paren = close(clean, switch.end() - 1, '(', ')')
        brace = clean.find('{', paren) if paren else -1
        if brace < 0 or clean[paren:brace].strip():
            continue
        end = close(clean, brace, '{', '}')
        if not end:
            continue
        head, body, after = clean[:switch.start()], clean[brace:end], clean[end:]
        for decl in _DECLARATION.finditer(head):
            var, kind = decl['name'], decl['type'].strip()
            if var in _KEYWORDS or kind.split()[0] in _KEYWORDS or kind.startswith('register'):
                continue
            inside = _mentions(body, var)
            before = [m for m in _mentions(head, var) if m.start() != decl.start('name')]
            if not inside or not before or _mentions(after, var):
                continue
            writes = [bool(re.match(r'\s*=(?!=)', body[m.end():])) for m in inside]
            if not writes[0]:
                continue
            first_write = next(i for i, w in enumerate(writes) if w)
            if any(not w for w in writes[:first_write]):
                continue
            fresh = var + '_arm'
            while fresh in clean:
                fresh += '_'
            renamed = re.sub(r'(?<![\w.>])' + re.escape(var) + r'\b', fresh, text[brace:end])
            rewritten = text[:decl.end()] + '\n' + decl['indent'] + kind + ' ' + fresh + ';' + text[decl.end():brace] + \
                renamed + text[end:]
            result.append((FAMILY, source[:span[0]] + rewritten + source[span[1]:]))
            if len(result) >= LIMIT:
                return result
    return result
