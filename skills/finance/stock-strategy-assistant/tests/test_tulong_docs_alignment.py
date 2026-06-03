from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_architecture_boundary_is_single_sourced_in_operations():
    skill = read_text("SKILL.md")
    operations = read_text("references/tulong-operations.md")
    readme = read_text("scripts/tulong/README.md")

    assert "架构职责边界" in operations
    assert "`references/` 保存当前规则和运行手册" in operations
    assert "`src/stock_assistant/strategy_tulong.py` 保存可复用规则函数" in operations
    assert "`scripts/tulong/selection/` 负责选股" in operations
    assert "`scripts/tulong/runtime/` 负责 cron 调用" in operations
    assert "不应成为长期规则事实源" in operations

    assert "架构职责边界或 runtime/selection/src/reference 分工" in skill
    assert "references/tulong-operations.md" in skill

    assert "## 职责分工" not in readme
    assert "src/stock_assistant" not in readme
    assert "不应成为长期规则事实源" not in readme


def test_rule_change_sync_protocol_is_documented():
    skill = read_text("SKILL.md")
    rules = read_text("references/tulong-current-rules.md")

    assert "规则变更同步协议" in rules
    assert "不能只改规则文档" in rules
    assert "src/stock_assistant/strategy_tulong.py" in rules
    assert "scripts/tulong/selection/" in rules
    assert "scripts/tulong/runtime/" in rules
    assert "references/tulong-operations.md" in rules
    assert "tests/" in rules
    assert "已评估，无需改动" in rules

    assert "规则变更同步协议" in skill
    assert "src/stock_assistant/" in skill
    assert "scripts/tulong/selection/" in skill
    assert "scripts/tulong/runtime/" in skill


def test_manual_narrowing_and_ticket_add_are_not_current_flow():
    current_files = [
        "SKILL.md",
        "references/tulong-current-rules.md",
        "references/tulong-operations.md",
        "scripts/tulong/README.md",
        "scripts/tulong/selection/generate_d3_candidates.py",
    ]
    forbidden = [
        "人工补票",
        "人工修正",
        "人工复核",
        "manual_add",
        "manual_review",
    ]

    for rel_path in current_files:
        text = read_text(rel_path)
        for term in forbidden:
            assert term not in text, f"{term} should not appear in {rel_path}"

    rules = read_text("references/tulong-current-rules.md")
    assert "规则输入修订" in rules
    assert "重新运行自动规则生成观察池" in rules


def test_documented_architecture_paths_exist():
    for rel_path in [
        "references/tulong-operations.md",
        "references/tulong-current-rules.md",
        "src/stock_assistant/strategy_tulong.py",
        "scripts/tulong/README.md",
        "scripts/tulong/selection/generate_d3_candidates.py",
        "scripts/tulong/runtime/watchdog.py",
        "scripts/tulong/runtime/review.py",
        "scripts/tulong/runtime/preopen_rotate_watchlist.py",
        "scripts/tulong/runtime/preopen_guard_check.py",
    ]:
        assert (ROOT / rel_path).exists(), rel_path


def test_selection_entry_uses_reusable_strategy_module():
    selection = read_text("scripts/tulong/selection/generate_d3_candidates.py")

    assert "from stock_assistant.strategy_tulong import" in selection
