"""Agent with two real tools, where the second call depends on the first.

order_agent.py answers one question with one lookup. That is a tool call, not
an agent loop. Here the goal is open-ended enough that the model has to decide
what to check, in what order, and what the combination means:

    "Can I use Claude Opus 5.5?"

It cannot answer that in one call. Bedrock keeps availability and entitlement
apart: the inference profiles say what exists in this region, the model's
availability and quotas say whether this account may actually call it. A model
can be listed and still be unusable, for example when the provider's terms
were never accepted.

The first version gave the model the raw list of profiles and an instruction to
check each alternative before recommending it. It didn't: it recommended models
it had never checked, which were not usable either. So the check moved into
code. list_usable_models() checks every model itself and returns only the ones
this account can call; the model can no longer recommend anything else, whatever
it decides. Instructions are advice; code is enforcement.

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


def _base_id(model_id: str) -> str:
    """The availability APIs want the base model ID, not a profile ID: strip
    the routing prefix from "eu.anthropic.claude-...", if there is one."""
    prefix, _, rest = model_id.partition(".")
    return rest if prefix in ("eu", "us", "apac", "global") else model_id


@lru_cache(maxsize=None)
def _access(base_id: str) -> dict:
    """Availability flags and per-minute quotas for one model. Raises on API errors."""
    details = _bedrock.get_foundation_model(modelIdentifier=base_id)["modelDetails"]
    availability = _bedrock.get_foundation_model_availability(modelId=base_id)
    availability.pop("ResponseMetadata", None)
    name = details["modelName"]
    quotas = {
        quota: value
        for quota, value in _bedrock_quotas()
        if name in quota and "inference" in quota and "per minute" in quota
    }
    return {"model": name, "outputs": details.get("outputModalities", []),
            "availability": availability, "quotas": quotas}


def _usable(access: dict) -> bool:
    """The rule, in code: terms accepted, authorised, entitled, and a non-zero
    EU cross-region token quota. Anything else cannot be called today."""
    a = access["availability"]
    eu_tokens = [v for q, v in access["quotas"].items()
                 if q.startswith("Cross-region") and "tokens per minute" in q]
    return (a.get("agreementAvailability", {}).get("status") == "AVAILABLE"
            and a.get("authorizationStatus") == "AUTHORIZED"
            and a.get("entitlementAvailability") == "AVAILABLE"
            and any(v for v in eu_tokens))


@tool
def list_usable_models() -> str:
    """List the text models this account can call right now from this region,
    each with the EU inference profile ID used to call it. Every model returned
    has been checked: terms accepted, entitled, and quota above zero. Models
    that are listed by Bedrock but not usable are left out."""
    try:
        pages = _bedrock.get_paginator("list_inference_profiles").paginate()
        profiles = [p for page in pages for p in page["inferenceProfileSummaries"]
                    if p["inferenceProfileId"].startswith("eu.")]   # EU routing only
        usable = []
        for p in profiles:
            access = _access(_base_id(p["inferenceProfileId"]))
            if "TEXT" in access["outputs"] and _usable(access):
                usable.append({"profile": p["inferenceProfileId"], "model": access["model"]})
    except (BotoCoreError, ClientError) as exc:
        return _fail(exc)
    return json.dumps(usable)


@tool
def check_model_access(model_id: str) -> str:
    """Check whether this account may call one model, and why not if it can't.
    Returns usable (true/false), the availability flags and the throughput
    quotas. agreementAvailability NOT_AVAILABLE means the provider's terms have
    not been accepted for this account, which is different from the model being
    absent.

    Args:
        model_id: Model or profile ID, e.g. anthropic.claude-opus-5-5
    """
    try:
        access = _access(_base_id(model_id))
    except (BotoCoreError, ClientError) as exc:
        return _fail(exc)
    return json.dumps({"usable": _usable(access), **access})


def main():
    model = BedrockModel(model_id=MODEL, region_name=REGION)

    agent = Agent(
        model=model,
        name="OpsAgent",
        system_prompt=(
            "You help with Amazon Bedrock model access. "
            "Check the facts with your tools before answering; never guess "
            "whether a model is usable. Only recommend models returned by "
            "list_usable_models: those are the only ones this account can call."
        ),
        tools=[check_model_access, list_usable_models],
        callback_handler=None,
    )

    result = agent(
        "I want to use Claude Opus 5.5 in this account. Can I? "
        "If not, tell me what I can already use instead."
    )
    print(result)


if __name__ == "__main__":
    main()
