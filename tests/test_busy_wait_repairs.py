"""Globals an empty loop waits on, declared volatile."""
from decomprepair import busy_wait_repairs as b

SOURCE = '''extern u16 D_800E426A;
extern u8 D_800E4214;
extern s32 D_800E4230;

void f(void) {
    D_800E426A = g();
    do {

    } while ((D_800E426A << 0x10) > 0);
    if (D_800E4230 != 0) {
        h(D_800E4230);
    }
    while (D_800E4214 != 0);
}
'''


def test_every_waited_global_together_then_each():
    # An N64 function with two waits: exact with both volatile, 99.9% with one, worse with the other alone.
    (family, both), (_, first), (_, second) = b.variants(SOURCE, 'f')
    assert family == 'busy_wait_volatile'
    assert 'extern volatile u16 D_800E426A;' in both and 'extern volatile u8 D_800E4214;' in both
    assert 'extern volatile u16 D_800E426A;' in first and 'extern u8 D_800E4214;' in first
    assert 'extern volatile u8 D_800E4214;' in second
    assert all('extern s32 D_800E4230;' in t for _, t in b.variants(SOURCE, 'f'))  # not waited on


def test_left_alone_without_an_empty_loop():
    busy = SOURCE.replace('    do {\n\n    } while', '    do {\n        k();\n    } while').replace(
        '    while (D_800E4214 != 0);\n', '    while (D_800E4214 != 0) {\n        k();\n    }\n')
    assert b.variants(busy, 'f') == []
    already = SOURCE.replace('extern u16 D_800E426A;', 'extern volatile u16 D_800E426A;')
    assert [t for _, t in b.variants(already, 'f')] == [SOURCE.replace('extern u16 D_800E426A;', 'extern volatile u16 D_800E426A;').replace('extern u8 D_800E4214;', 'extern volatile u8 D_800E4214;')]


def test_propose_finds_it():
    from decomprepair.propose import propose
    assert any(p.module == 'busy_wait_repairs' for p in propose(SOURCE, 'f').proposals)
