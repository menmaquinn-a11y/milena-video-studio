# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract tests for voice catalog; never loads untrusted RVC checkpoints."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from milena_studio.voice import VoiceBridge
from milena_studio.workflow import Workspace


class VoiceBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Workspace(Path(self.tmp.name))
        self.bridge = VoiceBridge(self.workspace)
        self.bridge.folder.mkdir(parents=True)
        (self.bridge.folder / "original_voz.pth").write_bytes(b"not an actual model")
        (self.bridge.folder / "original_voz.index").write_bytes(b"placeholder")
        (self.bridge.folder / "original_voz.json").write_text(json.dumps({
            "display_name": "Voz de teste",
            "commercial_use": True,
            "voice_owner_consent": True,
        }), encoding="utf-8")

    def test_inventory_reads_metadata_without_loading_model(self):
        result = self.bridge.inventory().structuredContent
        self.assertEqual(len(result["voices"]), 1)
        self.assertEqual(result["voices"][0]["id"], "original_voz")
        self.assertTrue(result["voices"][0]["hasIndex"])
        self.assertTrue(result["voices"][0]["consentRecorded"])

    def test_prevents_model_path_traversal(self):
        with self.assertRaisesRegex(ValueError, "identificador"):
            self.bridge.model("../outside")

    def test_refuses_conversion_without_rights_confirmation(self):
        audio = self.workspace.root / "voz.wav"
        audio.write_bytes(b"fake audio")
        with self.assertRaisesRegex(ValueError, "direitos"):
            asyncio.run(self.bridge.start(
                str(audio), "original_voz", rights_confirmed=False))

    def test_audio_must_be_inside_workspace(self):
        outside = self.workspace.root.parent / "external_audio.wav"
        with self.assertRaises(ValueError):
            self.workspace.path(str(outside))


if __name__ == "__main__":
    unittest.main()
