"""VI CLI — extends base ARS CLI with credential and constraint commands."""

from __future__ import annotations

import json

import click

from ars_client._signing import load_signing_key
from ars_client._transport import ARSClientError
from ars_client.cli import cli, _print_json, _handle_error, _get_key

from .agent import VIAgentClient
from .credential_provider import VICredentialProviderClient
from .payment_network import VIPaymentNetworkClient
from .user import VIUserClient


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.option("--l1-file", required=True, type=click.Path(exists=True))
@click.pass_context
def issue_l1(ctx, job_id, agreement_hash, l1_file):
    """Issue an L1 credential from a serialized SD-JWT file."""
    sk = _get_key(ctx)
    with open(l1_file) as f:
        l1_serialized = f.read().strip()
    client = VICredentialProviderClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.issue_l1(job_id, agreement_hash, l1_serialized)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.option("--mode", required=True, type=click.Choice(["immediate", "autonomous"]))
@click.option("--l2-file", required=True, type=click.Path(exists=True))
@click.option("--constraints-file", type=click.Path(exists=True))
@click.pass_context
def create_l2(ctx, job_id, agreement_hash, mode, l2_file, constraints_file):
    """Create an L2 mandate from a serialized SD-JWT file."""
    sk = _get_key(ctx)
    with open(l2_file) as f:
        l2_serialized = f.read().strip()
    constraints = None
    if constraints_file:
        with open(constraints_file) as f:
            constraints = json.load(f)
    client = VIUserClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.create_l2_mandate(
            job_id, agreement_hash, mode, l2_serialized, constraints
        )
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.pass_context
def verify_l2(ctx, job_id, agreement_hash):
    """Verify L1→L2 chain."""
    sk = _get_key(ctx)
    client = VICredentialProviderClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.verify_l2(job_id, agreement_hash)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.pass_context
def verify_chain(ctx, job_id, agreement_hash):
    """Verify full L1→L2→L3 chain."""
    sk = _get_key(ctx)
    client = VICredentialProviderClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.verify_chain(job_id, agreement_hash)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.pass_context
def get_credentials(ctx, job_id):
    """Get credential track state."""
    sk = _get_key(ctx)
    client = VIAgentClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        data = client.get_credentials(job_id)
        _print_json(data)
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.pass_context
def check_constraints(ctx, job_id):
    """Check L2 constraints against L3 fulfillment."""
    sk = _get_key(ctx)
    client = VIAgentClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        data = client.check_constraints(job_id)
        _print_json(data)
    except ARSClientError as e:
        _handle_error(e)


def main():
    cli()


if __name__ == "__main__":
    main()
