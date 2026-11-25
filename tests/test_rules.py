"""Declarative rules (rules.py): a repair as a JSON file the registry, and so the Deep Permuter, runs."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

from decomprepair import abs_idiom as ab
from decomprepair import registry, rules

ASM = '''glabel f
/* 0 80001000 04420001 */  bltzl      $v0, .L80001008
/* 4 80001004 00021023 */  negu       $v0, $v0
.L80001008:
/* 8 80001008 03E00008 */  jr         $ra
endlabel f
'''
TWO = '''void f(void *arg0) {
    s32 var_v0;
    s32 var_v0_2;
    s32 temp_ft1;

    var_v0 = (s32) (M2C_FIELD(arg0, f32 *, 4) - M2C_FIELD(arg0, f32 *, 8));
    if (var_v0 < 0) {
        var_v0 = -var_v0;
    }
    temp_ft1 = (s32) M2C_FIELD(arg0, f32 *, 0xC);
    var_v0_2 = temp_ft1;
    if (temp_ft1 < 0) {
        var_v0_2 = -var_v0_2;
    }
}
'''
BARE = 'void f(s32 a) {\n    if (a < 0) {\n        a = -a;\n    }\n    g(a);\n}\n'
MANY = 'void f(s32 a) {\n' + ''.join(f'    if (a < 0) {{\n        a = -a;\n    }}\n    g{i}(a);\n' for i in range(10)) + '}\n'
PLUS_ONE = {'schema': 1, 'id': 'plus_one', 'families': ['plus_one'],
            'sites': [{'match': r'^(?P<lead>[ \t]*)(?P<v>@IDENT@)\s*=\s*(?P=v)\s*\+\s*1\s*;',
                       'replace': '{lead}{v}++;'}],
            'children': {'all': 'plus_one'}}
SOURCE = 'void f(void)\n{\n    i = i + 1;\n}\n'


def write(folder, rule, name=None):
    path = pathlib.Path(folder) / f'{name or rule["id"]}.json'
    path.write_text(json.dumps(rule), encoding='utf-8')
    return path


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv(rules.ENVIRONMENT, str(tmp_path))
    return tmp_path


# the shipped rule

@pytest.mark.parametrize('source, asm, header', [
    (TWO, ASM, ''),
    (BARE, ASM, 'int abs(int);\n'),
    (BARE, ASM, ''),
    (TWO, ASM.replace('negu', 'addu'), ''),
    (TWO, ASM.replace('negu       $v0, $v0', 'subu       $v0, $zero, $v0'), ''),
    (TWO, ASM.replace('negu       $v0, $v0', 'subu       $v0, $v1, $v0'), ''),
    (TWO.replace('s32 var_v0;', 'f32 var_v0;'), ASM, ''),
    (BARE.replace('< 0', '< 1'), ASM, ''),
    (BARE.replace('}\n    g(a)', '} else {\n        g();\n    }\n    g(a)'), ASM, ''),
    (BARE.replace('s32 a', 'void *a'), ASM, ''),
    (MANY, ASM, ''),
    ('int abs(int);\n' + TWO, ASM, ''),
], ids=['two', 'bare-declared', 'bare', 'no-negate', 'subu-zero', 'subu-other', 'float', 'not-zero', 'else', 'pointer',
        'many', 'abs-in-source'])
def test_the_abs_idiom_rule_makes_what_the_module_made(source, asm, header):
    rule = rules.loaded()['abs_idiom']
    assert rules.apply(rule, source, 'f', asm, header) == ab.variants(source, 'f', asm, header)


def test_the_abs_idiom_rule_is_declared_once_with_the_modules_facts():
    declared = [r for r in registry.declared() if r.module in ('abs_idiom', 'rule:abs_idiom')]
    assert [r.module for r in declared] == ['rule:abs_idiom']
    repair = declared[0]
    assert repair.rule and repair.families == ('abs_idiom', 'abs_idiom_one') and repair.order == 63
    assert repair.needs == ('source', 'name', 'asm', 'header') and repair.archs == ('mips',)
    assert registry.problems(repair) == []
    assert repair.runs_in('local', 'mips') and not repair.runs_in('local', 'ppc')


def test_every_packaged_rule_is_valid():
    files = sorted(rules.PACKAGED.glob('*.json'))
    assert files
    for path in files:
        assert rules.problems(json.loads(path.read_text(encoding='utf-8'))) == [], path.name
    assert not [p for p in rules.skipped() if p.startswith(str(rules.PACKAGED))]


def test_the_registry_runs_a_rule_by_name_with_labelled_children():
    out = registry.run('rule:abs_idiom', source=TWO, name='f', asm=ASM, header='', arch='mips')
    assert [family for family, _ in out] == ['abs_idiom', 'abs_idiom_one', 'abs_idiom_one']
    assert out == ab.variants(TWO, 'f', ASM, '')


# rules from a folder

def test_a_rule_file_in_the_folder_is_run_without_clearing_any_cache(folder):
    assert registry.get('rule:plus_one') is None
    write(folder, PLUS_ONE)
    repair = registry.get('rule:plus_one')
    assert repair is not None and registry.problems(repair) == []
    assert registry.run('rule:plus_one', source=SOURCE, name='f') == [('plus_one', 'void f(void)\n{\n    i++;\n}\n')]


def test_a_changed_rule_file_is_read_again_and_a_removed_one_goes(folder):
    path = write(folder, PLUS_ONE)
    assert registry.run('rule:plus_one', source=SOURCE, name='f')[0][1].count('i++') == 1
    changed = json.loads(path.read_text())
    changed['sites'][0]['replace'] = '{lead}{v} += 1;'
    write(folder, changed)
    os.utime(path, ns=(1, path.stat().st_mtime_ns + 5_000_000_000))
    assert 'i += 1;' in registry.run('rule:plus_one', source=SOURCE, name='f')[0][1]
    path.unlink()
    assert registry.get('rule:plus_one') is None


def test_the_deep_permuters_subprocess_finds_a_rule_in_the_folder(folder):
    """The local lane calls `decomprepair.registry.run` by name in a subprocess: it gets the folder from the environment."""
    write(folder, PLUS_ONE)
    code = ("import json, sys; from decomprepair import registry; "
            "print(json.dumps(registry.run('rule:plus_one', source=sys.argv[1], name='f')))")
    done = subprocess.run([sys.executable, '-c', code, SOURCE], capture_output=True, text=True, timeout=120,
                          env={**os.environ, rules.ENVIRONMENT: str(folder)})
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [['plus_one', 'void f(void)\n{\n    i++;\n}\n']]


def test_a_bad_file_is_skipped_with_a_reason_and_the_others_still_run(folder):
    write(folder, PLUS_ONE)
    (folder / 'broken.json').write_text('{not json', encoding='utf-8')
    write(folder, {**PLUS_ONE, 'id': 'second', 'families': ['nope'], 'sites': []}, 'second')
    skipped = rules.skipped()
    assert str(folder / 'broken.json') in skipped and str(folder / 'second.json') in skipped
    assert 'sites' in skipped[str(folder / 'second.json')]
    assert registry.get('rule:plus_one') is not None and registry.get('rule:second') is None
    assert all(registry.problems(repair) == [] for repair in registry.declared())


def test_a_rule_cannot_take_the_id_of_one_already_loaded(folder):
    write(folder, {**PLUS_ONE, 'id': 'abs_idiom'}, 'mine')
    assert 'already used' in rules.skipped()[str(folder / 'mine.json')]
    assert rules.loaded()['abs_idiom'].path.endswith(str(pathlib.Path('rules') / 'abs_idiom.json'))


def test_a_rule_with_a_gate_and_a_prototype_asks_for_the_context_it_reads():
    compiled = rules.loaded()['abs_idiom']
    assert compiled.needs == ('source', 'name', 'asm', 'header')
    assert rules.compile_rule(PLUS_ONE).needs == ('source', 'name')


# what a rule may not be

def broken(**changes):
    rule = json.loads(json.dumps(PLUS_ONE))
    rule.update(changes)
    return rule


def site(**changes):
    return {**PLUS_ONE['sites'][0], **changes}


@pytest.mark.parametrize('rule, word', [
    (broken(schema=2), 'schema'),
    (broken(id='Not A Name'), 'id'),
    (broken(extra=1), 'unknown keys'),
    (broken(families=[]), 'families'),
    (broken(archs=['z80']), 'archs'),
    (broken(lanes=['nowhere']), 'lanes'),
    (broken(order='first'), 'order'),
    (broken(gate=[{'asm_has': []}]), 'gate'),
    (broken(gate=[{'run': 'rm -rf'}]), 'gate'),
    (broken(sites=[]), 'sites'),
    (broken(sites=[site()] * 9), 'sites'),
    (broken(sites=[site(match='(')]), 'regular expression'),
    (broken(sites=[site(match='(?P<v>a+)+b')]), 'repeats'),
    (broken(sites=[site(match=r'((?:ab)+)*c')]), 'repeats'),
    (broken(sites=[site(match='x*')]), 'empty'),
    (broken(sites=[site(match='a' * 2001)]), 'longer'),
    (broken(sites=[site(replace='{nope}')]), 'no group'),
    (broken(sites=[site(where=[{'run': 'x'}])]), 'unknown guard'),
    (broken(sites=[site(where=[{'declared_type': {'group': 'nope', 'kind': 'integer'}}])]), 'declared_type'),
    (broken(sites=[site(where=[{'declared_type': {'group': 'v', 'kind': 'pointer'}}])]), 'declared_type'),
    (broken(prepend_unless_declared={'pattern': '(', 'text': 'x'}), 'prepend'),
    (broken(children={}), 'children'),
    (broken(children={'all': 'other'}), 'children.all'),
    (broken(children={'each': {'family': 'plus_one', 'max': 99}}), 'max'),
    ('a string', 'object'),
])
def test_what_a_rule_may_not_be_is_refused_with_a_sentence(rule, word):
    found = rules.problems(rule)
    assert found and any(word in sentence for sentence in found), found
    with pytest.raises(ValueError):
        rules.compile_rule(rule)


def test_patterns_that_repeat_a_repeat_are_found_and_plain_ones_are_not():
    assert rules._fail_on_repeated_group(r'(a+)+')
    assert rules._fail_on_repeated_group(r'(?:\s*x*)*')
    assert rules._fail_on_repeated_group(r'(a|b*){2,}')
    assert not rules._fail_on_repeated_group(r'(?P<v>[a-z_]\w*)\s*=\s*(?P=v)\s*\+\s*1')
    assert not rules._fail_on_repeated_group(r'(?!\s*else\b)')
    assert not rules._fail_on_repeated_group(r'[(+*]+x')
    assert not rules._fail_on_repeated_group(r'\(a+\)+')


def test_a_giant_function_is_left_alone(folder):
    rule = rules.compile_rule(PLUS_ONE)
    huge = 'void f(void)\n{\n    i = i + 1;\n' + '    g();\n' * 60_000 + '}\n'
    assert len(huge) > rules.MAX_BODY and rules.apply(rule, huge, 'f') == []
