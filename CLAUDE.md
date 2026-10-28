# AWS agent lab

Learning lab: the Azure Foundry agent lab (github avandenberghe/agent-architectures,
local copy ../Azure-agent-architectures) rebuilt on Amazon Bedrock + AgentCore.
A spike, not a product: build directly, keep it small, comment for a reader
who is learning.

## Layout
- `python/local_agent/`: Strands agents in-process (hello, order, ops).
- `python/agentcore_native/`: publish / run / cleanup of an AgentCore harness
  (`lab_assistant_python`) and its IAM role (`lab-assistant-python-harness`).
- Root `.env` (untracked): AWS_PROFILE, AWS_REGION=eu-north-1, BEDROCK_MODEL.

## Rules
- Never commit `.env` or anything with credentials. Credentials live in ~/.aws
  via `aws login`; don't read or print them.
- Ask before anything that writes to the AWS account (publish_agent.py,
  cleanup.py --delete, any create/update/delete call) and before commit/push.
- Read-only AWS calls (list/get/describe, pricing) are fine.
- Stay in EU regions; use `eu.` inference profiles.
- Pin dependencies: `requirements.txt` direct, `constraints.txt` from
  `pip freeze`. boto3 needs the `[crt]` extra for `aws login` credentials.
- Bedrock Agents (Classic) is closed to this account; use AgentCore.
