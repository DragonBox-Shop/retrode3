"""Publisher regression checks for one signed export after staged imports."""
from pathlib import Path
import re
import unittest


PUBLISHER = (
    Path(__file__).resolve().parents[2] / "buildserver/publish-debs.sh"
)


class StagedPublicationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = PUBLISHER.read_text()

    def test_signing_preflight_before_first_package_mutation(self):
        preflight = self.script.index('if ! timeout 20s gpg')
        include = self.script.index('includedeb "$suite" "$deb"')
        self.assertLess(preflight, include)
        self.assertIn('--pinentry-mode error', self.script[preflight:include])

    def test_stage_packages_without_export_and_keep_old_pool_files(self):
        include = self.script.index('includedeb "$suite" "$deb"')
        self.assertIn('--export=never --keepunreferencedfiles',
                      self.script[include - 110:include])
        self.assertEqual(self.script.count('includedeb "$suite" "$deb"'), 1)

    def test_single_signed_export_after_all_staging(self):
        include = self.script.index('includedeb "$suite" "$deb"')
        final = self.script.index('export "$suite"', include)
        self.assertLess(include, final)
        self.assertEqual(self.script.count('export "$suite"'), 1)
        self.assertIn('done\n\n# A previous run may have staged',
                      self.script[include:final])

    def test_failed_export_stops_before_success_message(self):
        after_export = self.script.split('export "$suite"', 1)[1]
        self.assertIn('echo "Published to APT', after_export)
        self.assertTrue(self.script.startswith('#!/usr/bin/env bash'))
        self.assertIn('set -euo pipefail', self.script)


AUTOMATION = (
    Path(__file__).resolve().parents[2] / "buildserver/auto-package.sh"
)


class BuildOnlyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = AUTOMATION.read_text()

    def test_build_only_defers_publication_for_new_candidates(self):
        built = self.script.index('run="$(sed -n')
        build_only = self.script.index('if [[ "$build_only" == 1 ]]', built)
        publish = self.script.index('failure_stage="apt-publication"', built)
        self.assertLess(build_only, publish)
        self.assertIn('exit 0', self.script[build_only:publish])
        self.assertIn('BUILD ONLY: tagged candidate ready', self.script[build_only:publish])

    def test_build_only_reuses_existing_candidate_without_publishing(self):
        match = self.script.index('echo "Resuming exact tagged candidate: $run"')
        build_only = self.script.index('if [[ "$build_only" == 1 ]]', match)
        publish = self.script.index(
            'bash "$script_dir/publish-debs.sh" "$branch" "$run"',
            match,
        )
        self.assertLess(build_only, publish)
        self.assertIn('exit 0', self.script[build_only:publish])


    def test_release_tag_is_mandatory_for_publication(self):
        self.assertIn('APT publication requires selected OS and OSCR release tags',
                      PUBLISHER.read_text())
        self.assertIn('source worktree is not the selected release tag',
                      PUBLISHER.read_text())
        self.assertIn('package manifest source tags do not match selected tags',
                      PUBLISHER.read_text())

    def test_automation_builds_exact_tagged_snapshot(self):
        self.assertIn('select-release-tag.py', self.script)
        self.assertIn('git clone --quiet --no-local', self.script)
        self.assertIn('checkout --quiet --detach "$os_sha"', self.script)
        self.assertIn('RETRODE3_PACKAGE_SOURCE_ROOT="$tag_worktree"', self.script)
        self.assertIn('RETRODE3_RELEASE_TAG="$os_tag"', self.script)
        self.assertIn('RETRODE3_OSCR_TAG="$oscr_tag"', self.script)
        self.assertNotIn('git ls-remote --exit-code "$oscr_url" "$oscr_ref"', self.script)

    def test_build_only_default_is_normal_auto_publication(self):
        self.assertIn('build_only="${RETRODE3_BUILD_ONLY:-0}"', self.script)
        self.assertIn('case "$build_only" in', self.script)
        self.assertIn('0|1)', self.script)
        self.assertIn('save_published_manifest "$run/build-manifest.json"',
                      self.script)



class LauncherIsolationTests(unittest.TestCase):
    def test_apt_only_install_does_not_touch_image_launchers(self):
        script = (Path(__file__).resolve().parents[2] /
                  "buildserver/install-launchers.sh").read_text()
        self.assertIn('install_mode="${1:---all}"', script)
        self.assertIn('case "$install_mode" in', script)
        self.assertIn('if [[ "$install_mode" == --packages-only ]]', script)
        self.assertIn('file_mode=750', script)
        self.assertIn('file_mode=640', script)
        self.assertIn('install -m "$file_mode"', script)
        # Guard against overwriting the installation mode with file modes.
        self.assertNotRegex(script, r'(?m)(?<![A-Za-z_])mode=(?:640|750)')
        self.assertLess(script.index('if [[ "$install_mode" == --packages-only ]]'),
                        script.index('# The image launchers run'))
        self.assertIn('exit 0', script[
            script.index('if [[ "$install_mode" == --packages-only ]]'):
            script.index('# The image launchers run')])

    def test_interactive_signer_is_installed_without_touching_image_scripts(self):
        installer = (Path(__file__).resolve().parents[2] /
                     "buildserver/install-launchers.sh").read_text()
        self.assertIn('unlock-apt-signing.sh', installer)
        signer = (Path(__file__).resolve().parents[2] /
                  "buildserver/unlock-apt-signing.sh").read_text()
        self.assertIn('[[ -t 0 && -t 1 ]]', signer)
        self.assertIn('[[ "$(id -un)" == retrode ]]', signer)
        self.assertIn('GPG_TTY="$(tty)"', signer)
        self.assertIn('updatestartuptty /bye', signer)
        self.assertIn('pinentry-program /usr/bin/pinentry-curses', signer)
        self.assertIn('gpgconf --homedir "$GNUPGHOME" --reload gpg-agent', signer)
        self.assertIn('SignWith', signer)
        self.assertIn('--batch --no-tty --pinentry-mode error', signer)
        self.assertNotRegex(signer, r'(?m)^\s*reprepro\s')
        self.assertNotIn('--passphrase-file', signer)
        self.assertNotIn('--passphrase-fd', signer)





if __name__ == "__main__":
    unittest.main()
