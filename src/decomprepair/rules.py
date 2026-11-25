"""Declarative repair rules: a repair written as a JSON file instead of a module.

A rule says what C shape to find in the function, what must be true of the target and of the match, and what to write
in its place. It carries no code, so an agent (or a person) can add one by writing a file, and the Deep Permuter runs
it the next time it asks the registry: `registry.declared()` lists every valid rule beside the library's modules.

Where rules come from (first one with an id wins; a second file with the same id is reported, not run):
- `decomprepair/rules/*.json`, the rules shipped in the library;
- every folder in the `DECOMP_REPAIR_RULES` environment variable (separated like PATH), which the application points
  at the user's rules folder. A subprocess inherits it, so the Deep Permuter's local lane (which calls
  `registry.run('rule:<id>', ...)` by name) finds the same rules as the parent.
A file that is not a valid rule is skipped and listed by `skipped()` with a sentence saying why; it never stops the
registry or another rule.

The rule (schema 1):

    {
      "schema": 1,
      "id": "abs_idiom",                       # lower-case name; the registry module is "rule:abs_idiom"
      "description": "one sentence",           # optional
      "families": ["abs_idiom", "abs_idiom_one"],   # the labels its children carry
      "archs": ["mips"],                       # optional, as REPAIR's "archs"
      "lanes": ["draft", "beam", "local"],     # optional
      "order": 63,                             # optional, as REPAIR's "order"
      "gate": [ {"asm_has": ["negu", {"op": ["subu", "sub"], "argc": 3, "arg1": "$zero"}]} ],
      "sites": [                               # what to rewrite, in the function's body (comments/strings blanked)
        {"match": "^(?P<lead>[ \\t]*)if\\s*\\(\\s*(?P<var>@IDENT@)\\s*<\\s*0\\s*\\)...",
         "where": [ {"declared_type": {"group": "var", "kind": "integer"}} ],
         "replace": "{lead}{var} = abs({var});"} ],
      "prepend_unless_declared": {"pattern": "(?:int|s32)[ \\t]+abs\\s*\\(", "text": "int abs(int);\\n"},
      "children": {"all": "abs_idiom",         # one child with every site rewritten
                   "each": {"family": "abs_idiom_one", "when_sites_over": 1, "max": 7}}   # and one per site
    }

`gate`: every entry must hold or the rule makes nothing. `asm_has` is true when the target's assembly has any listed
instruction: a name, or {"op": name or [names], "argc": operand count, "arg0".."arg3": the operand's text}.
`sites[].match`: a regular expression (`re.M`); `@IDENT@` is a C identifier and `@INTEGER@` an integer type. A later
site never takes text an earlier site took. `where` guards (all must hold; groups are compared stripped):
`{"group_equals_any": {"group": "test", "of": ["var", "expr"]}}` and `{"declared_type": {"group": "var", "kind":
"integer"}}` (the name is declared in the function or its parameters as an integer, not a pointer or a float).
`replace`: `{group}` is the group's text as matched, `{group:strip}` stripped.
`prepend_unless_declared`: `text` goes in front of the function unless `pattern` is in the source or the header.

Limits, so a rule from an agent can't hang or flood a caller: a match pattern is at most 2,000 characters and has no
nested quantifier (`(a+)+`), a rule has at most 8 sites, 4 `where` guards a site and 24 children, and a function longer
than 400,000 characters is left alone. Python's `re` can't be interrupted, which is why the patterns are checked when
they are loaded rather than timed when they run."""
import inspect
import json
import os
import pathlib
import re
from dataclasses import dataclass
from functools import lru_cache

from .csource import find
from .integer_repair_support import IDENT, edit, view

SCHEMA = 1
ENVIRONMENT = 'DECOMP_REPAIR_RULES'
PACKAGED = pathlib.Path(__file__).parent / 'rules'
PREFIX = 'rule:'

