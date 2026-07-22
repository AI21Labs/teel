# Teel

## Making synchronous code run faster

A lot of approaches to writing faster code involves introducing concurrent concepts like futures or coroutines, trading off simplicity for performance.
Before you know it, your code is filled with concurrency bits like `.result()` or `asyncio.gather`.
We believe the latter should not be mixed with the "main" code itself, which should be kept as simple as possible.
These concurrency-related considerations should be kept outside.

What do we propose?
We start with completely synchronous code.
The plain way a developer would write it for a single thread without an event loop.
The problem with such code is that everything runs sequentially and therefore slow.
An already known trick which makes things speed up a bit is the use involves decorating certain "heavy" functions with `@functools.cache`.
This makes the decorated functions store/use input-ouptut pairs of invocations and thus run in near zero time on cache hits.
That's nice but it's insufficient - it relies on these cache hits.
We want to increase the likelyhood of such cache hits.

Consider the following simple snippet:

```python
y = f1(x)
z = f2(x)
w = f3(y, z)
```

Assume all functions `f1, f2, f3` are cacheable and each of them takes about a second to complete.
In a normal run, when everything runs sequentially, this code take about 3 seconds to complete.
In an optimized run, the following happens:

1. MainThread is just about to execute `f1(x)`.
2. MainThread magically realizes that the `f2(x)` is on the horizon and submits its execution on a ThreadPoolExecutor.
3. MainThread executes `f1(x)`.
4. MainThread is just about to execute `f2(x)`. By this point either the result of `f2(x)` is already in the cache (because ThreadPoolExecutor finished running it) or it's still in progress (but about to finish). If it's in the cache - MainThread returns it immediately. Otherwise - MainThread waits for ThreadPoolExecutor to complete its computation.
5. MainThread exectues `f3(y, z)`.

