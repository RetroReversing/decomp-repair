"""A local that only caches a plain memory read, written as the read itself where it is used.

m2c (and the permuter's own staging families) cache a field in a local at the head of a loop and again at its end:

    s1 = p->head;                            while (p->head - p->tail < p->size - 0xA0 && budget > 0)
    v1 = s1 - p->tail;               ->      {
    s2 = p->size;                                step(p->ring + ((p->head % p->size) >> 2) * 8);
    while (v1 < s2 - 0xA0 && budget > 0)         p->head += 0xA0;
    {                                            budget--;
      step(p->ring + ((s1 % s2) >> 2) * 8);  }
      p->head += 0xA0;
      s1 = p->head; v1 = s1 - p->tail; s2 = p->size;
      budget--;
    }

The cached form pins a value in a register across the loop and orders the three loads at the loop head the way the
source says (`s1`, then `s2`, then `tail`); the plain reads leave both to the compiler, which loads left to right and
folds the repeats. In a 222-instruction stream refill built by IDO 7.1 the cached form stood at 555 (load order and the
second loop's registers) and the plain reads at 60, the rest being `guard_prefix_while` (60 -> 0). Whether a given
compiler prefers the plain reads is a hypothesis for the judge; the rewrite itself is the same program when every use of
the local sees the value its definition read, which is what the checks below prove from the text:

* the local is assigned only as `t = E;` with `E` free of calls, assignments, `++`/`--`, `volatile` and `t` itself;
* every use of the local is reached, walking back through the lines above it, by one definition of it with nothing
  between that stores to memory, calls, jumps out, assigns a local named in `E`, or defines the local again in a
  block that may be skipped (a block that does none of that is stepped over whole);
* a use inside a loop is also reached, through the loop's back edge, by a definition with the same `E` at the end of
  the loop body, and the loop has no `continue`, `goto` or label;
* a line that uses it and also calls or stores has one call at most and the use is among that call's arguments (a
  call to an inline helper of the source whose body is one pure `return E;` does not count: it is the expression).

Children (one per local the checks accept, in the order they are found, then all of them together): the local's
definitions are deleted, its uses become `E` (in parentheses unless it is a plain name or a field read), and its name
leaves the declaration. Locals that read other such locals are taken after them, so a chain (`v1 = s1 - p->tail`)
goes with its members in the combined child.
"""
import re

from .integer_repair_support import edit, view
from .line_scan import block_end, block_start, lines, mentions, words

FAMILY = 'reload_temp_inline'
FAMILIES = (FAMILY,)
LIMIT = 6
_DEF = re.compile(r'(?P<t>[A-Za-z_]\w*) = (?P<e>[^;]*);')
_EFFECT = re.compile(r'[A-Za-z_]\w*\s*\(|\+\+|--|\bvolatile\b|(?<![=!<>])=(?!=)')
_CALL = re.compile(r'[A-Za-z_]\w*\s*\(')
_HEADER = re.compile(r'(?:if|while|for)\s*\(.*\)|else(?:\s+if\s*\(.*\))?|do')
_TYPES = frozenset('''s8 u8 s16 u16 s32 u32 s64 u64 f32 f64 int char short long unsigned signed float double register'''.split())
_DECL = re.compile(r'(?:[A-Za-z_]\w*[ \t]+)+\**[ \t]*[A-Za-z_]\w*(?:[ \t]*,[ \t]*\**[ \t]*[A-Za-z_]\w*)*;')


def _plain(e):
    return re.fullmatch(r'[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*|-?(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*', e.strip()) is not None


def _pure(e):
    return not _EFFECT.search(e)


def _header_condition(s):
    m = re.match(r'(?:else\s+)?(?:if|while|for)\s*\((.*)\)\s*;?$', s)
    return m[1] if m else ''


_HELPER = re.compile(r'\b(?:static\s+inline|inline\s+static|inline)\s+[^;{}()]*?\b(?P<name>[A-Za-z_]\w*)\s*\([^;{}()]*\)\s*'
                     r'\{\s*return\s+(?P<e>[^;{}]*);\s*\}')


