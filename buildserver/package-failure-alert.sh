#!/usr/bin/env bash
# Report a failed package build/publication without retrying or touching APT.
set -euo pipefail
umask 027

branch="${1:-}"
exit_code="${2:-}"
stage="${3:-unknown}"
build_log="${4:-}"
case "$branch" in
  develop|master) ;;
  *) echo "Invalid failure-report branch" >&2; exit 2 ;;
esac
[[ "$exit_code" =~ ^[1-9][0-9]*$ ]] || {
  echo "Invalid failure-report exit code" >&2; exit 2;
}

base="${RETRODE3_FAILURE_REPORT_BASE:-/srv/www/vhosts/retrode.com/buildserver}"
logdir="$base/artifacts/logs"
timestamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
suite=testing
[[ "$branch" == master ]] && suite=stable

message="FAILED: Retrode3 package run $branch ($suite), exit $exit_code, stage $stage, UTC $timestamp"
printf '\n%s\n' "$message" >&2
printf 'A partially imported APT package set is possible. Do not assume a complete release.\n' >&2
if [[ -n "$build_log" ]]; then
  printf 'Build/publish log: %s\n' "$build_log" >&2
fi

# A private marker survives unattended runs and does not disclose key material.
mkdir -p "$logdir"
marker="$logdir/last-failed-$branch.txt"
tmp="$(mktemp "$logdir/.last-failed-$branch.XXXXXXXX")"
trap 'rm -f "$tmp"' EXIT
{
  printf '%s\n' "$message"
  printf 'APT publication may be partial; inspect suite and last-published manifest.\n'
  if [[ -n "$build_log" ]]; then printf 'Log: %s\n' "$build_log"; fi
} > "$tmp"
mv -f "$tmp" "$marker"
trap - EXIT
printf 'Failure marker: %s\n' "$marker" >&2

# Optional mail. Recipient is configured externally; no credentials are sent.
recipient="${RETRODE3_BUILD_ALERT_EMAIL:-}"
if [[ -n "$recipient" ]]; then
  if [[ ! "$recipient" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
    printf 'WARNING: invalid RETRODE3_BUILD_ALERT_EMAIL; no mail sent.\n' >&2
  elif ! command -v sendmail >/dev/null 2>&1; then
    printf 'WARNING: sendmail unavailable; failure marker was saved but no mail sent.\n' >&2
  elif {
    printf 'To: %s\n' "$recipient"
    printf 'Subject: Retrode3 %s package run FAILED\n' "$branch"
    printf 'Content-Type: text/plain; charset=UTF-8\n\n'
    printf '%s\n' "$message"
    printf 'APT publication may be partial. Check the repository and last-published manifest.\n'
    if [[ -n "$build_log" ]]; then printf 'Log: %s\n' "$build_log"; fi
  } | sendmail -t -oi; then
    printf 'Failure alert handed to local mail transport for %s\n' "$recipient" >&2
  else
    printf 'WARNING: sendmail failed; failure marker was saved.\n' >&2
  fi
fi