LANES = ('draft', 'beam', 'local')
ARCHS = ('mips', 'ppc', 'x86', 'arm')
MAX_PATTERN, MAX_SITES, MAX_WHERE, MAX_CHILDREN, MAX_EACH, MAX_BODY = 2000, 8, 4, 24, 16, 400_000
INTEGER = (r'(?:s8|u8|s16|u16|s32|u32|int|short|char|unsigned\s+(?:int|short|char)|signed\s+(?:int|short|char))')
PLACEHOLDERS = {'@IDENT@': IDENT, '@INTEGER@': INTEGER}
NAME = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')
TEMPLATE = re.compile(r'\{(\w+)(?::(strip))?\}')
ASM_LINE = re.compile(r'\*/\s*(?P<op>[a-z.]+)\s+(?P<args>[^\n]*)$')
OPERANDS = ('arg0', 'arg1', 'arg2', 'arg3')
KEYS = {'schema', 'id', 'description', 'families', 'archs', 'lanes', 'order', 'gate', 'sites',
        'prepend_unless_declared', 'children'}


@dataclass(frozen=True)
class Rule:
    """A validated rule with its patterns compiled."""
    id: str
    families: tuple
    archs: tuple
    lanes: tuple
    order: int
    needs: tuple
    gate: tuple
    sites: tuple          # ((compiled pattern, where guards, replace template), ...)
    prepend: tuple        # (compiled pattern, text) or ()
    all_family: str
    each: dict
    path: str = ''

    @property
    def module(self):
        return PREFIX + self.id


def _expand(pattern):
    for placeholder, text in PLACEHOLDERS.items():
        pattern = pattern.replace(placeholder, text)
    return pattern


def _fail_on_repeated_group(pattern):
    """The repetition of a group that contains a repetition, found by looking at what follows each closing bracket."""
    opens, repeats = [], []
    escaped = in_class = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if escaped:
            escaped = False
        elif char == '\\':
            escaped = True
        elif in_class:
            in_class = char != ']'
        elif char == '[':
            in_class = True
        elif char == '(':
            opens.append(index)
            repeats.append(False)
        elif char == ')' and opens:
            opens.pop()
            inner = repeats.pop()
            repeated = re.match(r'[+*]|\{\d+(,\d*)?\}', pattern[index + 1:]) is not None
            if inner and repeated:
                return True
            if repeats and (inner or repeated):
                repeats[-1] = True
        elif char in '+*' or (char == '{' and re.match(r'\{\d+(,\d*)?\}', pattern[index:])):
            if repeats:
                repeats[-1] = True
        index += 1
    return False


def problems(rule):
    """What is wrong with `rule` (a parsed JSON value), as sentences a rule's author can act on; empty when it is fine."""
    if not isinstance(rule, dict):
        return ['a rule is a JSON object']
    out = []
    unknown = sorted(set(rule) - KEYS)
    if unknown:
        out.append(f'unknown keys {unknown}: a rule has only {sorted(KEYS)}')
    if rule.get('schema') != SCHEMA:
        out.append(f'"schema" must be {SCHEMA}')
    if not isinstance(rule.get('id'), str) or not NAME.match(rule['id']):
        out.append('"id" must be a lower-case name (letters, digits and underscores, starting with a letter)')
    families = rule.get('families')
    if not isinstance(families, list) or not families or not all(isinstance(f, str) and NAME.match(f) for f in families):
        out.append('"families" must list the lower-case family names the children are labelled with')
        families = []
    for key, allowed in (('archs', ARCHS), ('lanes', LANES)):
        value = rule.get(key, [])
        if not isinstance(value, list) or any(item not in allowed for item in value):
            out.append(f'"{key}" must be a list with only {list(allowed)}')
    if 'order' in rule and (not isinstance(rule['order'], int) or isinstance(rule['order'], bool)):
        out.append('"order" must be an integer')
    for entry in rule.get('gate', []) if isinstance(rule.get('gate', []), list) else [None]:
        out.extend(_gate_problems(entry))
    sites = rule.get('sites')
    if not isinstance(sites, list) or not 1 <= len(sites) <= MAX_SITES:
        out.append(f'"sites" must list 1 to {MAX_SITES} sites')
        sites = []
    for number, site in enumerate(sites, 1):
        out.extend(f'site {number}: {text}' for text in _site_problems(site))
    prepend = rule.get('prepend_unless_declared')
    if prepend is not None:
        out.extend(_prepend_problems(prepend))
    out.extend(_children_problems(rule.get('children'), families, len(sites)))
    return out


