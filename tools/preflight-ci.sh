#!/bin/sh
# Reproduce the OS packaging/Web smoke checks before publishing a commit.
# Cross-compilation and physical Retrode3 tests are separate gates.
set -eu
cd "$(dirname "$0")/.."

for tool in bash python3 node php visudo; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'Missing required tool: %s\n' "$tool" >&2
        exit 1
    fi
done

for p in packaging/maintainer/* packaging/assets/*.start; do
    sh -n "$p"
done
sh -n retrode3-web-control/v2/service/retrode3-web-v2.init
sh -n retrode3-core-runtime/etc/init.d/retrode3-core-runtime
bash -n make-all retrode3.qcodeproj retrode3-tools/retrode3-tools.qcodeproj
bash -n retrode3-web-control/retrode3-web-control.qcodeproj
visudo -cf packaging/assets/retrode3-corectl.sudoers
visudo -cf retrode3-tools/etc/sudoers.d/retrode3

! grep -Fq 'DEBIAN_RECOMMENDS="oscr"' retrode3.qcodeproj
! grep -Fq 'PACKAGES+=" oscr"' make-all
! grep -Fq 'SOURCES="oscr.qcodeproj"' retrode3-tools/retrode3-tools.qcodeproj

python3 -m json.tool packaging/native-source-lock.json >/dev/null
python3 -m json.tool packaging/retrode3-core-layout.json >/dev/null
python3 -m json.tool packaging/core-meta.json >/dev/null
bash -n buildserver/stage-oscr-plugins.sh
python3 -m py_compile packaging/build-debs.py
python3 -m py_compile retrode3-web-control/v2/backend/service.py retrode3-web-control/v2/backend/http_gateway.py
sh -n image/assets/retrode3-memory.init
python3 -m unittest discover -s image/tests -p 'test_finalize_apt.py' -v
python3 -m unittest discover -s image/tests -p 'test_verify_lighttpd_offline.py' -v
python3 -m unittest discover -s packaging/tests -p 'test_*.py' -v
python3 -m unittest discover -s retrode3-web-control/v2/tests -p 'test_*.py' -v

node --check retrode3-web-control/v2/web/assets/app.js
node --check retrode3-web-control/v2/web/assets/selection-ui.js
node retrode3-web-control/v2/tests/test_frontend_generic_selection.js
node retrode3-web-control/v2/tests/test_frontend_v3_job.js
node retrode3-web-control/v2/tests/test_frontend_job_progress.js
node retrode3-web-control/v2/tests/test_frontend_flash_writer.js
node retrode3-web-control/v2/tests/test_frontend_filename.js
node retrode3-web-control/v2/tests/test_frontend_slot_card.js
node retrode3-web-control/v2/tests/test_frontend_slot_poll.js
node retrode3-web-control/v2/tests/test_documentation_links.js

! grep -Eq 'nes-choice|nes-manual-toggle|mapping-control|size-control' retrode3-web-control/v2/web/index.php
! grep -Eq 'nesReadAllowed|validate_nes_options|NES_OPTION_KEYS|nes_options' retrode3-web-control/v2/backend/service.py
! grep -Eq 'nesReadAllowed|renderNesOptions|populateNesManualSizes' retrode3-web-control/v2/web/assets/app.js

python3 -m json.tool retrode3-web-control/v2/web/locales/de.json >/dev/null
python3 -m json.tool retrode3-web-control/v2/web/locales/en.json >/dev/null
for file in retrode3-web-control/v2/web/*.php; do
    php -l "$file"
done
for file in retrode3-web-control/v2/*on-retrode.sh; do
    sh -n "$file"
done

! grep -Fq 'retrode3-web-control/retrode3-web-control.qcodeproj' retrode3.qcodeproj
! grep -Fq 'DEBIAN_DEPENDS+=", retrode3-web-control"' retrode3.qcodeproj
! grep -Fq 'PACKAGES+=" retrode3-web-control"' make-all
grep -Fq 'exit 1' retrode3-web-control/retrode3-web-control.qcodeproj

printf '\nPre-push OS/Web/package mocks passed. MIPS cross-build and physical package tests remain separate gates.\n'
