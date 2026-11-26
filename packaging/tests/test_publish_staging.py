"""Publisher regression checks for one signed export after staged imports."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
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

    def test_optional_local_secret_priming_happens_before_apt_mutation(self):
        secret = self.script.index('signing_secret_dir=')
        priming = self.script.index('--passphrase-file "$signing_secret"')
        preflight = self.script.index('if ! timeout 20s gpg', priming)
        include = self.script.index('includedeb "$suite" "$deb"')
        self.assertLess(secret, priming)
        self.assertLess(priming, preflight)
        self.assertLess(preflight, include)
        self.assertIn('--pinentry-mode loopback', self.script[secret:preflight])
        self.assertIn('--pinentry-mode error', self.script[preflight:include])
        self.assertIn('validate_apt_signing_secret "$signing_secret_dir" "$signing_secret"',
                      self.script[secret:preflight])
        self.assertIn('apt-signing-secret.sh', self.script[secret:preflight])
        self.assertIn('[[ -e "$signing_secret" || -L "$signing_secret" ]]',
                      self.script[secret:preflight])
        self.assertIn('no packages imported', self.script[secret:preflight])
        # The secret is never injected as a command-line value or a process env var.
        self.assertNotIn('--passphrase "', self.script)
        self.assertNotIn('export apt_passphrase=', self.script)
        self.assertNotIn('cat "$signing_secret"', self.script)

    def test_meta_package_validation_precedes_apt_import(self):
        check = self.script.index("builder.validate_meta_manifest(manifest, lock)")
        depends = self.script.index('if depends != expected_meta_depends:')
        include = self.script.index('includedeb "$suite" "$deb"')
        self.assertLess(check, depends)
        self.assertLess(depends, include)
        self.assertIn("unexpected meta-package for selected historical OS tag",
                      self.script)

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
        self.assertIn('BUILD ONLY: source candidate ready', self.script[build_only:publish])

    def test_build_only_reuses_existing_candidate_without_publishing(self):
        match = self.script.index('echo "Resuming exact source candidate: $run"')
        build_only = self.script.index('if [[ "$build_only" == 1 ]]', match)
        publish = self.script.index(
            'bash "$script_dir/publish-debs.sh" "$branch" "$run"',
            match,
        )
        self.assertLess(build_only, publish)
        self.assertIn('exit 0', self.script[build_only:publish])


    def test_manifest_tags_match_selected_source(self):
        self.assertIn('package manifest source tags do not match selected tags',
                      PUBLISHER.read_text())

    def test_image_launcher_explicitly_requires_tag_mode(self):
        script = (AUTOMATION.parent / "run-image.sh").read_text()
        self.assertIn('RETRODE3_SOURCE_MODE=tag RETRODE3_BUILD_ONLY=0 bash "$vhost/package_$branch.sh"',
                      script)
        self.assertIn('selection="$(python3 "$selector" "$checkout" "$branch")"', script)
        self.assertIn('selection="$(python3 "$selector" "$oscr_history" "$branch")"', script)
        self.assertIn('verify-image-snapshot.py', script)
        self.assertIn('"$published" "$suite" "$branch" "$os_tag" "$os_sha" "$oscr_tag" "$oscr_sha"',
                      script)

    def test_automation_builds_exact_source_snapshot(self):
        self.assertIn('source_mode="${RETRODE3_SOURCE_MODE:-branch}"', self.script)
        self.assertIn('os_sha="$(git -C "$checkout" rev-parse "refs/heads/$branch")"', self.script)
        self.assertIn('oscr_sha="$(git --git-dir="$oscr_history" rev-parse "refs/heads/$branch")"', self.script)
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



class SourceSelectionTests(unittest.TestCase):
    def test_publication_source_gate(self):
        # Stop at the missing-candidate gate, before any APT/GPG access.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(("RETRODE3_", "GIT_"))}

            def git(repo, *args):
                return subprocess.check_output(
                    ["git", "-C", str(repo), *args], env=env,
                    stderr=subprocess.STDOUT, text=True).strip()

            def history(name):
                repo = base / name
                repo.mkdir()
                git(repo, "init", "-q", "-b", "develop")
                for version in ("old", "new"):
                    git(repo, "-c", "user.name=Preflight", "-c",
                        "user.email=preflight@example.invalid", "-c",
                        "commit.gpgsign=false", "commit", "--allow-empty",
                        "-qm", name + "-" + version)
                    git(repo, "-c", "tag.gpgsign=false", "tag", version)
                return repo, git(repo, "rev-parse", "old"), git(repo, "rev-parse", "HEAD")

            root, os_old, os_head = history("os")
            native, native_old, native_head = history("oscr")
            bare = base / "oscr.git"
            git(native, "clone", "-q", "--bare", str(native), str(bare))
            env.update(RETRODE3_PACKAGE_SOURCE_ROOT=str(root),
                       RETRODE3_RELEASE_COMMIT=os_head,
                       RETRODE3_OSCR_COMMIT=native_head,
                       RETRODE3_OSCR_HISTORY=str(bare),
                       RETRODE3_FOLLOW_OSCR_BRANCH="1")
            cases = (
                ("default branch without tags", True, {}),
                ("explicit branch without tags", True, {"RETRODE3_SOURCE_MODE": "branch"}),
                ("branch with tag", False, {"RETRODE3_RELEASE_TAG": "new"}),
                ("branch stale native commit", False, {"RETRODE3_OSCR_COMMIT": native_old}),
                ("branch wrong OS commit", False, {"RETRODE3_RELEASE_COMMIT": os_old}),
                ("tag mode without tags", False, {"RETRODE3_SOURCE_MODE": "tag"}),
                ("tag mode missing OSCR tag", False, {"RETRODE3_SOURCE_MODE": "tag", "RETRODE3_RELEASE_TAG": "new"}),
                ("tag mode missing OS tag", False, {"RETRODE3_SOURCE_MODE": "tag", "RETRODE3_OSCR_TAG": "new"}),
                ("tag mode matching tags", True, {"RETRODE3_SOURCE_MODE": "tag", "RETRODE3_RELEASE_TAG": "new", "RETRODE3_OSCR_TAG": "new"}),
                ("tag mode wrong tag", False, {"RETRODE3_SOURCE_MODE": "tag", "RETRODE3_RELEASE_TAG": "new", "RETRODE3_OSCR_TAG": "old"}),
                ("unknown mode", False, {"RETRODE3_SOURCE_MODE": "invalid"}),
            )

            def check(accepted, overrides):
                result = subprocess.run(
                    ["bash", str(PUBLISHER), "develop", str(base / "missing-run")],
                    env=dict(env, **overrides), capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual("use an absolute build run directory" in result.stderr,
                                 accepted, result.stderr)

            for label, accepted, overrides in cases:
                with self.subTest(label=label):
                    check(accepted, overrides)

            # Even repositories that have never had a release tag may build.
            git(root, "tag", "-d", "old", "new")
            git(bare, "tag", "-d", "old", "new")
            check(True, {})
            check(False, {"RETRODE3_SOURCE_MODE": "tag",
                          "RETRODE3_RELEASE_TAG": "new", "RETRODE3_OSCR_TAG": "new"})


class LauncherIsolationTests(unittest.TestCase):
    def test_automation_only_keeps_all_existing_launchers(self):
        script = (Path(__file__).resolve().parents[2] /
                  "buildserver/install-launchers.sh").read_text()
        start = script.index('if [[ "$install_mode" == --automation-only ]]')
        end = script.index('for spec in "master:', start)
        self.assertIn("exit 0", script[start:end])
        self.assertIn("apt-signing-secret.sh", script[:start])

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
