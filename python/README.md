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

## Setup

Requires Python 3.10+ (the lab uses 3.13), the AWS CLI v2, and the filled-in
`.env` at the repo root. From the repo root:

```bash
python3 -m venv python/.venv && source python/.venv/bin/activate
pip install -r python/requirements.txt

aws login --profile "$AWS_PROFILE"
```

`load_dotenv()` walks up from each **script's folder** to find the root `.env`,
so the scripts work from any working directory. boto3 picks up `AWS_PROFILE`
from the environment, but not `AWS_REGION`: the code passes the region to
every client explicitly, or it would silently use the profile's region.

## Run

```bash
python python/local_agent/hello_agent.py
python python/local_agent/order_agent.py
python python/local_agent/ops_agent.py

python python/agentcore_native/publish_agent.py   # writes to the account: role + harness, a new version each run
python python/agentcore_native/run_agent.py       # endpoint to use, default DEFAULT (= latest version)
python python/agentcore_native/cleanup.py         # list only; --delete removes the harness and the role
```

The Ops tools are plain functions, so you can exercise them without spending tokens:

```bash
cd python/local_agent && ../.venv/bin/python -c "import ops_agent; print(ops_agent.check_model_access('anthropic.claude-opus-5-5'))"
```

To pin a version, create a named endpoint and pass its name to `run_agent.py`:

```bash
aws bedrock-agentcore-control create-harness-endpoint \
  --harness-id <id from publish_agent.py> --endpoint-name stable --target-version 1
python python/agentcore_native/run_agent.py stable
```

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
