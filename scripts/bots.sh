#!/usr/bin/env bash
# just pause | resume | bots: boot the lab's LaunchAgents out or back in, by short name.
set -uo pipefail
action=$1; shift
domain=gui/$(id -u)
agents=~/Library/LaunchAgents

labels() {
    case $1 in
        rush | rush-remote | dagster) echo "com.pjkelly.light-labs.$1" ;;
        hermes) echo "ai.hermes.gateway" ;;
        radar) echo "com.pjkelly.relationship-radar.messages-export" \
            "com.pjkelly.relationship-radar.sync" "com.pjkelly.relationship-radar.weekly" ;;
        *) echo "unknown job $1 (rush, rush-remote, dagster, hermes, radar, all)" >&2; exit 2 ;;
    esac
}

jobs="$*"
[ "$jobs" = all ] && jobs="rush rush-remote dagster hermes radar"
for job in $jobs; do
    for label in $(labels "$job"); do
        running=$(launchctl print "$domain/$label" >/dev/null 2>&1 && echo yes)
        case $action in
            status) [ -n "$running" ] && echo "$label: running" || echo "$label: paused" ;;
            pause)
                if [ -n "$running" ]; then
                    launchctl bootout "$domain/$label" && echo "paused $label"
                else echo "$label already paused"; fi ;;
            resume)
                if [ -z "$running" ]; then
                    launchctl bootstrap "$domain" "$agents/$label.plist" && echo "resumed $label"
                else echo "$label already running"; fi ;;
        esac
    done
done
