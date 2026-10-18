"""Shared WeChat layouts for host downloads and container-side tools."""
import copy
from pathlib import Path
import re

try:
    import yaml
except ImportError as error:
    raise ImportError('PyYAML is required; install python3-yaml or PyYAML>=6,<7') from error

CONFIG_PATH = Path(__file__).with_name('wechat-builds.yaml')
ARCH_ALIASES = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}


def normalize_arch(arch):
    try:
        return ARCH_ALIASES[arch.lower()]
    except KeyError:
        raise ValueError(f'Unsupported architecture: {arch}') from None


def load_config(path=CONFIG_PATH):
    with open(path, encoding='utf-8') as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict) or config.get('schema_version') != 1:
        raise ValueError('Unsupported WeChat build configuration schema')
    builds = config.get('builds')
    if not isinstance(builds, dict) or not builds:
        raise ValueError('No WeChat build profiles configured')
    for prefix, build in builds.items():
        if not isinstance(prefix, str) or not re.fullmatch(r'[0-9a-f]{8}', prefix):
            raise ValueError('Invalid BuildID prefix')
        build_id = build.get('build_id', '')
        if not re.fullmatch(r'[0-9a-f]{8}|[0-9a-f]{40}', build_id) or not build_id.startswith(prefix):
            raise ValueError(f'Invalid BuildID for {prefix}')
        normalize_arch(build['arch'])
        version = build.get('version')
        if version is not None and (not isinstance(version, str) or not re.fullmatch(r'\d+(?:\.\d+)+', version)):
            raise ValueError(f'Invalid version for {prefix}')
    return config


def tool_profiles(tool, config=None):
    config = load_config() if config is None else config
    profiles = {}
    for prefix, build in config['builds'].items():
        if tool not in build:
            continue
        profile = copy.deepcopy(build[tool])
        if tool == 'extract_keys':
            for field in ('db_xor_mask', 'image_xor_mask'):
                if field in profile:
                    profile[field] = bytes.fromhex(profile[field])
                    if len(profile[field]) != 32:
                        raise ValueError(f'Invalid {field} for {prefix}')
        profiles[prefix] = profile
    return profiles


def media_profiles(config=None):
    config = load_config() if config is None else config
    return {build['build_id']: copy.deepcopy(build['media_download'])
            for build in config['builds'].values()
            if 'media_download' in build and len(build['build_id']) == 40}


def fallback_profile(tool, profiles):
    """Retain explicitly configured legacy behavior for unknown builds."""
    name = load_config().get('fallbacks', {}).get(tool)
    if name not in profiles:
        raise ValueError(f'No fallback profile configured for {tool}')
    return profiles[name]


def latest_build(arch, config=None):
    """Select numerically newest installable build for the target architecture."""
    arch = normalize_arch(arch)
    config = load_config() if config is None else config
    builds = [build for build in config['builds'].values()
              if normalize_arch(build['arch']) == arch and build.get('version')
              and len(build['build_id']) == 40
              and all(tool in build for tool in ('extract_keys', 'chat_select', 'media_download'))]
    if not builds:
        raise ValueError(f'No complete installable WeChat profile for {arch}')
    return copy.deepcopy(max(builds, key=lambda build: tuple(map(int, build['version'].split('.')))))
