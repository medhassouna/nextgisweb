import json
from pathlib import Path
from subprocess import check_call

from ..lib.logging import logger
from ..command import Command
from ..package import amd_packages, pkginfo
from ..pyramid.uacompat import FAMILIES


@Command.registry.register
class JSRealmInstallCommand:
    identity = 'jsrealm.install'
    no_initialize = True

    @classmethod
    def argparser_setup(cls, parser, env):
        pass

    @classmethod
    def execute(cls, args, env):
        client_packages = list()
        icon_sources = list()

        debug = env.core.options['debug']
        cwd = Path().resolve()

        for cid, cpath in pkginfo._comp_path.items():
            cpath = cpath.resolve().relative_to(cwd)
            if cid not in env._components and debug:
                logger.debug("Component [%s] excluded from build in debug mode", cid)
                continue

            jspkg = cpath / 'nodepkg'
            if jspkg.exists():
                for package_json in jspkg.glob('**/package.json'):
                    package_dir = package_json.parent
                    logger.debug("Node package %s (%s)", package_dir, cid)
                    client_packages.append(str(package_dir))

            icon_source = cpath / 'icon'
            if icon_source.exists():
                logger.debug("Icon source %s (%s)", icon_source, cid)
                icon_sources.append([cid, str(icon_source)])

        package_json = dict(private=True)
        package_json['config'] = config = dict()
        config['nextgisweb_core_debug'] = str(debug).lower()
        config['nextgisweb_jsrealm_root'] = str(cwd.resolve())
        config['nextgisweb_jsrealm_packages'] = ','.join(client_packages)
        config['nextgisweb_jsrealm_externals'] = ','.join([
            pname for pname, _ in amd_packages()])
        config['nextgisweb_jsrealm_icon_sources'] = json.dumps(icon_sources)

        ca = env.pyramid.options['compression.algorithms']
        config['nextgisweb_pyramid_compression_algorithms'] = \
            json.dumps(ca if ca else [])

        config['nextgisweb_core_locale_available'] = \
            ','.join(env.core.locale_available)

        targets = dict()
        for k in FAMILIES.keys():
            r = env.pyramid.options[f'uacompat.{k}']
            if type(r) == bool:
                continue
            targets[k] = r
        config['nextgisweb_jsrealm_targets'] = json.dumps(targets)

        webpack_config = (
            Path(__file__).parent / 'nodepkg' / 'jsrealm' / 'webpack.root.cjs'
        ).resolve().relative_to(cwd)

        package_json['scripts'] = scripts = dict()
        scripts['build'] = 'webpack --progress --config {}'.format(webpack_config)
        scripts['watch'] = 'webpack --progress --watch --config {}'.format(webpack_config)

        package_json['workspaces'] = client_packages

        with open('package.json', 'w') as fd:
            fd.write(json.dumps(package_json, indent=4))

        check_call(['yarn', 'install'])
