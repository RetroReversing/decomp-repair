# decomp-repair

Targeted C rewrites for matching decompilation. Give it a function's C. It returns variant sources, each
changing one thing the compiler is sensitive to: a literal, a local's lifetime, which register carries an
argument, how a branch is laid out, the order of stores. You compile each one with the game's original compiler
and keep it only when the bytes match.

It only proposes. It never compiles, and it never decides whether something matches: your compiler and your
judge (objdiff, a linked ROM, decomp.me) do that. That keeps it safe to run beside any matching workflow.

It complements [decomp-permuter](https://github.com/simonlindholm/decomp-permuter). The permuter makes thousands
of random tree changes. These are a few hundred deliberate rewrites, each tied to a pattern old compilers are
known for.

It started in [decompdecomp](https://github.com/RetroReversing/decompdecomp), which uses it in its repair
pipeline. This repository has kept its history.

## Status

MIPS first: most families and all the code readers understand MIPS (N64, PS1, PS2, PSP). Families that only read
C work for any processor. The interface may change before 1.0.

## Use

```bash
uv tool install git+https://github.com/RetroReversing/decomp-repair
decomprepair src/game.c --function func_80012345 --arch mips --out proposals/
decomprepair src/game.c --function func_80012345 --timing     # how long each family took
decomprepair src/game.c --function func_80012345 --json       # proposals and timings as JSON
```

From Python:

```python
from decomprepair.propose import propose

report = propose(source, 'func_80012345', arch='mips', header=header, asm=target_asm)
for proposal in report.proposals:
    print(proposal.family, proposal.module)   # compile proposal.source and compare the bytes
for timing in report.timings:
    print(timing.module, timing.ms, timing.skipped or timing.error)
```

Some families need more than the C: the header (`header`), the processor (`arch`), the target's assembly (`asm`)
or the compiler flags (`flags`). Leave an input out and those families are skipped; the report says which input
each one needed.

## Layout

The package is flat. Each `*_repairs.py` module is one family, with a `variants(source, name, ...)` function that
returns sources or `(label, source)` pairs. The other modules are the readers the families share: `csource` for C
text, `mips` and `mips_*` for MIPS code, `symbols` for symbol tables, `m2cfix` for m2c output. `propose.py` runs
them all.

The `mips_*` readers also give evidence about a byte difference that a repair can act on: argument and literal
differences, frame sizes, return paths, control-flow regions, runtime helpers, small leaf templates. They are
hints, never match verdicts. `mips_count`, `mips_compare`, `mips_status`, `mips_fcsr` and
`mips_status_return_spacing` propose fixed CP0/FPU leaves that C can't express; `mips_debug_break.header()` is the
header a compiler puts before each file so they compile, and their `candidate(asm, name, registered)` proposes only
when the caller says its compiler includes it.

The permuter's rewrites are here too. `permuter` makes simple random rewrites (statement and declaration order,
casts, `register`), `permuter_local` a few cheap ordering hypotheses, and `permuter_initialization` rejects variants
that read a local before it's set. `permuter_gen.py` is a program, not a module: run it by path with
[decomp-permuter](https://github.com/simonlindholm/decomp-permuter)'s Python and folder, and it writes that
randomizer's variants, guarded by its helpers beside it (`permuter_capture`, `permuter_dependencies`,
`permuter_formatting`). Running the candidates, compiling and scoring them is the caller's job.

## Develop

```bash
uv sync
uv run pytest -q
uv run ruff check src tests
```

Nothing in `src/decomprepair` may import decompdecomp (`decompnet`); `tests/test_library.py` checks this.

## License

AGPL-3.0-only (`LICENSE`), like decompdecomp, which this code comes from. Some readers began in decomp.wtf
(`LICENSE-decomp.wtf`).
