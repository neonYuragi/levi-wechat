#!/usr/bin/env python3
"""Download and verify the newest supported package from wechat-builds.yaml."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

from wechat_builds import latest_build, load_config, normalize_arch


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def binary_build_id(path):
    notes = subprocess.check_output(['readelf', '-n', str(path)], text=True)
    matches = re.findall(r'Build ID:\s*([0-9a-f]+)', notes)
    if len(matches) != 1:
        raise ValueError('Could not identify WeChat binary BuildID')
    return matches[0]


def verify_package(path, build):
    expected_digest = build.get('package_sha256')
    if not expected_digest or sha256(path) != expected_digest:
        raise ValueError('Package SHA256 does not match the selected profile')
    for field, expected in [('Package', 'wechat'), ('Version', build['version']),
                            ('Architecture', normalize_arch(build['arch']))]:
        actual = subprocess.check_output(['dpkg-deb', '--field', str(path), field], text=True).strip()
        if actual != expected:
            raise ValueError(f'Package {field}: expected {expected}, got {actual}')
    with tempfile.TemporaryDirectory(prefix='wechat-package-check-') as directory:
        subprocess.run(['dpkg-deb', '--extract', str(path), directory], check=True)
        if binary_build_id(Path(directory) / 'opt/wechat/wechat') != build['build_id']:
            raise ValueError('Package BuildID does not match the selected profile')


def verify_installed(build):
    version = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'wechat'], text=True).strip()
    arch = subprocess.check_output(['dpkg-query', '-W', '-f=${Architecture}', 'wechat'], text=True).strip()
    if version != build['version'] or arch != normalize_arch(build['arch']):
        raise ValueError('Installed WeChat version or architecture does not match the selected profile')
    if binary_build_id('/opt/wechat/wechat') != build['build_id']:
        raise ValueError('Installed WeChat BuildID does not match the selected profile')


def download(output, build, templates):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        try:
            verify_package(output, build)
            print(f'Using verified cached package: {output}', flush=True)
            return
        except (ValueError, subprocess.CalledProcessError) as error:
            print(f'Cached package is incompatible: {error}', flush=True)
    vendor_arch = 'x86_64' if normalize_arch(build['arch']) == 'amd64' else 'arm64'
    errors = []
    with tempfile.TemporaryDirectory(prefix='wechat-download-', dir=output.parent) as directory:
        partial = Path(directory) / 'wechat.deb'
        for template in templates:
            url = template.format(version=build['version'], arch=normalize_arch(build['arch']), vendor_arch=vendor_arch)
            print(f'Downloading {url}', flush=True)
            try:
                subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                                '--retry', '2', '--connect-timeout', '15', '--max-time', '900',
                                '--output', str(partial), url], check=True)
                verify_package(partial, build)
            except (ValueError, subprocess.CalledProcessError) as error:
                errors.append(str(error))
                print(f'Source failed verification or download: {error}', flush=True)
                continue
            if output.exists():
                backup_dir = output.parent / 'cache'
                backup_dir.mkdir(exist_ok=True)
                backup = backup_dir / f'wechat-{sha256(output)[:16]}.deb'
                if not backup.exists():
                    shutil.copy2(output, backup)
                print(f'Previous package preserved: {backup}', flush=True)
            partial.replace(output)
            print(f'Saved verified WeChat package: {output}', flush=True)
            return
    raise RuntimeError('No source provided a compatible package: ' + '; '.join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch', default=platform.machine())
    parser.add_argument('--output', default=str(Path(__file__).with_name('wechat.deb')))
    parser.add_argument('--describe', action='store_true')
    parser.add_argument('--verify-installed', action='store_true')
    args = parser.parse_args()
    config = load_config()
    build = latest_build(args.arch, config)
    if args.describe:
        print(json.dumps({key: build[key] for key in ('version', 'arch', 'build_id', 'package_sha256')}))
        return
    print(f'Selected supported WeChat: {build["version"]} ({build["arch"]}), BuildID {build["build_id"]}', flush=True)
    if args.verify_installed:
        verify_installed(build)
    else:
        download(args.output, build, config['download_urls'])


if __name__ == '__main__':
    main()
