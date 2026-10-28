"""Minimal Strands agent on Bedrock: verifies the whole chain works end to end."""

import os

from dotenv import load_dotenv
from strands import Agent
from strands.models import BedrockModel

load_dotenv()  # not automatic, must be called. It also sets AWS_PROFILE, which boto3 reads.


def main():
    # The model object is your connection to Bedrock. Unlike Foundry there is no
    # project endpoint: the account comes from your credentials.
    model = BedrockModel(
        model_id=os.environ["BEDROCK_MODEL"],   # which model (an inference profile)
        region_name=os.environ["AWS_REGION"],   # where
    )                                           # who you are: AWS_PROFILE, via boto3

    # The agent wraps the model with a standing brief. callback_handler=None
    # because Strands streams the answer to stdout by default; here we print
    # the finished result instead, like the Azure lab does.
    agent = Agent(
        model=model,
        name="HelloAgent",
        system_prompt="You are a concise, friendly assistant.",
        callback_handler=None,
    )

    # Synchronous: no asyncio needed. invoke_async() exists if you want it.
    result = agent("What is the largest city in Belgium?")
    print(result)


if __name__ == "__main__":
    main()
