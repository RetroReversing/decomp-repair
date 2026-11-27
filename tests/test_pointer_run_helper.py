"""The statements that read one freshly built pointer, written as a `static inline` helper that takes it."""
from decomprepair import pointer_run_helper

SOURCE = """typedef struct { u8 speed; u8 vol; } Env;
typedef struct { u8 index; u8 speed; u8 vol; s32 calc; Env *envs; s32 note; } Chan;
extern void tick(Chan *c);

void play(Chan *cp)
{
    Env *env;
    u8 rate;
    s32 note;

    note = cp->note;
    if (note) {
        env = &cp->envs[cp->index];
        rate = env->speed;
        if (rate == 0)
            rate = 1;
        cp->speed = rate;
        cp->calc = 0x400 / rate;
        cp->vol = env->vol;
        cp->calc += rate;
        cp->note = note;
    }
    tick(cp);
}
"""


def children(source):
    return [child for family, child in pointer_run_helper.variants(source, 'play') if family == 'pointer_run_helper']


def test_helper_takes_the_pointer_and_copies_it():
    copied, direct = children(SOURCE)
    assert 'static inline void play_step(Chan *cp, Env *env_in)\n{\n  Env *env = env_in;' in copied
    assert 'play_step(cp, &cp->envs[cp->index]);' in copied
    assert 'static inline void play_step(Chan *cp, Env *env)' in direct
    for child in (copied, direct):
        main = child[child.index('void play(Chan *cp)'):]
        # the run is gone from the function, with the pointer and the temporary only it used
        assert 'Env *env;' not in main and 'u8 rate;' not in main and 'env =' not in main
        # what comes after the run stays
        assert 'cp->note = note;' in main and 'tick(cp);' in main
        helper = child[:child.index('void play(Chan *cp)')]
        assert 'u8 rate;' in helper and 'cp->calc += rate;' in helper


def test_a_call_that_builds_the_pointer_does_not_move():
    assert children(SOURCE.replace('&cp->envs[cp->index]', 'lookup(cp)')) == []


def test_a_pointer_read_after_the_run_is_left_alone():
    # a later read of the pointer keeps it in the run too; a run that would need a value passed by address is not offered
    source = SOURCE.replace('    tick(cp);', '    tick(cp);\n    cp->vol = env->vol;')
    assert all('Env **' not in child for child in children(source))


def test_a_short_run_is_not_worth_a_function():
    source = """typedef struct { u8 a; u8 b; } Rec;
extern Rec table[];
void play(s32 i)
{
    Rec *r;
    r = &table[i];
    r->a = 0;
    r->b = 1;
}
"""
    assert children(source) == []


def test_the_run_ends_where_its_temporary_is_assigned_afresh():
    source = SOURCE.replace('        cp->note = note;\n', '        rate = cp->index;\n        cp->note = rate;\n')
    helper = children(source)[0].split('void play(Chan *cp)')[0]
    assert 'cp->calc += rate;' in helper and 'cp->index;\n' not in helper
