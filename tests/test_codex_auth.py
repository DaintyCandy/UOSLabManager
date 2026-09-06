from types import SimpleNamespace

from gui.plugin_studio.codex_panel import CodexAuthWorker


def response_with(account):
    wrapped = None if account is None else SimpleNamespace(root=account)
    return SimpleNamespace(account=wrapped)


def test_missing_codex_account_is_reported_as_signed_out():
    info = CodexAuthWorker.account_info(response_with(None))

    assert info == {
        "authenticated": False,
        "method": None,
        "label": "Not signed in",
    }


def test_chatgpt_account_description_includes_identity_and_plan():
    account = SimpleNamespace(
        type="chatgpt",
        email="scientist@example.com",
        plan_type=SimpleNamespace(value="pro"),
    )

    info = CodexAuthWorker.account_info(response_with(account))

    assert info["authenticated"] is True
    assert info["method"] == "chatgpt"
    assert info["label"] == "ChatGPT / scientist@example.com / pro"


def test_api_key_account_description_never_contains_the_key():
    account = SimpleNamespace(type="apiKey")

    info = CodexAuthWorker.account_info(response_with(account))

    assert info == {
        "authenticated": True,
        "method": "apiKey",
        "label": "API key",
    }
