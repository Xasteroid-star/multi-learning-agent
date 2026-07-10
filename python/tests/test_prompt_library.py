"""测试 Prompt 资产库。"""
import json
import tempfile
from pathlib import Path
from core.prompt_library import PromptLibrary, PromptTemplate


def test_prompt_template_render():
    tmpl = PromptTemplate("test", {
        "system": "你是{role}",
        "user_template": "请回答：{question}",
        "variables": ["role", "question"],
        "tags": ["test"],
    })
    system, user = tmpl.render(role="老师", question="什么是光合作用？")
    assert "请回答：什么是光合作用？" == user


def test_prompt_library_load_and_search():
    with tempfile.TemporaryDirectory() as tmp:
        prompts_dir = Path(tmp) / "prompts"
        prompts_dir.mkdir()

        test_data = {
            "templates": {
                "test_tmpl": {
                    "name": "测试模板",
                    "system": "你是测试助手",
                    "user_template": "回答关于{question}的问题",
                    "variables": ["question"],
                    "tags": ["测试", "问答"],
                }
            },
            "version": "1.0.0",
        }
        (prompts_dir / "test.json").write_text(
            json.dumps(test_data, ensure_ascii=False), encoding="utf-8"
        )

        lib = PromptLibrary(str(prompts_dir))
        lib.load_all()

        tmpl = lib.get("test.test_tmpl")
        assert tmpl is not None
        assert tmpl.name == "test_tmpl"  # name 是 JSON 字典的 key，不是 "name" 字段

        results = lib.search_by_tag("测试")
        assert len(results) == 1

        system, user = lib.render("test.test_tmpl", question="数学")
        assert "数学" in user


def test_prompt_library_reload():
    with tempfile.TemporaryDirectory() as tmp:
        prompts_dir = Path(tmp) / "prompts"
        prompts_dir.mkdir()

        (prompts_dir / "test.json").write_text(
            json.dumps({"templates": {}, "version": "1.0.0"}), encoding="utf-8"
        )

        lib = PromptLibrary(str(prompts_dir))
        lib.load_all()
        assert lib.get("test.test_tmpl") is None

        (prompts_dir / "test.json").write_text(
            json.dumps({
                "templates": {
                    "new_tmpl": {
                        "name": "新模板", "system": "", "user_template": "",
                        "variables": [], "tags": [],
                    }
                },
                "version": "2.0.0",
            }), encoding="utf-8",
        )

        lib.reload()
        assert lib.get("test.new_tmpl") is not None


def test_prompt_library_list_all():
    with tempfile.TemporaryDirectory() as tmp:
        prompts_dir = Path(tmp) / "prompts"
        prompts_dir.mkdir()

        test_data = {
            "templates": {
                "tmpl_a": {
                    "name": "模板A", "system": "", "user_template": "",
                    "variables": [], "tags": ["tag1"],
                },
                "tmpl_b": {
                    "name": "模板B", "system": "", "user_template": "",
                    "variables": [], "tags": ["tag2"],
                },
            },
            "version": "1.0.0",
        }
        (prompts_dir / "test.json").write_text(
            json.dumps(test_data, ensure_ascii=False), encoding="utf-8"
        )

        lib = PromptLibrary(str(prompts_dir))
        lib.load_all()
        all_tmpl = lib.list_all()
        assert "test" in all_tmpl
        assert len(all_tmpl["test"]) == 2
