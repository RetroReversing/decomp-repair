from decomprepair import registry
from decomprepair.typed_run_slide import FAMILY, variants

SOURCE = """typedef struct { u16 x; s16 scale; s32 vx, vy; u16 type; u8 slot, flag, state; } Ent;
void step(Ent *);
s32 touching(Ent *);
extern u16 next[];
void f(Ent *self) {
    u16 tries;
    tries = 0;
    while (touching(self)) {
        tries++;
        self->x += 1;
        self->x += 2;
        step(self);
        if (tries > 1000) {
            break;
        }
    }
    self->flag = 0;
    self->state = 1;
    self->scale = 0x1400;
    self->vx = self->vy = 0;
    self->type = next[self->slot];
}
"""


def children(source):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def squeeze(text):
    return ' '.join(text.split())


def test_the_counter_steps_below_the_call():
    assert any('step(self); tries++; if' in squeeze(text) for text in children(SOURCE))


def test_a_table_store_passes_typed_members_and_a_chain():
    assert any('self->flag = 0; self->type = next[self->slot]; self->state = 1;' in squeeze(text)
               for text in children(SOURCE))


def test_a_store_never_passes_the_read_of_what_it_writes():
    source = SOURCE.replace('self->flag = 0;', 'self->slot = 0;')
    assert not any(text.index('self->type = next') < text.index('self->slot = 0;') for text in children(source))


def test_a_chain_writes_every_target():
    source = SOURCE.replace('self->type = next[self->slot];', 'self->type = self->vy;')
    assert not any(text.index('self->type = self->vy') < text.index('self->vx = self->vy = 0') for text in children(source))


def test_a_member_does_not_pass_a_call():
    assert not any(text.index('self->x += 2;') > text.index('step(self);') for text in children(SOURCE))


def test_a_counter_whose_address_is_taken_stays():
    source = SOURCE.replace('tries = 0;', 'tries = 0; use(&tries);')
    assert not any('step(self); tries++;' in squeeze(text) for text in children(source))


def test_it_is_registered():
    assert FAMILY in {family for repair in registry.declared() for family in repair.families}


def test_native_variants_match_interpreted_output(tmp_path):
    import importlib.util
    import json
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    import pytest

    import decomprepair

    if any(importlib.util.find_spec(name) is None for name in ('Cython', 'setuptools')):
        pytest.skip('Building the native repair needs Cython and setuptools')
    package = tmp_path / 'decomprepair'
    shutil.copytree(Path(decomprepair.__file__).parent, package,
                    ignore=shutil.ignore_patterns('__pycache__', '_compiled*', '_objects*', '*.so', '*.pyd'))
    subprocess.run([sys.executable, str(package / 'native_build.py'), '--only', 'typed_run_slide'],
                   check=True, capture_output=True, timeout=120)
    run = subprocess.run(
        [sys.executable, '-X', 'faulthandler', '-c',
         'import json,sys; from decomprepair.typed_run_slide import variants; '
         'assert type(variants).__name__ == "cython_function_or_method"; '
         'print(json.dumps(variants(sys.stdin.read(), "f")))'],
        env=dict(os.environ, PYTHONPATH=str(tmp_path)), input=SOURCE,
        text=True, capture_output=True, timeout=15, cwd=tmp_path,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [[family, text] for family, text in variants(SOURCE, 'f')]
