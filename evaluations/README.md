# Evaluations

Realistic, tool-picking questions for agents using `gitlab-ci-mcp`. Designed to
verify an LLM can (a) pick the right tool for the question, (b) supply correct
arguments, and (c) summarise the tool output back to the user.

The questions in `questions.xml` follow the shape recommended by the
[MCP server evaluation guide](https://modelcontextprotocol.io/). Each entry has:

- `<question>` — the phrasing a human would use
- `<answer>` — the expected tool name (and sometimes an argument value)
  the agent should pick. String comparison (case-insensitive).

Because answers are tool names / arg values, the questions are **stable** (don't
change with repo state) and **verifiable**.

## Running

This repo does not ship a runner — use your harness of choice. A minimal
Python runner looks like:

```python
import xml.etree.ElementTree as ET

tree = ET.parse("evaluations/questions.xml")
for qa in tree.iter("qa_pair"):
    question = qa.find("question").text
    expected = qa.find("answer").text.lower().strip()
    # send `question` to your agent with the MCP server attached
    predicted = run_agent(question)  # returns the tool name the agent called
    ok = expected in predicted.lower()
    print(f"{'✓' if ok else '✗'} {question}  expected={expected}  got={predicted}")
```

## Live-fixture evaluations

For richer evaluations against a real GitLab instance with a known data set,
spin up a test project with a fixed commit history and write questions like
"what's the success rate of the nightly schedule over 7 days" with a pinned
numeric answer. Not included here because it depends on your test fixture.