def _gate_problems(entry):
    if not isinstance(entry, dict) or set(entry) != {'asm_has'} or not isinstance(entry['asm_has'], list) \
            or not entry['asm_has']:
        return ['each "gate" entry must be {"asm_has": [instruction, ...]}']
    out = []
    for item in entry['asm_has']:
        if isinstance(item, str):
            if not re.fullmatch(r'[a-z][a-z0-9.]*', item):
                out.append(f'"asm_has" instruction {item!r} must be a lower-case mnemonic')
        elif isinstance(item, dict):
            op = item.get('op')
            ops = op if isinstance(op, list) else [op]
            extra = set(item) - {'op', 'argc'} - set(OPERANDS)
            if not ops or not all(isinstance(o, str) and re.fullmatch(r'[a-z][a-z0-9.]*', o) for o in ops) or extra:
                out.append(f'"asm_has" entry {item!r} needs "op" (a mnemonic or a list) and only "argc", {list(OPERANDS)}')
        else:
            out.append(f'"asm_has" entry {item!r} must be a mnemonic or an object')
    return out


def _site_problems(site):
    if not isinstance(site, dict) or set(site) - {'match', 'where', 'replace'} or not {'match', 'replace'} <= set(site):
        return ['a site is {"match": regex, "where": [guards], "replace": template}']
    pattern, template = site['match'], site['replace']
    if not isinstance(pattern, str) or not isinstance(template, str) or not pattern:
        return ['"match" and "replace" must be strings']
    if len(pattern) > MAX_PATTERN:
        return [f'"match" is longer than {MAX_PATTERN} characters']
    expanded = _expand(pattern)
    try:
        compiled = re.compile(expanded, re.M)
    except re.error as error:
        return [f'"match" is not a valid regular expression: {error}']
    if _fail_on_repeated_group(expanded):
        return ['"match" repeats a group that itself repeats (like (a+)+), which can run for ever: write it without']
    if compiled.match(''):
        return ['"match" matches the empty text']
    out = [f'"replace" names {{{name}}}, which "match" has no group for'
           for name in sorted({m[1] for m in TEMPLATE.finditer(template)} - set(compiled.groupindex))]
    guards = site.get('where', [])
    if not isinstance(guards, list) or len(guards) > MAX_WHERE:
        return out + [f'"where" must be a list of at most {MAX_WHERE} guards']
    for guard in guards:
        out.extend(_guard_problems(guard, compiled))
    return out


def _guard_problems(guard, compiled):
    groups = set(compiled.groupindex)
    if isinstance(guard, dict) and set(guard) == {'group_equals_any'}:
        spec = guard['group_equals_any']
        if not isinstance(spec, dict) or set(spec) != {'group', 'of'} or not isinstance(spec['of'], list) \
                or not {spec['group'], *spec['of']} <= groups:
            return ['"group_equals_any" is {"group": g, "of": [g, ...]} with groups the pattern has']
        return []
    if isinstance(guard, dict) and set(guard) == {'declared_type'}:
        spec = guard['declared_type']
        if not isinstance(spec, dict) or set(spec) != {'group', 'kind'} or spec['group'] not in groups \
                or spec['kind'] != 'integer':
            return ['"declared_type" is {"group": g, "kind": "integer"} with a group the pattern has']
        return []
    return [f'unknown guard {guard!r}: one of group_equals_any, declared_type']


