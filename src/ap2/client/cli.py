"""AP2 CLI — extends base ARS CLI with mandate and constraint commands."""

from __future__ import annotations

import json
import sys

import click

from abstract_ars_client._signing import load_signing_key
from abstract_ars_client._transport import ARSClientError
from abstract_ars_client.cli import cli, _print_json, _handle_error, _get_key

from .merchant import MerchantClient
from .shopping_agent import ShoppingAgentClient
from .user import UserClient


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.option("--budget", required=True, type=int)
@click.option("--merchant-pubkey", required=True, multiple=True)
@click.option("--description", default="")
@click.option("--ttl", default=3600, type=int)
@click.option("--requires-principal", is_flag=True, default=False)
@click.pass_context
def create_intent(
    ctx,
    job_id,
    agreement_hash,
    budget,
    merchant_pubkey,
    description,
    ttl,
    requires_principal,
):
    """Create an IntentMandate."""
    sk = _get_key(ctx)
    client = UserClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.create_intent_mandate(
            job_id,
            agreement_hash,
            budget=budget,
            allowed_merchants=list(merchant_pubkey),
            description=description,
            ttl_seconds=ttl,
            requires_principal=requires_principal,
        )
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.option("--items-file", required=True, type=click.Path(exists=True))
@click.option("--total", required=True, type=int)
@click.pass_context
def propose_cart(ctx, job_id, agreement_hash, items_file, total):
    """Propose a CartMandate from a line items JSON file."""
    sk = _get_key(ctx)
    with open(items_file) as f:
        line_items = json.load(f)
    client = MerchantClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.propose_cart(job_id, agreement_hash, line_items, total)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.pass_context
def sign_cart(ctx, job_id, agreement_hash):
    """Sign the cart mandate."""
    sk = _get_key(ctx)
    client = MerchantClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.sign_cart(job_id, agreement_hash)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.pass_context
def approve_cart(ctx, job_id, agreement_hash):
    """Approve cart (human-present mode)."""
    sk = _get_key(ctx)
    client = UserClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.approve_cart(job_id, agreement_hash)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.pass_context
def sign_payment(ctx, job_id, agreement_hash):
    """Sign the payment mandate."""
    sk = _get_key(ctx)
    client = UserClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.sign_payment(job_id, agreement_hash)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.pass_context
def get_mandates(ctx, job_id):
    """Get mandate track state."""
    sk = _get_key(ctx)
    client = ShoppingAgentClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        data = client.get_mandates(job_id)
        _print_json(data)
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.pass_context
def check_constraints(ctx, job_id):
    """Check intent constraints against cart."""
    sk = _get_key(ctx)
    client = ShoppingAgentClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        data = client.check_constraints(job_id)
        _print_json(data)
    except ARSClientError as e:
        _handle_error(e)


def main():
    cli()


if __name__ == "__main__":
    main()
