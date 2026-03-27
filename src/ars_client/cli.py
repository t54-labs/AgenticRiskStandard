"""ARS CLI — command-line interface for base ARS protocol interactions."""

from __future__ import annotations

import json
import sys

import click
from nacl.signing import SigningKey

from ._signing import load_signing_key, pubkey_hex
from ._transport import ARSClientError
from .business_agent import BusinessAgentClient
from .evaluator import EvaluatorClient
from .requestor import RequestorClient
from .underwriter import UnderwriterClient


def _print_json(data):
    click.echo(json.dumps(data, indent=2, default=str))


def _handle_error(e: ARSClientError):
    click.echo(f"Error {e.status_code}: {e.detail}", err=True)
    sys.exit(1)


def _get_key(ctx) -> SigningKey:
    return load_signing_key(
        key_hex=ctx.obj.get("key_hex"), key_file=ctx.obj.get("key_file"),
    )


@click.group()
@click.option("--server", envvar="ARS_SERVER_URL", default="http://localhost:8000")
@click.option("--key-hex", envvar="ARS_SIGNING_KEY", default=None)
@click.option("--key-file", default=None, type=click.Path(exists=True))
@click.pass_context
def cli(ctx, server, key_hex, key_file):
    """ARS protocol CLI."""
    ctx.ensure_object(dict)
    ctx.obj["server"] = server
    ctx.obj["key_hex"] = key_hex
    ctx.obj["key_file"] = key_file


@cli.command()
def generate_keypair():
    """Generate a new Ed25519 keypair."""
    sk = SigningKey.generate()
    click.echo(f"SIGNING_KEY={sk.encode().hex()}")
    click.echo(f"PUBLIC_KEY={pubkey_hex(sk)}")


@cli.command()
@click.option("--agreement-file", required=True, type=click.Path(exists=True))
@click.pass_context
def create_job(ctx, agreement_file):
    """Create a new job from an agreement JSON file."""
    sk = _get_key(ctx)
    with open(agreement_file) as f:
        agreement = json.load(f)
    client = RequestorClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.create_job(agreement)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.pass_context
def sign_agreement(ctx, job_id, agreement_hash):
    """Sign an agreement (works for any signing role)."""
    sk = _get_key(ctx)
    client = RequestorClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.sign_agreement(job_id, agreement_hash)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.pass_context
def lock_fee(ctx, job_id, agreement_hash):
    """Lock fee in escrow."""
    sk = _get_key(ctx)
    client = RequestorClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.lock_fee(job_id, agreement_hash)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.option("--action", type=click.Choice(["release", "refund"]), required=True)
@click.pass_context
def settle_fee(ctx, job_id, agreement_hash, action):
    """Settle fee — release or refund."""
    sk = _get_key(ctx)
    client = RequestorClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.settle_fee(job_id, agreement_hash, action)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.option("--deliverable-ref", required=True)
@click.pass_context
def submit_deliverable(ctx, job_id, agreement_hash, deliverable_ref):
    """Submit a deliverable."""
    sk = _get_key(ctx)
    client = BusinessAgentClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.submit_deliverable(job_id, agreement_hash, deliverable_ref)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.option("--verdict", type=click.Choice(["pass", "fail"]), required=True)
@click.pass_context
def evaluate(ctx, job_id, agreement_hash, verdict):
    """Evaluate outcome — pass or fail."""
    sk = _get_key(ctx)
    client = EvaluatorClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.evaluate(job_id, agreement_hash, verdict)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.option("--agreement-hash", required=True)
@click.option("--approve/--reject", required=True)
@click.option("--premium", default=0, type=int)
@click.option("--collateral", default=0, type=int)
@click.pass_context
def uw_decide(ctx, job_id, agreement_hash, approve, premium, collateral):
    """Submit underwriting decision."""
    sk = _get_key(ctx)
    client = UnderwriterClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        resp = client.uw_decide(job_id, agreement_hash, approve, premium, collateral)
        _print_json(resp.model_dump())
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.pass_context
def get_job(ctx, job_id):
    """Get current job state."""
    sk = _get_key(ctx)
    client = RequestorClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        data = client.get_job(job_id)
        _print_json(data)
    except ARSClientError as e:
        _handle_error(e)


@cli.command()
@click.option("--job-id", required=True)
@click.pass_context
def get_events(ctx, job_id):
    """Get job event history."""
    sk = _get_key(ctx)
    client = RequestorClient(base_url=ctx.obj["server"], signing_key=sk)
    try:
        data = client.get_events(job_id)
        _print_json(data)
    except ARSClientError as e:
        _handle_error(e)


def main():
    cli()


if __name__ == "__main__":
    main()
