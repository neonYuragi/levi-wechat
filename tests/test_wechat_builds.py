"""Shared profile loading and package selection/verification regressions."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'docker'))
import wechat_builds as builds
import download_wechat as download


class SharedBuildTests(unittest.TestCase):
    def test_latest_is_numeric_and_architecture_specific(self):
        config = builds.load_config()
        for arch in ('amd64', 'arm64'):
            template = builds.latest_build(arch, config)
            older = dict(template, version='4.9.0.1')
            newer = dict(template, version='4.10.0.1')
            config['builds'] = {'older': older, 'newer': newer,
                                'other-arch': dict(template, arch='arm64' if arch == 'amd64' else 'amd64', version='99.0')}
            self.assertEqual(builds.latest_build(arch, config)['version'], '4.10.0.1')

    def test_incomplete_and_unknown_versions_cannot_be_installed(self):
        template = builds.latest_build('amd64')
        for change in ({'version': None}, {'build_id': template['build_id'][:8]},
                       {'media_download': None}):
            build = dict(template, **change)
            if change.get('media_download', True) is None:
                del build['media_download']
            with self.assertRaisesRegex(ValueError, 'No complete installable'):
                builds.latest_build('amd64', {'builds': {'fixture': build}})

    def test_masks_are_bytes_offsets_are_integers_and_copies_are_isolated(self):
        config = builds.load_config()
        extract = builds.tool_profiles('extract_keys', config)
        chat = builds.tool_profiles('chat_select', config)
        for prefix, profile in extract.items():
            self.assertIsInstance(profile['image_xor_mask'], bytes)
            self.assertEqual(len(profile['image_xor_mask']), 32)
            self.assertIsInstance(chat[prefix]['SELECT_SESSION'], int)
        extract['ce28c347']['db_xor_mask'] = b'changed'
        self.assertNotEqual(builds.tool_profiles('extract_keys', config)['ce28c347']['db_xor_mask'], b'changed')

    def test_media_profiles_keep_full_build_id_allowlist(self):
        profiles = builds.media_profiles()
        self.assertTrue(profiles)
        for build_id, profile in profiles.items():
            self.assertEqual(len(build_id), 40)
            build = builds.load_config()['builds'][build_id[:8]]
            self.assertEqual(profile, build['media_download'])

    def test_config_change_reaches_selection_without_script_edits(self):
        config = builds.load_config()
        build = builds.latest_build('amd64', config)
        config['builds']['12345678'] = dict(build, version='8.0.0.1', build_id='12345678' + '0' * 32)
        import yaml
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'builds.yaml'
            path.write_text(yaml.safe_dump(config))
            loaded = builds.load_config(path)
        self.assertEqual(builds.latest_build('amd64', loaded)['version'], '8.0.0.1')

    def test_bad_mask_and_mismatched_build_id_fail(self):
        config = builds.load_config()
        config['builds']['ce28c347']['extract_keys']['db_xor_mask'] = 'abcd'
        with self.assertRaises(ValueError):
            builds.tool_profiles('extract_keys', config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'builds.yaml'
            import yaml
            config['builds']['ce28c347']['build_id'] = '0' * 40
            path.write_text(yaml.safe_dump(config))
            with self.assertRaisesRegex(ValueError, 'Invalid BuildID'):
                builds.load_config(path)


class PackageVerificationTests(unittest.TestCase):
    def test_package_identity_and_build_id_are_verified(self):
        # Build a harmless local .deb containing /bin/true as a stand-in ELF.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'root'
            (root / 'DEBIAN').mkdir(parents=True)
            (root / 'opt/wechat').mkdir(parents=True)
            (root / 'DEBIAN/control').write_text('Package: wechat\nVersion: 1.0.0.1\nArchitecture: amd64\nMaintainer: Test <test@example.invalid>\nDescription: Synthetic test package\n')
            import shutil
            shutil.copy2('/bin/true', root / 'opt/wechat/wechat')
            package = Path(directory) / 'fixture.deb'
            subprocess.run(['dpkg-deb', '--build', str(root), str(package)], check=True, capture_output=True)
            profile = {'version': '1.0.0.1', 'arch': 'amd64', 'build_id': download.binary_build_id('/bin/true'),
                       'package_sha256': download.sha256(package)}
            download.verify_package(package, profile)
            for changes in ({'version': '2.0'}, {'arch': 'arm64'}, {'build_id': '0' * 40}, {'package_sha256': '0' * 64}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    download.verify_package(package, dict(profile, **changes))

    def test_failed_download_preserves_existing_package(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'wechat.deb'
            output.write_bytes(b'existing cached package')
            with patch.object(download.subprocess, 'run', side_effect=subprocess.CalledProcessError(22, 'curl')):
                with self.assertRaises(RuntimeError):
                    download.download(output, builds.latest_build('amd64'), ['https://example.invalid/{version}.deb'])
            self.assertEqual(output.read_bytes(), b'existing cached package')


if __name__ == '__main__':
    unittest.main()