def _prepend_problems(prepend):
    if not isinstance(prepend, dict) or set(prepend) != {'pattern', 'text'} \
            or not all(isinstance(prepend[key], str) for key in prepend):
        return ['"prepend_unless_declared" is {"pattern": regex, "text": the text to put before the function}']
    try:
        re.compile(prepend['pattern'], re.M)
    except re.error as error:
        return [f'"prepend_unless_declared" pattern is not a valid regular expression: {error}']
    if len(prepend['pattern']) > MAX_PATTERN or _fail_on_repeated_group(prepend['pattern']):
        return ['"prepend_unless_declared" pattern is too long or repeats a repeated group']
    return []


def _children_problems(children, families, count):
    if not isinstance(children, dict) or not set(children) <= {'all', 'each'} or not children:
        return ['"children" is {"all": family, "each": {...}}']
    out = []
    if 'all' in children and children['all'] not in families:
        out.append('"children.all" must be one of "families"')
    each = children.get('each')
    if each is not None:
        if not isinstance(each, dict) or set(each) - {'family', 'when_sites_over', 'max'} or each.get('family') not in families:
            out.append('"children.each" is {"family": one of "families", "when_sites_over": n, "max": n}')
        else:
            over, most = each.get('when_sites_over', 0), each.get('max', MAX_EACH)
            if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in (over, most)) \
                    or not 1 <= most <= MAX_EACH:
                out.append(f'"when_sites_over" must be a count and "max" between 1 and {MAX_EACH}')
            elif ('all' in children) + most > MAX_CHILDREN:
                out.append(f'a rule makes at most {MAX_CHILDREN} children')
    return out


def compile_rule(rule, path=''):
    """The `Rule` for a parsed JSON value, or a ValueError whose message lists what is wrong."""
    found = problems(rule)
    if found:
        raise ValueError('; '.join(found))
    sites = tuple((re.compile(_expand(site['match']), re.M), tuple(_freeze(g) for g in site.get('where', [])),
                   site['replace']) for site in rule['sites'])
    prepend = rule.get('prepend_unless_declared')
    needs = ['source', 'name']
    if rule.get('gate'):
        needs.append('asm')
    if prepend:
        needs.append('header')
    each = dict(rule['children'].get('each') or {})
    each.setdefault('when_sites_over', 0)
    each.setdefault('max', MAX_EACH)
    return Rule(id=rule['id'], families=tuple(rule['families']), archs=tuple(rule.get('archs', ())),
                lanes=tuple(rule.get('lanes', LANES)), order=rule.get('order', 1000), needs=tuple(needs),
                gate=tuple(tuple(entry['asm_has']) for entry in rule.get('gate', [])), sites=sites,
                prepend=(re.compile(prepend['pattern'], re.M), prepend['text']) if prepend else (),
                all_family=rule['children'].get('all', ''), each=each if rule['children'].get('each') else {}, path=str(path))


def _freeze(guard):
    (kind, spec), = guard.items()
    return (kind, spec['group'], tuple(spec.get('of', ())), spec.get('kind'))


def _asm_has(asm, wanted):
    for line in (asm or '').splitlines():
        hit = ASM_LINE.search(line)
        if not hit:
            continue
        op, args = hit['op'], [a.strip() for a in hit['args'].split(',')]
        for item in wanted:
            if isinstance(item, str):
                if op == item:
                    return True
                continue
            ops = item['op'] if isinstance(item['op'], list) else [item['op']]
            if op in ops and item.get('argc', len(args)) == len(args) and all(
                    key not in item or (int(key[3]) < len(args) and args[int(key[3])] == item[key]) for key in OPERANDS):
                return True
    return False


def _integer_declared(part, name, top):
    return re.search(rf'\b{INTEGER}\s+{re.escape(name)}\s*[;,=)\[]', part.clean[top:part.end]) is not None


