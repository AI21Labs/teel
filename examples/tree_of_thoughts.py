# pip install tree-of-thoughts-llm --no-deps
# pip install openai==0.27.7 numpy backoff sympy pandas

import time
import argparse
import teel
import random

from tot.methods import bfs
from tot.methods.bfs import solve
from tot.tasks.game24 import Game24Task

bfs.gpt = teel.cacheable(bfs.gpt)

for fn in (
    bfs.solve,
    bfs.get_values,
    bfs.get_value,
    bfs.get_proposals,
    bfs.get_samples,
    bfs.get_votes,
):
    teel.jit(fn)

for wrap in (
    Game24Task.value_prompt_wrap,
    Game24Task.propose_prompt_wrap,
    Game24Task.standard_prompt_wrap,
    Game24Task.cot_prompt_wrap,
):
    teel.inline(wrap)


def time_it():
    before = time.perf_counter()
    solve(args, task, idx)
    after = time.perf_counter()
    return after - before


if __name__ == "__main__":
    args = argparse.Namespace(
        backend="gpt-4",
        temperature=0.7,
        task="game24",
        naive_run=False,
        prompt_sample=None,
        method_generate="propose",
        method_evaluate="value",
        method_select="greedy",
        n_generate_sample=1,
        n_evaluate_sample=3,
        n_select_sample=5,
    )

    task = Game24Task()
    idx = random.choice(range(len(task.data)))

    normal_dur = time_it()

    with teel.Teel(max_workers=32):
        optimized_dur = time_it()

    print(f"Sample #{idx} normal {normal_dur:.2f}s optimized {optimized_dur:.2f}s")
