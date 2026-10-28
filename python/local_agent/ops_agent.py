"""Agent with two real tools, where the second call depends on the first.

order_agent.py answers one question with one lookup. That is a tool call, not
an agent loop. Here the goal is open-ended enough that the model has to decide
what to check, in what order, and what the combination means:

    "Can I use Claude Opus 5.5?"

It cannot answer that in one call. Bedrock keeps availability and entitlement
apart: the inference profiles say what exists in this region, the model's
availability and quotas say whether this account may actually call it. A model
can be listed and still be unusable, for example when the provider's terms
were never accepted. The model has to consult both and reconcile them.

Both tools are read-only boto3 calls. Nothing here creates or deletes anything.
"""

import json
import os
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from strands import Agent, tool
from strands.models import BedrockModel

load_dotenv()


def _required(name: str) -> str:
    """Read a setting from .env, failing with a useful message rather than a KeyError."""
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"{name} is not set. Copy .env.example to .env and fill it in, "
            f"then run this from anywhere inside the repo."
        )
    return value


REGION = _required("AWS_REGION")
MODEL = _required("BEDROCK_MODEL")

# boto3 picks up AWS_PROFILE from the environment. The Azure lab shells out to
# `az` here; on AWS the SDK is the natural route, and it removes the PATH
# problem a GUI-launched IDE has with CLI tools.
_session = boto3.Session(region_name=REGION)
_bedrock = _session.client("bedrock")
_quotas = _session.client("service-quotas")


def _fail(exc: Exception) -> str:
    """Errors come back as text rather than raising. A raised exception ends the
    run; a returned string lets the model read the failure and decide what to
    do about it, which is the behaviour you want from a tool."""
    return f"ERROR: {exc}"


@lru_cache(maxsize=1)
def _bedrock_quotas() -> tuple[tuple[str, float | None], ...]:
    """All Bedrock quotas in this region. Several hundred, so fetch them once.
    A few have no Value at all, hence .get()."""
    pages = _quotas.get_paginator("list_service_quotas").paginate(ServiceCode="bedrock")
    return tuple((q["QuotaName"], q.get("Value")) for page in pages for q in page["Quotas"])


@tool
def list_inference_profiles() -> str:
    """List the inference profiles available in this region: the models this
    account can address here, each with the profile ID used to call it."""
    try:
        pages = _bedrock.get_paginator("list_inference_profiles").paginate()
        profiles = [
            {"profile": p["inferenceProfileId"], "name": p["inferenceProfileName"], "status": p["status"]}
            for page in pages
            for p in page["inferenceProfileSummaries"]
        ]
    except (BotoCoreError, ClientError) as exc:
        return _fail(exc)
    return json.dumps(profiles)


@tool
def check_model_access(model_id: str) -> str:
    """Check whether this account may call a model, and how much. Returns the
    availability flags and the cross-region throughput quotas.
    agreementAvailability NOT_AVAILABLE means the provider's terms have not been
    accepted for this account, which is different from the model being absent.

    Args:
        model_id: Base model ID without a region prefix, e.g. anthropic.claude-opus-5-5
    """
    # The model may pass a profile ID ("eu.anthropic..."); the availability API
    # wants the base model ID.
    base_id = model_id.split(".", 1)[1] if model_id.split(".", 1)[0] in ("eu", "us", "apac", "global") else model_id
    try:
        availability = _bedrock.get_foundation_model_availability(modelId=base_id)
        name = _bedrock.get_foundation_model(modelIdentifier=base_id)["modelDetails"]["modelName"]
        quotas = {
            quota: value
            for quota, value in _bedrock_quotas()
            if name in quota and "inference" in quota and "per minute" in quota
        }
    except (BotoCoreError, ClientError) as exc:
        return _fail(exc)
    availability.pop("ResponseMetadata", None)
    return json.dumps({"model": name, "availability": availability, "quotas": quotas})


def main():
    model = BedrockModel(model_id=MODEL, region_name=REGION)

    agent = Agent(
        model=model,
        name="OpsAgent",
        system_prompt=(
            "You help with Amazon Bedrock model access. "
            "Check the facts with your tools before answering; never guess "
            "whether a model is usable. A model that is listed but has "
            "agreementAvailability NOT_AVAILABLE cannot be called yet, which is "
            "different from the model being absent. Only recommend an "
            "alternative after checking it with check_model_access too."
        ),
        tools=[list_inference_profiles, check_model_access],
        callback_handler=None,
    )

    result = agent(
        "I want to use Claude Opus 5.5 in this account. Can I? "
        "If not, tell me what I can already use instead."
    )
    print(result)


if __name__ == "__main__":
    main()
