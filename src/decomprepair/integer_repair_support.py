"""Small, conservative C spans shared by integer repair hypotheses, not a replacement C parser."""
import re
from dataclasses import dataclass
from functools import lru_cache

from .csource import _blank, find
from .pattern_repairs import close

IDENT = r'[A-Za-z_]\w*'
INTEGER = r'(?:unsigned\s+(?:char|short|int)|signed\s+(?:char|short|int)|[su](?:8|16|32)|char|short|int)'
DECL = re.compile(rf'\b(?P<type>{INTEGER})\s+(?P<name>{IDENT})\s*;')
NUMBER = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*'


@dataclass
class View:
    source: str
    clean: str
    opening: int
    end: int

    @property
    def body(self):
        return self.clean[self.opening+1:self.end-1]


def view(source, name):
    part = _view(source, name)
    return View(part.source, part.clean, part.opening, part.end) if part else None


@lru_cache(maxsize=8)
def _view(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    definition = re.search(r'\b'+re.escape(name)+r'\s*\([^{};]*\)\s*{',clean[span[0]:span[1]])
    opening = span[0]+definition.end()-1 if definition else -1
    if opening < 0 or '#' in clean[opening:span[1]] or re.search(r'::|\b(?:class|template|namespace)\b', clean):
        return None
    return View(source, clean, opening, span[1])


def plain_repair_view(source, name, header):
    """Only source whose lexical reads and names are visible to the rewrite."""
    part = view(source,name)
    if not part:
        return None
    context = _blank(header)+'\n'+part.clean
    definitions = re.findall(r'^\s*#\s*define\s+('+IDENT+r')([^\n]*)',context,re.M)
    literals = rf'[ \t]+(?:{NUMBER}|\(\(void\s*\*\)\s*0\))'
    macros = {ident for ident, body in definitions if not re.fullmatch(literals,body.rstrip())}
    if (macros & set(re.findall(IDENT,part.body))
            or re.search(r'\b(?:asm|__asm__|goto|volatile)\b|^\s*#\s*include\b',context,re.M)):
        return None
    return part


def _address_taken(body, name):
    """Whether `&name` appears as an address-of. A binary `a & name` (an identifier, `]` or a parenthesised expression
    before the `&`) is not; `(T *)&name` and `(T)&name` are, and so is a parenthesised lone name (it may be a cast)."""
    for hit in re.finditer(rf'&\s*{re.escape(name)}\b', body):
        before = body[:hit.start()].rstrip()
        if before.endswith('&'):
            continue  # `a && name` is a logical and
        if re.search(r'(?:^|[^\w])return$', before) or not re.search(r'[\w)\]]$', before):
            return True
        if before.endswith(')'):
            depth, at = 0, len(before)
            while at > 0:
                at -= 1
                depth += (before[at] == ')') - (before[at] == '(')
                if depth == 0:
                    break
            if re.fullmatch(r'\s*(?:(?:const|volatile|struct|union|unsigned|signed)\s+)*\w+[\s*]*', before[at + 1:-1]):
                return True
    return False


def locals_for(part):
    """Ordinary, unescaped scalar declarations; leave shadows and qualified objects to the compiler."""
    found = []
    records = []
    for record in re.finditer(r'\b(?:struct|union)(?:\s+'+IDENT+r')?\s*{',part.body):
        start=part.opening+1+record.end()-1
        end=close(part.clean,start,'{','}')
        if end:
            records.append((start,end))
    for decl in DECL.finditer(part.clean, part.opening+1, part.end):
        if any(start < decl.start() < end for start,end in records):
            continue
        prefix = part.clean[part.opening+1:decl.start()].rstrip()
        if prefix and prefix[-1] not in ';{}':
            continue
        name = decl['name']
        # Also notice shadows declared as pointers, qualified objects or for-loop variables.
        declarations = re.findall(rf'\b(?:{INTEGER}|void|float|double)\s*\**\s*{re.escape(name)}\s*(?=[;=,\[])', part.body)
        if len(declarations) != 1 or _address_taken(part.body, name):
            continue
        found.append(decl)
    return found


_LABEL_AFTER = re.compile(r'\s*:(?!:)')


def _member_or_goto_before(text, position):
    """`text[:position]` ends (past any whitespace) in `.`, `->` or a `goto`: what the old regex for that said, without
    slicing and rescanning the whole prefix for every reference."""
    while position > 0 and text[position - 1].isspace():
        position -= 1
    if text.startswith('.', position - 1) and position > 0:
        return True
    if position >= 2 and text[position - 2:position] == '->':
        return True
    return (position >= 4 and text[position - 4:position] == 'goto'
            and (position == 4 or not (text[position - 5].isalnum() or text[position - 5] == '_')))


def refs(part, decl):
    clean = part.clean
    return [hit for hit in re.finditer(rf'\b{re.escape(decl["name"])}\b', clean)
            if part.opening < hit.start() < part.end and not decl.start() <= hit.start() < decl.end()
            and not _member_or_goto_before(clean, hit.start())
            and not _LABEL_AFTER.match(clean, hit.end())]


def edit(source, edits):
    ordered = sorted(edits)
    # Edits that don't overlap and lie inside the source (nearly always) are joined in one pass; rebuilding the whole
    # source once per edit made a repair with hundreds of edits quadratic. Anything else keeps the old
    # last-edit-first replacement, so its result is what it was.
    position, pieces = 0, []
    for start, end, replacement in ordered:
        if start < position or end < start or end > len(source):
            break
        pieces.append(source[position:start])
        pieces.append(replacement)
        position = end
    else:
        pieces.append(source[position:])
        return ''.join(pieces)
    for start, end, replacement in reversed(ordered):
        source = source[:start]+replacement+source[end:]
    return source


def split_plain_declarations(source, name, header=''):
    """Expose ordinary comma declarations to scalar analysis without moving scopes/lines."""
    part=view(source,name)
    if not part:return source
    macros=set(re.findall(r'^\s*#\s*define\s+('+IDENT+')',header+'\n'+source,re.M))
    changes=[]
    pattern=re.compile(rf'\b(?P<type>{INTEGER})\s+(?P<names>{IDENT}(?:\s*,\s*{IDENT})+)\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end):
        if part.clean[part.opening+1:hit.start()].rstrip()[-1:] not in ('',';','{','}'):continue
        if set(re.findall(IDENT,hit[0]))&macros:continue
        names=source[hit.start('names'):hit.end('names')]
        names=re.sub(r',(\s*)',lambda m,kind=hit['type']:';'+m[1]+kind+' ',names)
        changes.append((hit.start(),hit.end(),hit['type']+' '+names+';'))
    return edit(source,changes)


def integer(text):
    text = re.sub(r'[uUlL]+$', '', text)
    return int(text, 16 if text.lower().startswith('0x') else 10)


def split_args(text):
    start = depth = 0
    result = []
    for pos, char in enumerate(text):
        depth += (char in '([{')-(char in ')]}')
        if char == ',' and depth == 0:
            result.append((start, pos))
            start = pos+1
    if text.strip():
        result.append((start, len(text)))
    return result


def calls(part, name):
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*\(', part.clean[part.opening+1:part.end-1]):
        start = part.opening+1+hit.end()
        end = close(part.clean, start-1)
        if end:
            yield start, end-1
