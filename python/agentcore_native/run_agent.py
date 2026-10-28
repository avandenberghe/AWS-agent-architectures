"""Connect to the published harness and hold a two-turn conversation.

Two things here that the local_agent/ scripts cannot do:

1. The agent is not defined in this file. It is referenced by name and
   endpoint. The instructions live in AgentCore: change them, re-run this, and
   the behaviour changes without touching code.

2. The conversation has a session. Turn two knows what turn one said, and that
   memory is held by the service, not by a variable in this process.

Versions are chosen through endpoints, not per call as in Foundry. DEFAULT
always points at the latest version; to pin an older one, create a named
endpoint for it (see the README) and pass its name here.

Usage:  python run_agent.py [endpoint]      default: DEFAULT
"""

import sys
import uuid

from harness import HARNESS_NAME, control_client, find_harness, runtime_client


def ask(runtime, harness_arn: str, endpoint: str, session_id: str, text: str) -> str:
    """Send one user message and collect the streamed answer."""
    response = runtime.invoke_harness(
        harnessArn=harness_arn,
        qualifier=endpoint,
        runtimeSessionId=session_id,
        messages=[{"role": "user", "content": [{"text": text}]}],
    )
    # InvokeHarness streams events: message starts and stops, content deltas,
    # token usage. For a harness without tools, the text deltas are the answer.
    parts = []
    for event in response["stream"]:
        if "contentBlockDelta" in event:
            parts.append(event["contentBlockDelta"].get("delta", {}).get("text", ""))
        elif "runtimeClientError" in event:
            raise SystemExit(f"harness error: {event['runtimeClientError']['message']}")
    return "".join(parts).strip()


def main():
    endpoint = sys.argv[1] if len(sys.argv) > 1 else "DEFAULT"

    control = control_client()
    summary = find_harness(control)
    if summary is None:
        raise SystemExit(f"{HARNESS_NAME} does not exist. Run publish_agent.py first.")

    # No instructions, no model, no tools defined here: only a reference.
    # Everything that shapes behaviour lives in AgentCore.
    if endpoint == "DEFAULT":
        version = summary["harnessVersion"]
    else:
        version = control.get_harness_endpoint(
            harnessId=summary["harnessId"], endpointName=endpoint
        )["liveVersion"]
    print(f"{HARNESS_NAME}, endpoint {endpoint} -> version {version}")
    print()

    # The session is just an ID you make up (at least 33 characters). The first
    # call with a new ID starts a microVM for it; later calls with the same ID
    # land in the same one, until it has been idle for 5 minutes.
    session_id = str(uuid.uuid4())
    runtime = runtime_client()

    first = ask(runtime, summary["arn"], endpoint, session_id,
                "I am setting up a lab in the eu-north-1 region. Note that.")
    print("turn 1:", first)
    print()

    # The proof. This question is unanswerable without the previous turn, and
    # nothing in this file is holding that history.
    second = ask(runtime, summary["arn"], endpoint, session_id,
                 "Which region did I just say I was using?")
    print("turn 2:", second)


if __name__ == "__main__":
    main()
