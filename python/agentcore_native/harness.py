"""What the three agentcore_native scripts share: the names they create, and how
to find the harness again.

Foundry addresses an agent by name. AgentCore addresses a harness by a
generated ID (name + 10 random characters) or its ARN, so finding "our" harness
means listing and matching on the name.
"""

import boto3
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

# Harness names allow letters, digits and underscores only: no hyphens.
HARNESS_NAME = "lab_assistant_python"

# The IAM role the harness assumes when it runs. Foundry needs nothing like
# this: its agents run under the project's own identity.
ROLE_NAME = "lab-assistant-python-harness"

TAGS = {"project": "aws-agent-architectures"}


def control_client():
    """Control plane: create, update, list and delete harnesses."""
    return boto3.client("bedrock-agentcore-control")


def runtime_client():
    """Data plane: invoke a harness."""
    return boto3.client("bedrock-agentcore")


def find_harness(control) -> dict | None:
    """The harness summary for HARNESS_NAME, or None if it doesn't exist."""
    token = None
    while True:
        page = control.list_harnesses(**({"nextToken": token} if token else {}))
        for h in page["harnesses"]:
            if h["harnessName"] == HARNESS_NAME:
                return h
        token = page.get("nextToken")
        if not token:
            return None
