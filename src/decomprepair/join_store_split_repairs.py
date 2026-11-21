"""A global updated through a shared temporary, stored back directly on each arm.

m2c computes a global's new value into a local on each arm and stores it once at the join:

    if (menuItemIsActive(0x21) & 0xFF) {
        var_s1 = gSceneType + 1;
    } else {
block_12:
        var_s1 = gSceneType - 1;
    }
block_13:
    gSceneType = var_s1;

The local is the function's call-crossing temporary (the same name holds a pointer computed before the calls), so it
lives in a saved register and the `lbu/addiu` pair is computed there. GCC 2.7.2 (an N64 game's own build) wrote the
update on each arm, `gSceneType = gSceneType + 1;` / `- 1`, kept the byte in `$v0` and shared the `lui $at; sb` tail
itself, with the saved register untouched. A local of its own (a fresh `u8`, an `s32`) did not do it (scores 560-2800
against 30): only the stores on the arms did. Seen on a switch function that was 30 points from exact with only
`$v0`/`$s1` differing; exact with this rewrite on both of its joins.

Offered when a statement `G = T;` stores a local `T` that at least two earlier statements assign from an expression
reading `G` (also m2c's split `T = G; T += k;`), and `T` is not mentioned again before the end of the block.
"""
import re

from .csource import _blank, find

FAMILY = 'join_store_split'
FAMILIES = (FAMILY,)


def _locals(body):
    names = set()
    for decl in re.finditer(r'^[ \t]*(?:register\s+)?(?:(?:unsigned|signed|long|short|const|volatile|struct|union|enum)\s+)*'
                            r'[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)?\s+([^;(){}=]*(?:=[^;]*)?);', body, re.M):
        for part in decl[1].split(','):
            name = re.match(r'\s*\**\s*(\w+)', part)
            if name:
                names.add(name[1])
    return names


def _block_end(clean, at):
    """Index of the `}` that closes the block `at` sits in."""
    depth = 0
    for i in range(at, len(clean)):
        if clean[i] == '{':
            depth += 1
        elif clean[i] == '}':
            if depth == 0:
                return i
            depth -= 1
    return len(clean)


class _Shifted:
    """A match found in a slice, read with the slice's offset added back."""

    def __init__(self, match, shift):
        self.match, self.shift = match, shift

    def __getitem__(self, i):
        return self.match[i] if i <= self.match.re.groups else None

    def start(self):
        return self.match.start() + self.shift

    def end(self):
        return self.match.end() + self.shift


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    start, end = span
    body, clean = source[start:end], _blank(source)[start:end]
    declared = _locals(body)
    for store in re.finditer(r'^([ \t]*(?:\w+:\s*)?)(\w+) = (\w+);[ \t]*$', clean, re.M):
        target, temp = store[2], store[3]
        if temp not in declared or target in declared or temp == target:
            continue
        before = clean[:store.start()]
        feeds = []
        for pair in re.finditer(rf'^([ \t]*)({temp}) = ([^;\n]*\b{target}\b[^;\n]*);(?:[ \t]*\n?[ \t]*{temp} ([-+|&^]|<<|>>)= ([^;\n]+);)?', before, re.M):
            feeds.append(pair)
        pairs = [m for m in re.finditer(rf'^([ \t]*)({temp}) = ({target});\s*{temp} ([-+|&^]|<<|>>)= ([^;\n]+);', before, re.M)]
        spans = {m.start() for m in pairs}
        feeds = [m for m in feeds if m.start() in spans or not m[4]]
        if len(feeds) < 2:
            continue
        stop = _block_end(clean, store.end())
        ends = re.search(r'\b(?:case|default|break|return)\b', clean[store.end():stop])
        stop = store.end() + ends.start() if ends else stop
        if re.search(rf'\b{temp}\b', clean[store.end():stop]):
            continue
        label = re.search(r'(\w+):\s*$', store[1])
        out = body
        edits = []
        for m in feeds:
            if m[4]:
                edits.append((m.start(), m.end(), f'{m[1]}{target} = {m[3]} {m[4]} {m[5]};'))
            else:
                edits.append((m.start(), m.end(), f'{m[1]}{target} = {m[3]};'))
        edits.append((store.start(), store.end(), f'{store[1]};' if store[1].strip() else ''))
        if label:
            # Another arm that borrows the join: `if (c) { T = E1; } else { goto A; } goto J;`, A being a feed above.
            # It writes its own copy of both stores and of what follows the join, as the compiler has them.
            tail = re.sub(r'^[ \t]*\w+:[ \t]*\n?', '', body[store.end():stop].strip('\n'), flags=re.M)
            for m in re.finditer(rf'^([ \t]*)if \(([^\n]*)\) \{{\s*{temp} = ([^;\n]*\b{target}\b[^;\n]*);\s*\}} else \{{\s*goto (\w+);\s*\}}\s*goto {label[1]};',
                                 clean[store.end():], re.M):
                feed = next((f for f in feeds if re.search(rf'{m[4]}:\s*$', clean[:f.start()])), None)
                if feed is None:
                    continue
                other = f'{feed[3]} {feed[4]} {feed[5]}' if feed[4] else feed[3]
                at = store.end()
                ind = m[1]
                text = (f'{ind}if ({m[2]}) {{\n{ind}    {target} = {m[3]};\n{ind}}} else {{\n{ind}    {target} = {other};\n{ind}}}\n'
                        + tail)
                edits.append((at + m.start(), at + m.end(), text))
        for lo, hi, text in sorted(edits, reverse=True):
            out = out[:lo] + text + out[hi:]
        result = source[:start] + out + source[end:]
        if result != source:
            return [(FAMILY, result)]
    return []
