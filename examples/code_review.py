# pip install openai
# export OPENAI_API_KEY=sk-...

import asyncio
import time

from openai import AsyncOpenAI, OpenAI

from teel import Teel, cacheable, jit

MODEL = "gpt-4o-mini"

client = OpenAI()
async_client = AsyncOpenAI()

DIFF = {
    "billing.py": """
def average_invoice(invoices):
    total = sum(invoice.amount for invoice in invoices)
    return total / len(invoices)
""",
    "retry.py": """
def fetch(url, attempts=5):
    while attempts:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
    raise RuntimeError("giving up")
""",
    "session.py": """
class Session:
    def __init__(self, user, scopes=[]):
        self.user = user
        self.scopes = scopes
""",
}


@cacheable
def llm(prompt):
    completion = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return completion.choices[0].message.content.strip()


@jit
def request_changes(report):
    patch = llm(f"Suggest a minimal patch for the worst issue below.\n\n{report}")
    return f"CHANGES REQUESTED\n\n{report}\n\nSuggested fix:\n{patch}"


@jit
def approve(report):
    note = llm(f"Write a one-line approval comment for these findings.\n\n{report}")
    return f"APPROVED\n\n{report}\n\n{note}"


@jit
def review(diff):
    findings = [
        llm(f"Name the single worst bug in one sentence.\n\nFile: {name}\n{body}")
        for name, body in diff.items()
    ]
    report = "\n".join(findings)
    verdict = llm(f"Do these findings block a merge? Answer yes or no.\n\n{report}")
    if verdict.lower().startswith("yes"):
        return request_changes(report)
    return approve(report)


async def async_llm(prompt):
    completion = await async_client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return completion.choices[0].message.content.strip()


async def async_request_changes(report):
    patch = await async_llm(
        f"Suggest a minimal patch for the worst issue below.\n\n{report}"
    )
    return f"CHANGES REQUESTED\n\n{report}\n\nSuggested fix:\n{patch}"


async def async_approve(report):
    note = await async_llm(
        f"Write a one-line approval comment for these findings.\n\n{report}"
    )
    return f"APPROVED\n\n{report}\n\n{note}"


async def async_review(diff):
    findings = await asyncio.gather(
        *(
            async_llm(
                f"Name the single worst bug in one sentence.\n\nFile: {name}\n{body}"
            )
            for name, body in diff.items()
        )
    )
    report = "\n".join(findings)
    verdict_task = asyncio.create_task(
        async_llm(f"Do these findings block a merge? Answer yes or no.\n\n{report}")
    )
    changes_task = asyncio.create_task(async_request_changes(report))
    approve_task = asyncio.create_task(async_approve(report))
    try:
        verdict = await verdict_task
        if verdict.lower().startswith("yes"):
            approve_task.cancel()
            return await changes_task
        changes_task.cancel()
        return await approve_task
    finally:
        for task in (verdict_task, changes_task, approve_task):
            task.cancel()


def time_it():
    before = time.perf_counter()
    review(DIFF)
    after = time.perf_counter()
    return after - before


def time_async():
    before = time.perf_counter()
    asyncio.run(async_review(DIFF))
    after = time.perf_counter()
    return after - before


def main(trace_path="teel-trace.json"):
    baseline = time_it()
    print(f"Without Teel: {baseline:.1f}s")

    with Teel(trace_path=trace_path):
        optimized = time_it()
    print(f"With Teel: {optimized:.1f}s")

    print(f"With asyncio: {time_async():.1f}s")


if __name__ == "__main__":
    main()
