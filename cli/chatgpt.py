"""Manage this local installation's ChatGPT subscription authorization."""

import typer

from tradingagents.llm_clients import chatgpt_auth

app = typer.Typer(help="Sign in with ChatGPT to use an eligible Plus/Pro plan.")


@app.command()
def login(
    account: str | None = typer.Option(None, help="Saved client ID from the accounts command"),
    new_account: bool = typer.Option(False, "--new-account", help="Add another ChatGPT account or workspace"),
):
    """Continue with ChatGPT in your browser and authorize plan usage."""
    if account and new_account:
        raise typer.BadParameter("Choose --account or --new-account.")
    try:
        profile = chatgpt_auth.sign_in(account, new_account, notify=typer.echo)
    except chatgpt_auth.ChatGPTAuthError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Connected: {profile['email'] or profile['client_id']}")
    if "chatgpt.tokens.use.direct" not in profile["scopes"]:
        typer.echo("Sign-in succeeded, but ChatGPT plan usage was not granted.")
        raise typer.Exit(code=1)
    typer.echo("You're using your ChatGPT plan. Manage usage: https://chatgpt.com/settings/usage")
    typer.echo("Choose the ChatGPT provider, or set TRADINGAGENTS_LLM_PROVIDER=chatgpt.")


@app.command()
def accounts():
    """List saved registrations; the active one is marked *."""
    try:
        profiles = chatgpt_auth.accounts()
    except chatgpt_auth.ChatGPTAuthError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    for profile in profiles:
        typer.echo(f"{'*' if profile['active'] else ' '} {profile['client_id']}  {profile['email']}")
    if not profiles:
        typer.echo("No saved ChatGPT accounts. Run tradingagents chatgpt login.")


@app.command()
def models():
    """List models available to the active ChatGPT account."""
    try:
        for label, slug in chatgpt_auth.list_models():
            typer.echo(f"{slug}  {label}")
    except chatgpt_auth.ChatGPTAuthError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


@app.command()
def logout():
    """Sign out the active account; retain its registration for the next login."""
    try:
        revoked = chatgpt_auth.sign_out()
    except chatgpt_auth.ChatGPTAuthError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    typer.echo("Signed out locally.")
    if not revoked:
        typer.echo("Remote revocation was not confirmed. Disconnect TradingAgents in ChatGPT settings.")