That's basically the deal - the developer marks certain functions as "cache-able" and we add the necessary magic to make sequential code run optimized by submitting these functions to be ran on multiple threads *ahead of time*.
This lookahead mechanism does not have to perfect - it operates on a best effort basis sniffing out possible future calls to cache-able functions.
It does need to operate relatively fast - more accurately, faster than the time it takes to run a function on cache miss (else we don't reduce runtime).
What this lookahead must not do is mutate state tied to the MainThread run, otherwise we risk corrupting the execution.

## The API you actually write

The API is thin - just three decorators and one context manager.
Your "heavy" functions - the ones that are cache-able and you wish we will auto-parallelize for you - you mark them with `@cacheable`.
The cache key for these calls will be based on a `json.dumps` of the arguments (so don't throw in there any funky stuff).
The functions you want us to sip through their bytecodes in search of future calls - you mark with `@jit`.
Optionally, you can help us help you by decorating with `@inline` fast helper functions (like ones for string formatting or dict access) that the shadow interpreter can safely execute, instead of skipping them.
Inline functions would help the shadow interpreter expand its ready-to-execute-horizon of calls (in simple words - likely more stuff will be submitted ahead-of-time).
Last but not least - you need to wrap what you want to execute with a `with Teel(): ...` to activate this whole magic (otherwise it just runs synchronously).

Because we dispatch `@cacheable` functions speculatively/eagerly/ahead-of-time (pick your favorite adjective), these functions must be pure and idempotent - that means same output for same input and no side effects.
The whole caching thing by `(func, json.dumps(args))` pair and performing not-yet-determined conditional jumps relies on the promise that invoking these `@cacheable` functions in these creative/wild ways will not break the main run and its correctness.

## Lookahead mechanism

We step in right before the executing of a `@cacheable` decorated function.
When we reach such a point, just before calling the function, we initiate the lookahead search.
This is done by copying the execution state and running a limited "shadow interpreter" to find subsequent calls.
Python offers a lot of introspection through `sys._getframe()`.
We use the latter function to retrieve the frame stack, each with its own local and global variables.
Python does not offer visibility into the value stack of each frame, so we wrote a small C extension that retrives it.
We use `f_lasti` of each frame to know the last bytecode instruction that was executed.
We use the builtin `dis` module to disassemble the `@jit`-decorated functions (by decorating with `@jit` you agree that we go through your bytecode in search for future calls).
We copy this state and run the shadow interpreter which "resumes" the execution and collects future calls as it runs.

The shadow interpreter boils down to a long loop that iterates over bytecode opcodes, processing these opcodes and mutating its own shadow value stack per frame - it's a (obviosuly slower) reimplementation of CPython's loop but it can handle pending (not yet evaluated) values and it cautiously does copy-on-write as to not screw with the state of the main thread.

The shadow interpreter may:

1. Step into (user decorated) functions and shadow-execute them as well.
2. Skip instructions/calls that cannot yet be executed - marking them as "pending".
3. Run (by regular invocation) certain (user deocrated) inline functions that it deems safe to run (not going to corrupt the main state).
4. Perform copy-on-write on mutating instructions, further maintaing a shadow state while keep the main state intact.
5. Perform speculative execution by cloning state and following conditional jump instructions (up to configured width/depth to avoid exponential explosion).

The shadow interpreter returns a list of function calls that are submitted to ThreadPoolExecutor to be executed in the background.
This hopefully makes the cache-able functions cache warm up before MainThread reaches them, thus reducing runtime.
After submitting the background calls, we allow MainThread to go about executing the function it entered.
These background calls, when they finish, can also trigger more searches and thus more background calls (until MainThread reaches another point in the execution where the previous generation of pending background calls is discarded in favor of a new one).
This ability of piercing into (multiple potential) futures enables us to infer runtime parallelism by deducing dependencies and pre-invoking functions on speculative execution and thus reducing runtime.

## Caching calls by their inputs

Lookahead search can be performed from multiple threads and places and so the same (with equal arguments) function call can be discovered (and submitted) multiple times.
We keep a dict of pending/done tasks, keyed by the function itself and `json.dumps` of the input arguments, in order to execute just one instance of such call+arguments pair.
The first thread in the race to execute that future call gets to own it while the other threads, if they stumble upon the same call, either wait for that thread to finish or just grab its result if it already finished.
Worth noting that f the owner's call failed, we choose not to cache the failure and we assume it's retryable (might be worth to revisit this notion and retry only for specific exceptions).

## Tracing

You can provide `Teel()` with a `trace_path=` and we will record a timeline of `@cacheable`-decorated execution, so you'll be able to see just what exactly run in parallel.
The output file is saved in a Chrome trace-event json which can be opened at at [ui.perfetto.dev](https://ui.perfetto.dev/) to view the timline.
In additional to start/end times and durations, you can see in the UI that each call has its own index (`callno`) and the index of the call it originated from (`parent_callno`).
In the example above, the `f2` call is the parent of the `f3` call (because the `f3` call was discovered in a lookahead search conducted at the `f2` point).

## Testing

The small `tests/test_lookahead.py` (desparately needs to grow in size) helps with both making sure the search can agree with the CPython interpreter about the return value of a function and more important that it doesn't mutate any state that might affect the CPython outcome.

## Example: Tree of Thoughts

We took [Princeton's `tree-of-thoughts-llm`](https://github.com/princeton-nlp/tree-of-thought-llm), unmodified, and ran several samples of the "Game of 24" dataset with GPT-4.
We applied our decorators outside of the original code, decorating `@jit`, `@cacheable` and `@inline`.
Because the original is written in a naive synchronous code we managed to get an average reduction of 83% in runtime compared to regular execution (from as low as 148s optimized into 24s and as high as 307s optimized into 38s).

## Example: Recursive Language Models in Deep Agents

We took LangChain's Deep Agents (specifically the Deep Agents Code CLI, or `dcode`) for a spin.
See [How to Use RLMs in Deep Agents](https://www.langchain.com/blog/how-to-use-rlms-in-deep-agents).
The `dcode` CLI comes with an RLM-based `js_eval` tool - the model can choose to use it to run a Javascript snippet. The snippet *itself* can contain tool calls (such as `tools.web_search()`) and also a call to `task()` which runs a subagent (with its own context) as part of the snippet execution, achieving the recursion.
The snippet is run in a sandboxed environment using QuickJS.
Putting isolation aside, we wanted to measure the effect on the runtime if we replaced the (async) JS with synchronous Python, freeing the LLM from async considerations in writing the code.
We ran several prompts whose solutions involve a mixture of web search and LLM calls to be solved end-to-end by a single snippet.
Compared to synchrnous python we can see substantial improvement.
We for the JS comparison - we noticed a slight improvement.
Taken with a grain of salt (because event the same prompt produces different JS and Python solutions), we can point out that not all JS snippets use `Promise.all` where they should (instead of just `await`) and that JS doesn't bother pre-running fallback logic ("do B if A was unsatisfactory"), unlike `Teel` which speculatively runs these fallbacks ahead of time.

Running 10 prompts as described, on average Teel takes 58s, original async JS takes 71s and plain synchronous Python takes 150s.
This is 61% faster than plain synchronous Python and 19% faster than the JS baseline.

## GIL peskiness

In the current implementation we ship background calls to a `ThreadPoolExecutor`.
If your `@cacheable` does I/O or network work (like `requests.get`) or GIL-free CPU work (`numpy`) then you're good to go.
If your `@cacheable` is CPU-bound and also GIL-constrained then no dice.
It's not really a difficult hurdle to implement - either by switching to `ProcessPoolExecutor` or
`InterpreterPoolExecutor` (but that's been added only in Python 3.14), but it's not currently an option in the code.

## Try it out

To install and run:

```
uv sync
uv run python -m examples.hello_world
```

The `uv sync` commands takes care of building the `frameinspect` C extension.
The `hello_world` example runs an insanely simple diamond pipeline with and without `Teel`, prints time metrics and saves a timeline into `teel-trace.json`, available for viewing at [ui.perfetto.dev](https://ui.perfetto.dev/).
Note that we currently have a hard constraint on exact Python version 3.12.13.
This is because `frameinspect.c` needs CPython's internal headers, so if you're running with a different Python version you may need to adjust the extension.

## Disclaimer

This is a Proof-of-Concept.
Further work needs to be done to adjust this for other CPython versions.