def _pure_helpers(text):
    """Inline helpers above the function whose whole body is `return E;` with `E` free of calls and assignments.

    A call to one reads its arguments and nothing else, so it is no more a call than the expression it stands for
    (`temp + scaled_offset(x)` in an argument list); m2c and the permuter's own families write such helpers."""
    return tuple(m['name'] for m in _HELPER.finditer(text) if _pure(m['e']))


class _Function:
    def __init__(self, source, name):
        part = view(source, name)
        self.ok = part is not None
        if not self.ok:
            return
        self.source, self.part = source, part
        self.helpers = _pure_helpers(part.clean[:part.opening])
        self.body = lines(part, source)
        signature = part.clean[:part.opening]
        params = signature[signature.rfind('(') + 1:].rstrip().rstrip(')')
        self.locals = {m[1] for m in re.finditer(r'(\w+)\s*(?:,|$)', params)} if params.strip() not in ('', 'void') else set()
        declared = set()
        self.declarations = set()
        for k, line in enumerate(self.body):
            s = line.stripped
            if _DECL.fullmatch(s) and not re.match(r'(?:return|goto|else|case)\b', s):
                self.declarations.add(k)
                declared |= {n for n in re.findall(r'[A-Za-z_]\w*', s) if n not in _TYPES}
        # the first word of a declaration is its type, and a typedef name is not a local
        for line in self.body:
            s = line.stripped
            if _DECL.fullmatch(s) and not re.match(r'(?:return|goto|else|case)\b', s):
                declared.discard(re.findall(r'[A-Za-z_]\w*', s)[0])
        self.locals |= declared
        text = '\n'.join(l.text for l in self.body)
        self.locals = {n for n in self.locals if not re.search(rf'(?<!&)&\s*{re.escape(n)}\b', text)}
        self.assigned = set()
        for line in self.body:
            for m in re.finditer(r'(?<![\w.>])([A-Za-z_]\w*)\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', line.text):
                self.assigned.add(m[1])
            for m in re.finditer(r'(?<![\w.>])([A-Za-z_]\w*)\s*(?:\+\+|--)|(?:\+\+|--)\s*([A-Za-z_]\w*)', line.text):
                self.assigned.add(m[1] or m[2])

    # -- classification of single lines ------------------------------------------------------------------------
    def structural(self, s):
        if s in ('{', '}', 'else', 'do'):
            return True
        header = _HEADER.fullmatch(s.rstrip(';').strip())
        return bool(header) and _pure(_header_condition(s))

    def local_set(self, s, avoid):
        """`x = E;`, `x op= E;`, `x++;` or `--x;` on a plain local `x` that is not in `avoid`, with `E` pure."""
        m = re.fullmatch(r'(?P<t>[A-Za-z_]\w*) (?:[-+*/%&|^]|<<|>>)?= (?P<e>[^;]*);|(?P<u>[A-Za-z_]\w*)(?:\+\+|--);|'
                         r'(?:\+\+|--)(?P<v>[A-Za-z_]\w*);', s)
        if not m:
            return False
        x = m['t'] or m['u'] or m['v']
        return x in self.locals and x not in avoid and _pure(m['e'] or '')

    def quiet(self, low, high, t, avoid):
        """Lines low..high change no memory, jump nowhere, and assign neither `t` nor a name in `avoid`."""
        for k in range(low, high + 1):
            s = self.body[k].stripped
            if not (self.structural(s) or self.local_set(s, avoid | {t})):
                return False
        return True

    # -- the walk back ---------------------------------------------------------------------------------------
    def reach(self, start, t, avoid, depth=0):
        """(index, E) of the definition of `t` that reaches the top of line `start` (walking lines start-1, ...)."""
        return self.scan(start - 1, t, avoid, depth)

    def scan(self, i, t, avoid, depth=0):
        body = self.body
        while i >= 0:
            s = body[i].stripped
            d = _DEF.fullmatch(s)
            if d and d['t'] == t:
                return (i, d['e'].strip()) if _pure(d['e']) and not mentions(d['e'], t) else None
            if s == '}':
                low = block_start(body, i)
                if low is None:
                    return None
                header = body[low - 1].stripped if low else ''
                if re.fullmatch(r'do|(?:while|for)\s*\(.*\)', header) and not self.quiet(low, i, t, avoid):
                    # a loop above the line: the value comes from its end (it ran) or from before it (it did not)
                    if depth > 2 or self.jumps(low, i):
                        return None
                    ran = self.scan(i - 1, t, avoid, depth + 1)
                    entry = self.scan(low - 2 if header == 'do' else low - 1, t, avoid, depth)
                    if not ran or not entry or ' '.join(ran[1].split()) != ' '.join(entry[1].split()):
                        return None
                    return entry
                if not self.quiet(low, i, t, avoid):
                    if depth > 2 or self.jumps(low, i):
                        return None
                    if re.fullmatch(r'if\s*\(.*\)', header):
                        # a conditional block above the line: the value comes through it or around it
                        ran = self.scan(i - 1, t, avoid, depth + 1)
                        entry = self.scan(low - 2, t, avoid, depth)
                    elif header == 'else' and low >= 2 and body[low - 2].stripped == '}':
                        then = block_start(body, low - 2)
                        if then is None or not re.fullmatch(r'if\s*\(.*\)', body[then - 1].stripped if then else ''):
                            return None
                        ran = self.scan(i - 1, t, avoid, depth + 1)
                        entry = self.scan(low - 3, t, avoid, depth + 1)
                    else:
                        return None
                    if not ran or not entry or ' '.join(ran[1].split()) != ' '.join(entry[1].split()):
                        return None
                    return entry
                i = low - 1
                continue
            if s == '{':
                header = body[i - 1].stripped if i else ''
                if header == 'else' and i >= 2 and body[i - 2].stripped == '}':
                    # the arm before this one is not on the way here: go up to the `if` that holds both
                    then = block_start(body, i - 2)
                    if then is None or not re.fullmatch(r'if\s*\(.*\)', body[then - 1].stripped if then else ''):
                        return None
                    i = then - 1
                    continue
                if re.fullmatch(r'do|(?:while|for)\s*\(.*\)', header):
                    closing = block_end(body, i)
                    if closing is None or depth > 2 or self.jumps(i, closing):
                        return None
                    found = self.scan(closing - 1, t, avoid, depth + 1) if header != 'do' else None
                    if header == 'do':
                        tail = body[closing + 1].stripped if closing + 1 < len(body) else ''
                        if not re.fullmatch(r'while\s*\(.*\)\s*;', tail) or not _pure(_header_condition(tail)):
                            return None
                        found = self.scan(closing - 1, t, avoid, depth + 1)
                    entry = self.scan(i - 2 if header == 'do' else i - 1, t, avoid, depth)
                    if not found or not entry or ' '.join(found[1].split()) != ' '.join(entry[1].split()):
                        return None
                    return entry
                i -= 1
                continue
            if self.structural(s) or self.local_set(s, avoid | {t}):
                i -= 1
                continue
            return None
        return None

    def jumps(self, low, high):
        """A `continue`, `break`, `goto`, `return` or label among the lines low..high: the loop has more than one way in
        or out, and the end of its body is not the only place its values come from."""
        return any(re.search(r'\b(?:continue|break|goto|return)\b|^\w+:', l.stripped) for l in self.body[low:high + 1])

    def uses(self, t):
        return [k for k, line in enumerate(self.body) if mentions(line.text, t) and k not in self.declarations and not
                (_DEF.fullmatch(line.stripped) and _DEF.fullmatch(line.stripped)['t'] == t)]

    def defs(self, t):
        return [k for k, line in enumerate(self.body)
                if _DEF.fullmatch(line.stripped) and _DEF.fullmatch(line.stripped)['t'] == t]

    def line_ok(self, k, t):
        """A line that uses `t` and also calls or stores: one call at most, the use among its arguments."""
        text = self.body[k].text
        calls = [m for m in _CALL.finditer(text) if m[0].split('(')[0].strip() not in
                 ('if', 'while', 'for', 'sizeof', 'return') + self.helpers]
        if re.search(r'\+\+|--', text) or len(calls) > 1:
            return False
        if calls:
            at = text.index('(', calls[0].start())
            depth, end = 0, None
            for n in range(at, len(text)):
                depth += text[n] == '('
                depth -= text[n] == ')'
                if depth == 0:
                    end = n
                    break
            return end is not None and all(at < m.start() < end for m in re.finditer(rf'(?<![\w.>]){re.escape(t)}\b', text))
        return True

    def plan(self, t):
        """Edits that inline `t`, or None when a use or a definition does not qualify."""
        defs = self.defs(t)
        if not defs or t in self.declared_params():
            return None
        if any(not _DEF.fullmatch(l.stripped) and mentions(l.text, t) and re.search(
                rf'(?<![\w.>]){re.escape(t)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(t)}\b|\b{re.escape(t)}\s*(?:\+\+|--)',
                l.text) for l in self.body):
            return None
        edits = []
        for k in self.uses(t):
            line = self.body[k]
            if not self.line_ok(k, t):
                return None
            found = self.reach(k, t, set())
            if found is None:
                return None
            expr = found[1]
            names = {w for w in words(expr) if w in self.assigned or w in self.locals}
            found = self.reach(k, t, names)
            if found is None or found[1] != expr:
                return None
            head = self.body[k].stripped
            if re.match(r'for\b', head):
                return None
            if re.fullmatch(r'while\s*\(.*\)', head):
                # a loop's own test is read again from the end of its body
                closing = block_end(self.body, k + 1) if k + 1 < len(self.body) and self.body[k + 1].stripped == '{' else None
                if closing is None or self.jumps(k + 1, closing):
                    return None
                edge = self.scan(closing - 1, t, names)
                if edge is None or ' '.join(edge[1].split()) != ' '.join(expr.split()):
                    return None
            text = f'{expr}' if _plain(expr) else f'({expr})'
            for m in re.finditer(rf'(?<![\w.>]){re.escape(t)}\b', line.source):
                edits.append((line.start + m.start(), line.start + m.end(), text))
        for k in defs:
            edits.append((self.body[k].start, self.body[k].end, ''))
        return edits

    def declared_params(self):
        signature = self.part.clean[:self.part.opening]
        return set(re.findall(r'\w+', signature[signature.rfind('('):]))

    def temps(self):
        out = []
        for t in sorted({_DEF.fullmatch(l.stripped)['t'] for l in self.body if _DEF.fullmatch(l.stripped)}):
            if t in self.locals and t in self.assigned and all(
                    _pure(_DEF.fullmatch(self.body[k].stripped)['e']) for k in self.defs(t)):
                out.append(t)
        return out


