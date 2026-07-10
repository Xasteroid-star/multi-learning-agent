"""
Prompt 资产库 — 统一管理和检索所有 Prompt 模板。

功能：
1. 从 JSON 文件加载模板，按 tag/name 检索
2. 支持变量插值生成完整 Prompt
3. 版本追踪和热加载

JD 对应：JD 第一条「沉淀公司的 Prompt 资产库」
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PromptTemplate:
    """单个 Prompt 模板。"""

    def __init__(self, name: str, data: dict) -> None:
        self.name = name
        self.system: str = data.get("system", "")
        self.user_template: str = data.get("user_template", "")
        self.variables: list[str] = data.get("variables", [])
        self.tags: list[str] = data.get("tags", [])

    def render(self, **kwargs) -> tuple[str, str]:
        """用变量填充模板，返回 (system_prompt, user_prompt)。"""
        filled_user = self.user_template
        for var in self.variables:
            if var in kwargs:
                filled_user = filled_user.replace(f"{{{var}}}", str(kwargs[var]))
        return self.system, filled_user

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "system": self.system,
            "user_template": self.user_template,
            "variables": self.variables,
            "tags": self.tags,
        }


class PromptLibrary:
    """Prompt 资产库管理器。"""

    def __init__(self, prompts_dir: str = "data/prompts") -> None:
        self._prompts_dir = Path(prompts_dir)
        self._templates: dict[str, PromptTemplate] = {}
        self._by_tag: dict[str, list[str]] = {}
        self._versions: dict[str, str] = {}

    def load_all(self) -> None:
        """加载所有 Prompt 模板文件。"""
        if not self._prompts_dir.exists():
            logger.warning("Prompts directory not found: %s", self._prompts_dir)
            return

        for json_file in self._prompts_dir.glob("*.json"):
            self._load_file(json_file)

        logger.info(
            "PromptLibrary loaded: %d templates in %d categories",
            len(self._templates),
            len(self._versions),
        )

    def _load_file(self, filepath: Path) -> None:
        """加载单个 JSON 模板文件。"""
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load prompt file %s: %s", filepath, e)
            return

        category = filepath.stem
        self._versions[category] = data.get("version", "0.0.0")

        for tmpl_name, tmpl_data in data.get("templates", {}).items():
            key = f"{category}.{tmpl_name}"
            template = PromptTemplate(tmpl_name, tmpl_data)
            self._templates[key] = template

            for tag in template.tags:
                self._by_tag.setdefault(tag, []).append(key)

    def get(self, key: str) -> Optional[PromptTemplate]:
        """按 key 获取模板，如 'report.growth_report'。"""
        return self._templates.get(key)

    def search_by_tag(self, tag: str) -> list[PromptTemplate]:
        """按标签检索模板。"""
        keys = self._by_tag.get(tag, [])
        return [self._templates[k] for k in keys if k in self._templates]

    def list_all(self) -> dict[str, list[dict]]:
        """列出所有模板（按 category 分组）。"""
        result: dict[str, list[dict]] = {}
        for key, tmpl in self._templates.items():
            category = key.split(".")[0]
            result.setdefault(category, []).append({
                "key": key,
                "name": tmpl.name,
                "tags": tmpl.tags,
                "variables": tmpl.variables,
            })
        return result

    def render(self, key: str, **kwargs) -> tuple[str, str] | None:
        """获取模板并渲染。"""
        tmpl = self.get(key)
        if tmpl is None:
            logger.warning("Prompt template not found: %s", key)
            return None
        return tmpl.render(**kwargs)

    def reload(self) -> None:
        """热加载所有模板（不重启服务）。"""
        self._templates.clear()
        self._by_tag.clear()
        self._versions.clear()
        self.load_all()
