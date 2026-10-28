"""Publish an agent INTO AgentCore, as a named, versioned harness.

This is the difference the scripts in local_agent/ do not show. Agent() there
builds a Python object that dies with the process. Here the agent definition is
sent to AgentCore and becomes a resource you can see in the console, invoke
from anywhere, and version.

Like a Foundry prompt agent, a harness is declarative: a model reference plus
instructions, and AWS runs the agent loop (Strands, on AgentCore Runtime). Two
things Foundry does not ask for:

1. An IAM role. The harness runs as that role, so it needs permission to call
   the model. This script creates the role, scoped to the one model in .env.
2. Explicit limits. A harness gets a shell, a filesystem and a microVM per
   session by default. This one is told to use no tools, to stop after 10 loop
   iterations, and to shut an idle session down after 5 minutes.

Re-running creates a NEW version rather than overwriting, which is what makes
rollback possible. Run this once, then look at the AgentCore console.
"""

import json
import os
import time

import boto3
from botocore.exceptions import ClientError

from harness import HARNESS_NAME, REGION, ROLE_NAME, TAGS, control_client, find_harness

INSTRUCTIONS = (
    "You are a concise assistant for an AWS AgentCore lab. "
    "Answer in at most three sentences. "
    "If you are unsure, say so rather than guessing."
)


def ensure_role(account: str, region: str, model: str) -> str:
    """Create the harness execution role if needed; (re)apply its policy either way."""
    iam = boto3.client("iam")

    # Who may assume the role: only AgentCore, and only on behalf of this account.
    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"aws:SourceAccount": account}},
        }],
    }

    # What the role may do. AWS's sample grants every model in every region;
    # this grants the one inference profile, plus the base model behind it in
    # whichever EU region the profile routes the request to.
    base_model = model.split(".", 1)[1]
    log_group = f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*"
    permissions = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "InvokeTheOneModel",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                "Resource": [
                    f"arn:aws:bedrock:{region}:{account}:inference-profile/{model}",
                    f"arn:aws:bedrock:*::foundation-model/{base_model}",
                ],
            },
            {
                # The harness's own container image comes from ECR Public.
                "Sid": "PullManagedImage",
                "Effect": "Allow",
                "Action": ["ecr-public:GetAuthorizationToken", "sts:GetServiceBearerToken"],
                "Resource": "*",
            },
            {
                "Sid": "Logs",
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:DescribeLogStreams",
                           "logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [log_group, f"{log_group}:log-stream:*"],
            },
            {
                "Sid": "Traces",
                "Effect": "Allow",
                "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords",
                           "xray:GetSamplingRules", "xray:GetSamplingTargets"],
                "Resource": "*",
            },
            {
                "Sid": "Metrics",
                "Effect": "Allow",
                "Action": "cloudwatch:PutMetricData",
                "Resource": "*",
                "Condition": {"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}},
            },
            {
                "Sid": "WorkloadIdentity",
                "Effect": "Allow",
                "Action": ["bedrock-agentcore:GetWorkloadAccessToken",
                           "bedrock-agentcore:GetWorkloadAccessTokenForJWT"],
                "Resource": [
                    f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default/workload-identity/harness_{HARNESS_NAME}-*",
                ],
            },
        ],
    }

    try:
        arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        arn = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description=f"Execution role for the {HARNESS_NAME} AgentCore harness",
            Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()],
        )["Role"]["Arn"]
        print(f"created role {ROLE_NAME}")
    iam.put_role_policy(RoleName=ROLE_NAME, PolicyName="harness", PolicyDocument=json.dumps(permissions))
    return arn


def wait_until_settled(control, harness_id: str) -> dict:
    """Creating and updating are asynchronous. Poll until the harness is READY."""
    while True:
        h = control.get_harness(harnessId=harness_id)["harness"]
        if h["status"] not in ("CREATING", "UPDATING"):
            return h
        time.sleep(5)


def main():
    region = REGION
    model = os.environ["BEDROCK_MODEL"]
    account = boto3.client("sts").get_caller_identity()["Account"]
    control = control_client()

    # Step 1: the identity the harness will run as.
    role_arn = ensure_role(account, region, model)

    # Step 2: describe the agent. This is the whole definition AgentCore stores.
    definition = {
        "executionRoleArn": role_arn,
        "model": {"bedrockModelConfig": {"modelId": model, "maxTokens": 512}},
        "systemPrompt": [{"text": INSTRUCTIONS}],
        # No tools, not even the built-in shell and file tools. Without this
        # line the model gets both, plus ~900 tokens of tool definitions per call.
        "allowedTools": [],
        # Cost and safety caps. The defaults are 75 iterations and one hour.
        "maxIterations": 10,
        "timeoutSeconds": 120,
        "environment": {"agentCoreRuntimeEnvironment": {"lifecycleConfiguration": {
            "idleRuntimeSessionTimeout": 300,   # default 900
            "maxLifetime": 3600,                # default 28800
        }}},
    }

    # Step 3: the actual write. Create the harness (version 1), or update it,
    # which creates the next version. Versions are immutable.
    existing = find_harness(control)
    for attempt in range(12):
        try:
            if existing is None:
                h = control.create_harness(
                    harnessName=HARNESS_NAME,
                    tags=TAGS,
                    # Without a memory setting, the API provisions managed
                    # AgentCore Memory, which is billed per event. The session
                    # itself already keeps the conversation; see run_agent.py.
                    memory={"disabled": {}},
                    **definition,
                )["harness"]
            else:
                h = control.update_harness(
                    harnessId=existing["harnessId"],
                    memory={"optionalValue": {"disabled": {}}},
                    **definition,
                )["harness"]
            break
        except ClientError as exc:
            # A brand-new IAM role takes a few seconds to become assumable.
            if existing is None and attempt < 11 and "role" in str(exc).lower():
                time.sleep(5)
                continue
            raise

    h = wait_until_settled(control, h["harnessId"])
    if h["status"] != "READY":
        raise SystemExit(f"harness is {h['status']}: {h.get('failureReason', 'no reason given')}")

    print(f"published: {HARNESS_NAME}")
    print(f"id:        {h['harnessId']}")
    print(f"version:   {h['harnessVersion']}")
    print()
    print("Now open the AgentCore console -> Harnesses. It is there.")
    print("Then: python run_agent.py")


if __name__ == "__main__":
    main()
