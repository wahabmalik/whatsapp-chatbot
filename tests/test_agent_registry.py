import json
import tempfile
import unittest
from pathlib import Path

from app.services import agent_registry


class AgentRegistryTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp_dir.name)
        self.skills_dir = self.root / "skills"
        self.agent_manifest_file = self.root / "_bmad" / "_config" / "agent-manifest.csv"
        self.selection_file = self.root / "data" / "agent_selection.json"

        self._orig_skills_dir = agent_registry.SKILLS_DIR
        self._orig_agent_manifest_file = agent_registry.AGENT_MANIFEST_FILE
        self._orig_selection_file = agent_registry.SELECTION_FILE

        agent_registry.SKILLS_DIR = self.skills_dir
        agent_registry.AGENT_MANIFEST_FILE = self.agent_manifest_file
        agent_registry.SELECTION_FILE = self.selection_file

    def tearDown(self):
        agent_registry.SKILLS_DIR = self._orig_skills_dir
        agent_registry.AGENT_MANIFEST_FILE = self._orig_agent_manifest_file
        agent_registry.SELECTION_FILE = self._orig_selection_file
        self._tmp_dir.cleanup()

    def _write_customize(self, agent_folder: str, content: str) -> None:
        folder = self.skills_dir / agent_folder
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "customize.toml").write_text(content, encoding="utf-8")

    def _write_agent_manifest(self, content: str) -> None:
        self.agent_manifest_file.parent.mkdir(parents=True, exist_ok=True)
        self.agent_manifest_file.write_text(content, encoding="utf-8")

    def test_list_bmad_agents_includes_manifest_agents(self):
        self._write_agent_manifest(
            "\n".join(
                [
                    "name,displayName,title,icon,capabilities,role,identity,communicationStyle,principles,module,path,canonicalId",
                    '"bmad-agent-analyst","Mary","Business Analyst","📊","","","","","","bmm","_bmad/bmm/1-analysis/bmad-agent-analyst",""',
                    '"bmad-agent-dev","Amelia","Developer Agent","💻","","","","","","bmm","_bmad/bmm/4-implementation/bmad-agent-dev",""',
                ]
            )
        )

        agents = agent_registry.list_bmad_agents()
        codes = {item["code"] for item in agents}

        self.assertIn("bmad-agent-analyst", codes)
        self.assertIn("bmad-agent-dev", codes)

    def test_list_bmad_agents_supports_agent_and_agents_layouts(self):
        self._write_customize(
            "agent-alpha",
            """
[agent]
code = "alpha"
name = "Alpha"
title = "Primary Agent"
description = "Current metadata layout"
""".strip(),
        )

        self._write_customize(
            "agent-beta",
            """
[agents.beta]
name = "Beta"
title = "Legacy Agent"
description = "Legacy metadata layout"
""".strip(),
        )

        agents = agent_registry.list_bmad_agents()
        by_code = {item["code"]: item for item in agents}

        self.assertIn("alpha", by_code)
        self.assertEqual(by_code["alpha"]["name"], "Alpha")
        self.assertIn("beta", by_code)
        self.assertEqual(by_code["beta"]["name"], "Beta")

    def test_customize_metadata_overrides_manifest_for_same_code(self):
        self._write_agent_manifest(
            "\n".join(
                [
                    "name,displayName,title,icon,capabilities,role,identity,communicationStyle,principles,module,path,canonicalId",
                    '"whatsapp-support-ops","Manifest Name","Manifest Title","📟","","","","","","custom","skills/agent-whatsapp-support-ops",""',
                ]
            )
        )

        self._write_customize(
            "agent-whatsapp-support-ops",
            """
[agent]
code = "whatsapp-support-ops"
name = "Nia"
title = "WhatsApp Support Ops Specialist"
description = "Current metadata layout"
""".strip(),
        )

        agents = agent_registry.list_bmad_agents()
        by_code = {item["code"]: item for item in agents}

        self.assertEqual(by_code["whatsapp-support-ops"]["name"], "Nia")
        self.assertEqual(
            by_code["whatsapp-support-ops"]["title"],
            "WhatsApp Support Ops Specialist",
        )

    def test_get_selected_agent_repairs_stale_saved_selection(self):
        self._write_customize(
            "agent-whatsapp-support-ops",
            """
[agent]
code = "whatsapp-support-ops"
name = "Nia"
title = "WhatsApp Support Ops Specialist"
""".strip(),
        )

        self.selection_file.parent.mkdir(parents=True, exist_ok=True)
        self.selection_file.write_text(
            json.dumps({"selected_agent_code": "missing-agent"}),
            encoding="utf-8",
        )

        selected_agent = agent_registry.get_selected_agent()

        self.assertIsNotNone(selected_agent)
        self.assertEqual(selected_agent["code"], "whatsapp-support-ops")
        self.assertEqual(
            agent_registry.get_selected_agent_code(),
            "whatsapp-support-ops",
        )


if __name__ == "__main__":
    unittest.main()