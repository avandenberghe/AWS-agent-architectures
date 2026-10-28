"""List and delete the published harness, and the IAM role it runs as.

Publishing creates resources that outlive the process — which is the point,
and also the reason this script exists. Anything you create, you should be able
to remove in one command. On AWS that is two resources, not one: the harness
and its execution role.

Usage:
    python cleanup.py           # list harnesses, versions and endpoints; delete nothing
    python cleanup.py --delete  # delete the harness (all versions) and the role
"""

import sys

import boto3

from harness import HARNESS_NAME, REGION, ROLE_NAME, control_client, find_harness


def main():
    control = control_client()

    print(f"harnesses in {REGION}:")
    for h in control.list_harnesses()["harnesses"]:
        print(f"  {h['harnessName']}  ({h['status']}, latest version {h['harnessVersion']})")

    summary = find_harness(control)
    if summary is not None:
        harness_id = summary["harnessId"]
        print(f"\nversions of {HARNESS_NAME}:")
        for v in control.list_harness_versions(harnessId=harness_id)["harnessVersions"]:
            print(f"  version {v['harnessVersion']}  {v['status']}  {v['createdAt']:%Y-%m-%d %H:%M}")
        print(f"\nendpoints of {HARNESS_NAME}:")
        for e in control.list_harness_endpoints(harnessId=harness_id)["endpoints"]:
            print(f"  {e['endpointName']} -> version {e.get('liveVersion', '?')}")

    if "--delete" not in sys.argv:
        print("\nnothing deleted. pass --delete to remove the harness and its role.")
        return

    if summary is None:
        print(f"\nno harness named {HARNESS_NAME}.")
    else:
        # Deletes every version and endpoint with it.
        control.delete_harness(harnessId=summary["harnessId"])
        print(f"\ndeleted: {HARNESS_NAME}")

    # An IAM role can't be deleted while it still has inline policies.
    iam = boto3.client("iam")
    try:
        for name in iam.list_role_policies(RoleName=ROLE_NAME)["PolicyNames"]:
            iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName=name)
        iam.delete_role(RoleName=ROLE_NAME)
        print(f"deleted: role {ROLE_NAME}")
    except iam.exceptions.NoSuchEntityException:
        print(f"no role named {ROLE_NAME}.")


if __name__ == "__main__":
    main()