def _holds(guard, hit, part, top):
    kind, group, others, _ = guard
    value = (hit[group] or '').strip()
    if kind == 'group_equals_any':
        return value in {(hit[other] or '').strip() for other in others}
    return _integer_declared(part, value, top)


def _fill(template, hit):
    def piece(found):
        text = hit[found[1]] or ''
        return text.strip() if found[2] else text
    return TEMPLATE.sub(piece, template)


def apply(rule, source, name, asm='', header=''):
    """[(family, source)] of `rule` for one function: what `variants` of a module returns."""
    if any(not _asm_has(asm, entry) for entry in rule.gate):
        return []
    part = view(source, name)
    if not part or part.end - part.opening > MAX_BODY:
        return []
    top = find(source, name)[0]
    top = source.rfind('\n', 0, top) + 1
    found, taken = [], []
    for pattern, guards, template in rule.sites:
        for hit in pattern.finditer(part.clean, part.opening, part.end):
            if any(a <= hit.start() < b for a, b in taken) or not all(_holds(g, hit, part, top) for g in guards):
                continue
            found.append((hit.start(), hit.end(), _fill(template, hit)))
            taken.append((hit.start(), hit.end()))
    found.sort()
    if not found:
        return []
    proto = []
    if rule.prepend and not rule.prepend[0].search(source + '\n' + (header or '')):
        proto = [(top, top, rule.prepend[1])]
    out = []
    if rule.all_family:
        out.append((rule.all_family, edit(source, found + proto)))
    if rule.each and len(found) > rule.each['when_sites_over']:
        for site in found[:rule.each['max']]:
            out.append((rule.each['family'], edit(source, [site] + proto)))
    return out


def repair(rule):
    """The registry's `Repair` for `rule`: `variants` takes the context the rule says it needs, by those names."""
    from .registry import OPTIONAL, Repair

    def variants(**context):
        return apply(rule, context['source'], context['name'], context.get('asm', ''), context.get('header', ''))
    variants.__name__ = 'variants'
    variants.__signature__ = inspect.Signature([
        inspect.Parameter(key, inspect.Parameter.KEYWORD_ONLY,
                          default='' if key in ('asm', 'header') or key in OPTIONAL else inspect.Parameter.empty)
        for key in rule.needs])
    return Repair(module=rule.module, families=rule.families, variants=variants, needs=rule.needs, order=rule.order,
                  lanes=rule.lanes, archs=rule.archs, rule=True)


def directories():
    """The folders rules are read from, packaged ones first."""
    extra = [pathlib.Path(item) for item in os.environ.get(ENVIRONMENT, '').split(os.pathsep) if item]
    return [PACKAGED, *extra]


def files():
    return [path for folder in directories() if folder.is_dir() for path in sorted(folder.glob('*.json'))]


def signature():
    """What the rule files are now (path, modification time, size): the registry re-reads them when it changes."""
    out = []
    for path in files():
        try:
            info = path.stat()
        except OSError:
            continue
        out.append((str(path), info.st_mtime_ns, info.st_size))
    return tuple(out)


@lru_cache(maxsize=4)
def _load(sig):
    rules, skipped = {}, {}
    for path, _, _ in sig:
        try:
            parsed = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
            rule = compile_rule(parsed, path)
        except (OSError, ValueError) as error:  # json.JSONDecodeError is a ValueError
            skipped[path] = f'not a valid repair rule: {error}'
            continue
        if rule.id in rules:
            skipped[path] = f'the rule id "{rule.id}" is already used by {rules[rule.id].path}'
            continue
        rules[rule.id] = rule
    return rules, skipped


def loaded():
    """{id: Rule} of the valid rules now on disk."""
    return dict(_load(signature())[0])


def skipped():
    """{path: sentence} of the rule files that were not loaded."""
    return dict(_load(signature())[1])


def repairs():
    return [repair(rule) for rule in loaded().values()]
