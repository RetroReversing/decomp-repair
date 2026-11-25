"""The registry of repair modules: a library module declares itself, the caller finds it.

Until now every new module had to be wired by hand in the caller (an import, a family list, a `variants` call with the
right arguments in each lane), and a module nobody wired never ran. A module that has a `variants(...)` declares
itself with one module-level dict, and the caller (decompdecomp's drafts, the Deep Permuter's beam and its local lane)
asks `registry.declared()` and runs each entry with only the context it says it needs:

    REPAIR = {
        "families": FAMILIES,                    # the family names the module labels its children with
        "variants": variants,                    # the function; returns [(family, source)] or [source]
        "needs": ("source", "name", "header"),   # the context it takes, by the parameter's own name
        "order": 100,                            # lower runs first, default 1000 (ties: the module's name)
        "lanes": ("draft", "beam", "local"),     # where it runs (the default is all three)
        "archs": ("mips",),                      # optional: only for these processors
        "directives": True,                      # optional: it reads the function's own `#define` lines
    }

`directives`: a caller that sees a `#` inside the function hands the draft to a masking path (preprocessor lines blanked,
so nothing a module reads is a macro). A module that reads those lines themselves (a hand-written `#define` that names a
stack slot) declares `directives` and is also run on the function exactly as written, in the draft lane only.

`needs` are the `variants` parameter names the caller can supply, a subset of CONTEXT: `source` and `name` always,
and `header`, `arch`, `asm` (the target's assembly) and `flags` (the compiler's flags) when wanted. `words` is game data
the C can't show: {symbol: the 32-bit word at its address, in the game's byte order}, for the symbols the caller chose
to read (decompdecomp: the float constants only one function refers to). `callees` is the matched C of the function's callees, as one
text (decompdecomp: capture_followup_repairs.callee_evidence), evidence of a callee's own parameters. `tables` is the function's jump tables, [(lowest case value, [address each case enters])] read from the
target (decompdecomp: switch_tables.read), evidence of which case leads to which arm. All three are OPTIONAL:
a caller older than them leaves them out, so a module that needs it gives the parameter a default and gets nothing then (`arguments`). Each is passed by
keyword, so the order of the parameters is the module's own business. Lanes: `draft` (a draft's repair pass, which is
limited), `beam` (the Deep Permuter's beam, which asks the same pass with no limit), `local` (the Deep Permuter's local
lane, which tries the library's rewrites on its current best).

`declared()` finds the declaring modules by reading each file for a line that starts with `REPAIR` and imports only those,
so listing the registry costs a scan of the folder, not an import of every module. `problems()` is what the test
checks: a declaration the caller could not run is an error, found in this library's CI and not after a release."""
import builtins
import importlib
import inspect
import pathlib
import re
import sys
from dataclasses import dataclass
from functools import lru_cache

from . import rules

CONTEXT = ('source', 'name', 'header', 'arch', 'asm', 'flags', 'words', 'callees', 'tables')
OPTIONAL = ('words', 'callees', 'tables')  # context a caller may not have yet: left out, the parameter's default is used
LANES = ('draft', 'beam', 'local')
DEFAULT_ORDER = 1000
_DECLARES = re.compile(r'^REPAIR\s*(?::[^=\n]*)?=', re.M)


@dataclass(frozen=True)
class Repair:
    module: str
    families: tuple
    variants: object
    needs: tuple
    order: int
    lanes: tuple
    archs: tuple
    directives: bool = False
    rule: bool = False     # a declarative rule (rules.py), not a module of this package

    def runs_in(self, lane, arch=None):
        return lane in self.lanes and (not self.archs or arch is None or arch in self.archs)

    def function(self):
        """`variants` as its module has it now: a test or a hot patch that replaces the module's function is honoured."""
        module = sys.modules.get(f'{__package__}.{self.module}')
        return getattr(module, getattr(self.variants, '__name__', 'variants'), self.variants) if module else self.variants

    def arguments(self, context):
        """The keyword arguments of `variants` out of `context` (an OPTIONAL key the caller lacks is left out)."""
        return {key: context[key] for key in self.needs if key in context or key not in OPTIONAL}


def _make(module_name, declared):
    return Repair(
        module=module_name,
        families=tuple(declared.get('families', ())),
        variants=declared.get('variants'),
        needs=tuple(declared.get('needs', ('source', 'name'))),
        order=declared.get('order', DEFAULT_ORDER),
        lanes=tuple(declared.get('lanes', LANES)),
        archs=tuple(declared.get('archs', ())),
        directives=bool(declared.get('directives', False)),
    )


