"""The registry: a module that declares `REPAIR` runs in every caller lane with no caller wiring."""
import importlib
import pathlib
import re
import sys

import pytest

from decomprepair import registry

SRC = pathlib.Path(registry.__file__).parent
LEGACY = set((pathlib.Path(__file__).parent / 'registry_legacy.txt').read_text().split())
DECLARES = re.compile(r'^REPAIR\s*(?::[^=\n]*)?=', re.M)
SOURCE = 'void f(void)\n{\n    g();\n}\n'


def test_every_declared_repair_can_be_run_by_a_caller():
    declared = registry.declared()
    assert declared, 'no module declares REPAIR'
    for repair in declared:
        assert registry.problems(repair) == []


def test_a_module_with_variants_declares_itself():
    """A new module that has `variants` but no REPAIR would be wired by hand in every caller (or never run): declare it.
    The modules that were wired by hand before the registry are listed in registry_legacy.txt and may stay there."""
    missing = []
    for path in sorted(SRC.glob('*.py')):
        text = path.read_text(encoding='utf-8')
        if re.search(r'(?m)^def variants\(', text) and not DECLARES.search(text) and path.stem not in LEGACY:
            missing.append(path.stem)
    assert missing == [], (
        f'{missing} define variants() but not REPAIR. Add at the end of the module: '
        "REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')} (src/decomprepair/registry.py)")


def test_the_legacy_list_only_names_modules_that_still_need_it():
    stale = [name for name in sorted(LEGACY)
             if not (SRC / f'{name}.py').exists() or DECLARES.search((SRC / f'{name}.py').read_text(encoding='utf-8'))]
    assert stale == [], f'{stale} declare REPAIR now (or are gone): remove them from tests/registry_legacy.txt'


def test_all_is_ordered_and_finds_a_declaration_by_module():
    orders = [(item.order, item.module) for item in registry.all()]
    assert orders == sorted(orders)
    first = registry.all()[0]
    assert registry.get(first.module) is first and registry.get('no_such_module') is None


@pytest.fixture
def fake_module(tmp_path, monkeypatch):
    """A module in the package folder's namespace, declared the way a new one would be."""
    def make(text, name='registry_probe'):
        path = SRC / f'{name}.py'
        path.write_text(text, encoding='utf-8')
        registry.declared.cache_clear()
        importlib.invalidate_caches()
        return name
    yield make
    for path in SRC.glob('registry_probe*.py'):
        path.unlink()
        sys.modules.pop(f'decomprepair.{path.stem}', None)
    registry.declared.cache_clear()


def test_a_new_module_is_found_run_with_the_context_it_needs_and_labelled(fake_module):
    name = fake_module('''
FAMILIES = ('probe_a', 'probe_b')


def variants(source, name, asm, header=''):
    return [source.replace('g();', 'h(%s);' % asm.strip()), ('probe_b', source + '/*' + name + '*/')]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 5, 'lanes': ('draft', 'local')}
''')
    repair = registry.get(name)
    assert repair and registry.problems(repair) == [] and repair.order == 5
    assert repair.runs_in('draft') and repair.runs_in('local') and not repair.runs_in('beam')
    context = dict(source=SOURCE, name='f', header='ignored', arch='mips', asm=' 4 ', flags=('-O2',))
    assert registry.run(name, **context) == [('probe_a', SOURCE.replace('g();', 'h(4);')), ('probe_b', SOURCE + '/*f*/')]
    assert registry.all()[0].module == name  # order 5 sorts before the migrated modules


def test_problems_say_what_a_caller_could_not_run(fake_module):
    name = fake_module('''
FAMILIES = ('probe',)


def variants(source, name, rows):
    return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'bogus'), 'lanes': ('draft', 'nowhere')}
''', 'registry_probe_bad')
    found = ' | '.join(registry.problems(registry.get(name)))
    assert 'bogus' in found and 'nowhere' in found and 'needs "rows"' in found


def test_a_plain_source_result_is_labelled_with_the_first_family(fake_module):
    name = fake_module('''
FAMILIES = ('only',)


def variants(source, name):
    return [source + '1']


REPAIR = {'families': FAMILIES, 'variants': variants}
''')
    assert registry.run(name, source=SOURCE, name='f', header='') == [('only', SOURCE + '1')]
    with pytest.raises(ValueError):
        registry.run('not_declared', source=SOURCE, name='f')


def test_a_replaced_module_function_is_the_one_that_runs(monkeypatch):
    repair = registry.get('string_walk_index')
    module = importlib.import_module('decomprepair.string_walk_index')
    monkeypatch.setattr(module, 'variants', lambda source, name: [source + 'patched'])
    assert registry.run('string_walk_index', source=SOURCE, name='f') == [('string_walk_index', SOURCE + 'patched')]
    assert repair.function() is module.variants
