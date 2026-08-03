# 🚀 Teel - Turbo-Efficient Execution Library

### Async magic for synchronous code

Since LLMs and Agents, a big portion of production code became IO-bound. 

A lot of approaches to writing faster code involve introducing concurrent concepts like futures or coroutines, trading off simplicity for performance.
Before you know it, your code is filled with concurrency bits like `.result()` or `asyncio.gather`.

We wanted to stop the async "mechanicals" of ruining the simplicity of our main logic.

## How it works

Consider the following simple snippet:

```python
y = f1(x)
z = f2(x)
w = f3(y, z)
```

Assume each function `f1, f2, f3` takes about a second to complete.
In a normal run, when everything runs sequentially, this code takes about 3 seconds to complete.

In an optimized run, the runtime magically realizes that the `f2(x)` is on the horizon and runs it in parallel.
When `f1(x)` finishes, `f2(x)` is magically ready as well - so we immediately execute `f3(y, z)`.

**A 33% of the time was saved 🚀**

That's basically the deal - 
Teel adds the necessary magic to make sequential code run optimized by submitting these functions to be run on multiple threads *ahead of time*.
This lookahead mechanism does not have to be perfect - it operates on a best effort basis, sniffing out possible future calls to cache-able functions.
The hard part is to make sure this does not mutate state tied to the MainThread run, otherwise we risk corrupting the execution.

### Speed-up Results