@lru_cache(maxsize=1)
def _modules():
    """The package's own declaring modules, lowest `order` first. Scanned once: the folder doesn't change while running."""
    folder = pathlib.Path(__file__).parent
    found = []
    for path in sorted(folder.glob('*.py')):
        if path.stem == 'registry' or not _DECLARES.search(path.read_text(encoding='utf-8')):
            continue
        module = importlib.import_module(f'{__package__}.{path.stem}')
        declared = getattr(module, 'REPAIR', None)
        if isinstance(declared, dict):
            found.append(_make(path.stem, declared))
    return sorted(found, key=lambda item: (item.order, item.module))


_merged = (None, None, [])


def declared():
    """Every declared repair, lowest `order` first, then by module name: the package's modules and the declarative
    rules now on disk (rules.py). The same list comes back until a rule file is added, changed or removed, so a caller
    that holds it sees a new rule on its next call and an unchanged registry costs one stat per rule file."""
    global _merged
    modules, signature = _modules(), rules.signature()
    if _merged[0] is not modules or _merged[1] != signature:
        merged = sorted([*modules, *rules.repairs()], key=lambda item: (item.order, item.module))
        _merged = (modules, signature, merged)
    return _merged[2]


declared.cache_clear = _modules.cache_clear   # tests that add a module to the folder clear the scan


_index = (None, {})


def get(module):
    """The declared repair of `module`. The index follows `declared()` itself, so a cleared cache is not served stale."""
    global _index
    items = declared()
    if _index[0] is not items:
        _index = (items, {item.module: item for item in items})
    return _index[1].get(module)


def problems(repair):
    """What would stop a caller from running `repair`: a list of sentences, empty when it is fine."""
    out = []
    if not callable(repair.variants):
        return [f'{repair.module}: "variants" is not a function']
    if repair.rule:
        return _rule_problems(repair)
    if not repair.families or not all_strings(repair.families):
        out.append(f'{repair.module}: "families" must list the family names the children are labelled with')
    if getattr(repair.variants, '__module__', None) != f'{__package__}.{repair.module}':
        out.append(f'{repair.module}: "variants" is not defined in this module')
    unknown = [key for key in repair.needs if key not in CONTEXT]
    if unknown:
        out.append(f'{repair.module}: needs {unknown} are not context a caller supplies (one of {CONTEXT})')
    if 'source' not in repair.needs or 'name' not in repair.needs:
        out.append(f'{repair.module}: needs must include "source" and "name"')
    parameters = inspect.signature(repair.variants).parameters
    for key in repair.needs:
        if key in CONTEXT and key not in parameters:
            out.append(f'{repair.module}: variants has no parameter "{key}" that "needs" names')
    for key in repair.needs:
        if key in OPTIONAL and key in parameters and parameters[key].default is inspect.Parameter.empty:
            out.append(f'{repair.module}: "{key}" is optional context (an older caller has none): give it a default')
    for key, parameter in parameters.items():
        if parameter.default is inspect.Parameter.empty and parameter.kind in (
                parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY) \
                and key not in repair.needs:
            out.append(f'{repair.module}: variants needs "{key}" but "needs" does not list it')
    if not isinstance(repair.order, int):
        out.append(f'{repair.module}: "order" must be an integer')
    bad = [lane for lane in repair.lanes if lane not in LANES] or ([] if repair.lanes else ['(none)'])
    if bad:
        out.append(f'{repair.module}: lanes {bad} are not among {LANES}')
    return out


def _rule_problems(repair):
    """A declarative rule is built from validated JSON, so only what the registry itself relies on is checked."""
    out = []
    if not repair.module.startswith(rules.PREFIX) or not repair.families:
        out.append(f'{repair.module}: a rule needs an id and families')
    if repair.needs[:2] != ('source', 'name') or [key for key in repair.needs if key not in CONTEXT]:
        out.append(f'{repair.module}: needs {repair.needs} are not context a caller supplies (one of {CONTEXT})')
    return out


def all_strings(items):
    return builtins.all(isinstance(item, str) and item for item in items)


def pairs(repair, result):
    """`result` of `repair.variants` as [(family, source)]: a plain source is labelled with the first family."""
    family = repair.families[0] if repair.families else repair.module
    out = []
    for item in result or ():
        if isinstance(item, str):
            out.append((family, item))
        else:
            label, text = item
            out.append((label, text))
    return out


def run(module, **context):
    """[(family, source)] of the declared repair `module` for `context` (keys not in its `needs` are ignored).

    This is the call a subprocess makes by name (`decomprepair.registry.run`), so the children come back labelled."""
    repair = get(module)
    if repair is None:
        raise ValueError(f'{module} is not a declared repair')
    if not repair.runs_in('draft') and not repair.runs_in('beam') and not repair.runs_in('local'):
        return []
    if isinstance(context.get('flags'), list):
        context['flags'] = tuple(context['flags'])
    return pairs(repair, repair.function()(**repair.arguments(context)))


all = declared  # the name callers use: `registry.all()`