def _drop_name(source, name, t):
    """The declaration line(s) of `t` without it."""
    out = re.sub(rf'(?m)^([ \t]*)((?:[A-Za-z_]\w*[ \t]+)+\**[ \t]*){re.escape(t)};[ \t]*\n', '', source)
    out = re.sub(rf'(?m)^((?:[ \t]*(?:[A-Za-z_]\w*[ \t]+)+\**[ \t]*(?:\w+[ \t]*,[ \t]*)*)){re.escape(t)}[ \t]*,[ \t]*', r'\1', out)
    return re.sub(rf'(?m)^((?:[ \t]*(?:[A-Za-z_]\w*[ \t]+)+\**[ \t]*(?:\w+[ \t]*,[ \t]*)*\w+)),[ \t]*\**{re.escape(t)};', r'\1;', out)


def _inline_one(source, name, t):
    fn = _Function(source, name)
    if not fn.ok:
        return None
    edits = fn.plan(t)
    if edits is None:
        return None
    return _drop_name(edit(source, edits), name, t)


def variants(source, name):
    fn = _Function(source, name)
    if not fn.ok:
        return []
    out, text, taken = [], source, []
    for t in fn.temps():
        child = _inline_one(source, name, t)
        if child and child != source and len(out) < LIMIT:
            out.append((FAMILY, child))
    # every local the checks accept, one after another (a chain's members before the local that reads them)
    for _ in range(12):
        progress = False
        for t in _Function(text, name).temps():
            child = _inline_one(text, name, t)
            if child and child != text:
                text, progress = child, True
                taken.append(t)
                break
        if not progress:
            break
    if len(taken) > 1:
        out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
