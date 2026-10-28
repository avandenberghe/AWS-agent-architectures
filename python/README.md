# AWS agent lab: Python

The Python version of the lab. The project overview, and what an agent is
architecturally, are in the [root README](../README.md).

Built on [Strands Agents](https://strandsagents.com) (`strands`) for the local
steps and boto3 (`bedrock-agentcore-control`, `bedrock-agentcore`) for the
published harness.

## Layout

| Path | What it is |
|---|---|
| `local_agent/hello_agent.py` | One model, one agent, one question. No tools |
| `local_agent/order_agent.py` | One tool, one call. The tool returns a fixed string, so it shows only the mechanism |
| `local_agent/ops_agent.py` | Two read-only boto3 tools: one checks a single model, one lists only the models this account can call. The first real loop |
| `agentcore_native/publish_agent.py` | Creates the IAM role and publishes the harness `lab_assistant_python`; each later run adds a version |
| `agentcore_native/run_agent.py` | Invokes the harness through an endpoint and holds a two-turn session |
| `agentcore_native/cleanup.py` | Lists harnesses, versions and endpoints. `--delete` removes the harness and its role |
| `agentcore_native/harness.py` | The names the three scripts share, and how to find the harness by name |
| `requirements.txt` | The three direct dependencies, pinned |
| `constraints.txt` | The full known-good dependency set, pulled in by `requirements.txt` |

`local_agent/` creates nothing in AWS: the agent exists only in the process.
`agentcore_native/` creates a harness and an IAM role in the account.

## Walkthrough

Run everything from the repo root, in this order. Steps 1 to 4 create nothing
in AWS; steps 5 to 8 do, and step 9 removes it again.

### 0. One-time setup

```bash
cp .env.example .env                 # then fill in AWS_PROFILE
python3 -m venv python/.venv && source python/.venv/bin/activate
pip install -r python/requirements.txt
aws login --profile <your-profile>   # repeat when the session expires
```

Requires Python 3.10+ (the lab uses 3.13) and the AWS CLI v2. Every script
finds the root `.env` by itself, so the working directory doesn't matter.

### 1. Hello: is the chain working?

```bash
python python/local_agent/hello_agent.py
```

One agent, one question, no tools. You should get a short answer about
Belgium's largest city. If this fails, nothing else will work: check
`aws login`, the profile in `.env`, and model access (root README, Setup).

### 2. Order: the model calls your code

```bash
python python/local_agent/order_agent.py
```

One tool. The model decides to call `get_order_status`, gets the fixed
string back, and phrases it. Two model calls for one question.

### 3. Ops: a real loop

```bash
python python/local_agent/ops_agent.py
```

Two tools, three or more model calls. Expected: Claude Opus 5.5 is not usable
yet (terms not accepted), followed by the models you can use instead.

### 4. Ops without the model (optional, free)

```bash
cd python/local_agent && ../.venv/bin/python -c "import ops_agent; print(ops_agent.list_usable_models())"; cd -
```

The tools are plain functions; this shows exactly what the model is given.

### 5. Publish: the agent becomes a resource

```bash
python python/agentcore_native/publish_agent.py
```

**Writes to your account.** Creates the IAM role `lab-assistant-python-harness`
(first run only) and the harness `lab_assistant_python`, version 1. Prints the
harness ID. Then open the [AgentCore console](https://eu-north-1.console.aws.amazon.com/bedrock-agentcore/home?region=eu-north-1)
→ **Agents**: it is listed, labelled *Harness*.

### 6. Run: talk to the published agent

```bash
python python/agentcore_native/run_agent.py
```

Two turns in one session. Turn 2 answers "eu-north-1", a question it can only
answer because the session remembers turn 1. Nothing in the script holds that
history. Cost: a fraction of a cent, plus about 5 minutes of microVM memory.

### 7. Versions (optional)

Change `INSTRUCTIONS` in `publish_agent.py` (say, "answer in Dutch"), then:

```bash
python python/agentcore_native/publish_agent.py   # prints version: 2
python python/agentcore_native/run_agent.py       # DEFAULT -> version 2: the new behaviour
```

To keep calling version 1, give it a named endpoint and run against that:

```bash
aws bedrock-agentcore-control create-harness-endpoint --region eu-north-1 \
  --harness-id <id from step 5> --endpoint-name stable --target-version 1
python python/agentcore_native/run_agent.py stable  # stable -> version 1: the old behaviour
```

### 8. Look at the traces (optional)

The console's **Agents** page shows sessions, traces and token use per agent
only after CloudWatch **Transaction Search** is enabled once for the account
(the *Configure* button on that page). It is billed as CloudWatch Logs, cents
for a lab. After enabling, wait about 10 minutes and run step 6 again.

### 9. Clean up

```bash
python python/agentcore_native/cleanup.py           # lists harness, versions, endpoints
python python/agentcore_native/cleanup.py --delete  # removes the harness, all versions, and the role
```

Steps 1 to 4 can be rerun any time and leave nothing behind.

## Python-specific notes

- **`boto3[crt]`, not `boto3`.** Credentials from `aws login` need the AWS
  Common Runtime. Plain boto3 fails with "Using the login credential provider
  requires an additional dependency".
- **The tool schema comes from your signature and docstring.** Strands uses
  the docstring's first paragraph as the tool description and its `Args:`
  section as the parameter descriptions; the Azure lab uses
  `Annotated[..., Field(description=...)]` for the same thing.
- **Synchronous by default.** `agent("...")` blocks and returns the result;
  `invoke_async()` exists. Agent Framework is async-only.
- **`callback_handler=None`.** Strands streams the answer to stdout by default.
  The scripts turn that off and print the finished result.
- **Harness names allow no hyphens.** Letters, digits and underscores: hence
  `lab_assistant_python`, while the IAM role is `lab-assistant-python-harness`.
- **No hand-written loop for the harness.** `run_agent.py` reads a stream of
  events (`contentBlockDelta`, `messageStop`, ...) and keeps only the text.

## Observed behaviour

- **Hello:** Nova 2 Lite and Nova Micro answer "Brussels"; the Azure lab's
  gpt-5.4-mini said "Antwerp". Both are defensible (region vs municipality).
  Same question, same instructions, different model.
- **Ops, first version:** the tools were a raw list of inference profiles
  plus a per-model check, and the instructions said to check every
  alternative before recommending it. Nova 2 Lite got the verdict on Claude
  Opus 5.5 right (terms not accepted), then recommended Claude Opus 5, Sonnet
  5.5, Haiku 5.5, GPT-6, Grok and others "already available". It had checked
  none of them, and none were usable. The list changed from run to run. Nova
  Micro did worse: it checked the wrong model and leaked its `<thinking>` tags
  and part of its system prompt into the answer.
- **Ops, fixed:** the check moved into code. `list_usable_models()` checks
  every EU profile itself (terms accepted, authorised, entitled, token quota
  above zero) and returns only the models that pass: the four Nova models and
  Mistral Pixtral Large. The agent now gives the same, correct answer on every
  run. Instructions are advice; if a check must happen, make it code.
- **Quotas have no model ID.** They are matched by display name, and the names
  don't always agree ("Pixtral Large (25.02)" vs "Pixtral Large 25.02 V1").
  The first version of the check missed Pixtral for that reason.
- **Harness session:** turn 2 remembers turn 1 with AgentCore Memory
  disabled. The session's microVM holds the conversation, so it lasts as long
  as the microVM: 5 idle minutes in this lab. Memory is what you'd add to make
  a conversation survive beyond that.
- **Region:** the first publish landed in us-east-1. boto3 reads `AWS_PROFILE`
  from the environment but not `AWS_REGION`, so the AgentCore clients fell back
  to the profile's region. The code now passes the region to every client.
