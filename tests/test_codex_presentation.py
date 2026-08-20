from pathlib import Path

from gui.plugin_studio.codex_presentation import should_display_codex_log


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_command_and_proposed_changes_are_hidden_from_codex_log():
    assert not should_display_codex_log("COMMAND")
    assert not should_display_codex_log("PROPOSED CHANGES")
    assert not should_display_codex_log("  command  ")


def test_other_codex_activity_remains_visible():
    assert should_display_codex_log("CODEX")
    assert should_display_codex_log("VALIDATION")
    assert should_display_codex_log("FILE")


def test_generated_ui_contract_leaves_backgrounds_to_the_host():
    codex_source = (PROJECT_ROOT / "gui/plugin_studio/codex_panel.py").read_text(
        encoding="utf-8"
    )
    device_panel_source = (PROJECT_ROOT / "gui/panel_device.py").read_text(
        encoding="utf-8"
    )

    assert "Do not set `background` or `background-color`" in codex_source
    assert "never generate separate dark/light variants" in codex_source
    assert "background:#000" not in device_panel_source
