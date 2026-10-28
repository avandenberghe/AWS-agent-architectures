"""Agent with a tool.

The model decides on its own whether to call get_order_status. Everything it
knows about that function comes from the type hints and the docstring: the
summary line becomes the tool description, the "Args:" section becomes the
parameter descriptions. Treat them as an API contract, not as comments.
"""

import os

from dotenv import load_dotenv
from strands import Agent, tool
from strands.models import BedrockModel

load_dotenv()


@tool
def get_order_status(order_id: str) -> str:
    """Look up the current delivery status of a customer order.

    Args:
        order_id: Order ID, format ORD-12345
    """
    # A real implementation would call your order system here.
    # Note: the agent may call this more than once. Fine for a read;
    # anything that writes needs an idempotency key.
    return f"{order_id}: shipped, tracking BE998877, arriving 8 August"


def main():
    model = BedrockModel(
        model_id=os.environ["BEDROCK_MODEL"],
        region_name=os.environ["AWS_REGION"],
    )

    agent = Agent(
        model=model,
        name="OrderAgent",
        # Instructions shape behaviour but do not enforce it. Anything that
        # MUST happen every time belongs in ordinary code, not in here.
        system_prompt=(
            "You help customers with order queries. "
            "Always look up the order before answering. Never guess a status. "
            "If the order ID is not in ORD-NNNNN format, ask for a valid one."
        ),
        tools=[get_order_status],
        callback_handler=None,
    )

    result = agent("Hi, where has my order ORD-40021 got to?")
    print(result)


if __name__ == "__main__":
    main()