| Code | Original E2E duration | 🚀 Teel E2E duration | Speed-up |
|-------|----------------------|--------------------------|----------|
| [tree-of-thoughts-llm](https://github.com/princeton-nlp/tree-of-thought-llm) | 307s | 38s | 8.07x |
| RLM inside LangChain's Deep Agents (python) | 150s | 58s | 2.58x |
| RLM inside LangChain's Deep Agents (async JS) | 71s | 58s | 1.22x |


## Getting started with Teel

### 1. Install
Clone the repo 
```
git clone https://github.com/AI21Labs/teel.git
```

Install dependencies and run hello world:
```
uv sync
uv run python -m examples.hello_world
```

The `uv sync` command takes care of building the `frameinspect` C extension.
The `hello_world` example runs an insanely simple diamond pipeline with and without `Teel`, prints time metrics and saves a timeline into `teel-trace.json`, available for viewing at [ui.perfetto.dev](https://ui.perfetto.dev/).


>Note that we currently have a hard constraint on exact Python version 3.12.13.
>This is because `frameinspect.c` needs CPython's internal headers, so if you're running with a different Python version you may need to adjust the extension.


### 2. Turbo-charge your code

The API is thin - just three decorators and one context manager.

1. Mark your "heavy" functions (the ones that are cache-able and you wish to auto-parallelize) with `@cacheable`.
The cache key for these calls will be based on a `json.dumps` of the arguments (so don't throw in there any funky stuff).
```python
@cacheable
def heavy_calc(x, y, z):
  ...
```

2. Mark the main functions you want Teel to look for potential optimizations with `@jit`.
```python
@jit
def main():
  result = heavy_calc(a, b, c)
  ...
```

3. Optionally, decorate fast helper functions (like string formatting or dict access) with `@inline`. this helps adding more stuff to be submitted ahead-of-time.
```python
@inline
def get_user_data(raw_user):
  ...
  return raw_user.get('data', {}).get('result', None)
```

4. Wrap everything with a `with Teel(): ...` to activate the magic (otherwise it just runs synchronously).
```python
with Teel():
  main()
```

>Because Teel dispatches `@cacheable` functions ahead-of-time, these functions must be **pure and idempotent**, meaning they give the same output for same input, with no side effects. That means nothing that writes to a DB or randomly selects a return value.

### 3. Tracing

You can provide `Teel()` with a `trace_path=` and it will record a timeline of `@cacheable`-decorated execution, so you'll be able to see just what exactly ran in parallel.
The output file is saved in a Chrome trace-event json which can be opened at [ui.perfetto.dev](https://ui.perfetto.dev/) to view the timeline.
In addition to start/end times and durations, you can see in the UI that each call has its own index (`callno`) and the index of the call it originated from (`parent_callno`).
In the example above, the `f2` call is the parent of the `f3` call (because the `f3` call was discovered in a lookahead search conducted at the `f2` point).

## Under the hood

Teel's **lookahead mechanism** starts by duplicating the execution state into a limited "shadow interpreter". 
There it uses `sys._getframe()` to retrieve the frame stack, and applies a custom-written C extension that retrieves the frame's full value stack.
It uses `f_lasti` of each frame to know the last bytecode instruction that was executed.

The shadow interpreter iterates over bytecode opcodes, processing them and mutating its own shadow value stack per frame. Think of it as a (obviously slower) reimplementation of CPython's loop that can handle pending (not yet evaluated) values. It cautiously does copy-on-write as to not screw with the state of the main thread.

The shadow interpreter may:

1. Step into (user decorated) functions and shadow-execute them as well.
2. Skip instructions/calls that cannot yet be executed - marking them as "pending".
3. Run (by regular invocation) certain (user decorated) inline functions that it deems safe to run (not going to corrupt the main state).
4. Perform copy-on-write on mutating instructions, further maintaining a shadow state while keeping the main state intact.
5. Perform speculative execution by cloning state and following conditional jump instructions (up to configured width/depth to avoid exponential explosion).

The shadow interpreter submits function calls to be executed by ThreadPoolExecutor in the background. This makes the cache-able functions warmed up before MainThread reaches them, thus reducing runtime.

These background calls, when they finish, can also trigger more searches and thus more background calls (until MainThread reaches another point in the execution where the previous generation of pending background calls is discarded in favor of a new one).
This ability of piercing into (multiple potential) futures enables Teel to infer runtime parallelism by deducing dependencies and pre-invoking functions on speculative execution and thus reducing runtime.

### Caching calls by their inputs

Lookahead search can be performed from multiple threads and places and so the same (with equal arguments) function call can be discovered (and submitted) multiple times.
Teel keeps a dict of pending/done tasks, keyed by the function itself and `json.dumps` of the input arguments, in order to execute just one instance of such call+arguments pair.
Worth noting that if the owner's call failed, Teel does not cache the failure and assumes it's retryable (might be worth revisiting this notion and retry only for specific exceptions).

## Tests

The small `tests/test_lookahead.py` (desperately needs to grow in size) helps with both making sure the search can agree with the CPython interpreter about the return value of a function and more importantly that it doesn't mutate any state that might affect the CPython outcome.

## Examples

### Tree of Thoughts

We took [Princeton's `tree-of-thoughts-llm`](https://github.com/princeton-nlp/tree-of-thought-llm), unmodified, and ran several samples of the "Game of 24" dataset with GPT-4.


We applied our decorators outside of the original code, decorating `@jit`, `@cacheable` and `@inline`.


Because the original is written in naive synchronous code we managed to get an average reduction of 83% in runtime compared to regular execution (from as low as 148s optimized into 24s and as high as 307s optimized into 38s).

See [`examples/tree_of_thoughts.py`](examples/tree_of_thoughts.py).

### Recursive Language Models in Deep Agents

We took LangChain's Deep Agents (specifically the Deep Agents Code CLI, or `dcode`) for a spin.


See [How to Use RLMs in Deep Agents](https://www.langchain.com/blog/how-to-use-rlms-in-deep-agents).
Our [Deep Agents fork](https://github.com/AI21Labs/deepagents) uses Teel.

The `dcode` CLI comes with an RLM-based `js_eval` tool - the model can choose to use it to run a JavaScript snippet. The snippet *itself* can contain tool calls (such as `tools.web_search()`) and also a call to `task()` which runs a subagent (with its own context) as part of the snippet execution, achieving the recursion.

The snippet is run in a sandboxed environment using QuickJS.

Putting isolation aside, we wanted to measure the effect on the runtime if we replaced the (async) JS with synchronous Python, freeing the LLM from async considerations in writing the code.

We ran several prompts whose solutions involve a mixture of web search and LLM calls to be solved end-to-end by a single snippet.
Compared to synchronous Python we can see substantial improvement.
As for the JS comparison - we noticed a slight improvement.

Taken with a grain of salt (because even the same prompt produces different JS and Python solutions), we can point out that not all JS snippets use `Promise.all` where they should (instead of just `await`) and that JS doesn't bother pre-running fallback logic ("do B if A was unsatisfactory"), unlike `Teel` which speculatively runs these fallbacks ahead of time.

Running 10 prompts as described, on average Teel takes 58s, original async JS takes 71s and plain synchronous Python takes 150s.

This is 61% faster than plain synchronous Python and 19% faster than the JS baseline.

## GIL peskiness

In the current implementation we ship background calls to a `ThreadPoolExecutor`.
If your `@cacheable` does I/O or network work (like `requests.get`) or GIL-free CPU work (`numpy`) then you're good to go.
If your `@cacheable` is CPU-bound and also GIL-constrained then no dice.
It's not really a difficult hurdle to implement - either by switching to `ProcessPoolExecutor` or
`InterpreterPoolExecutor` (but that's been added only in Python 3.14), but it's not currently an option in the code.

## Disclaimer

This is a Proof-of-Concept.
Further work needs to be done to adjust this for other CPython versions.
