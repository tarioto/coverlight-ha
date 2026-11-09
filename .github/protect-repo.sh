#!/bin/sh
# Applies main-branch protection and security settings to tarioto/coverlight-ha.
set -e
repo=tarioto/coverlight-ha
here=$(dirname "$0")
gh api -X POST "repos/$repo/rulesets" --input "$here/ruleset-main.json" --jq '"ruleset: " + .name'
gh api -X PUT "repos/$repo/vulnerability-alerts" && echo "dependabot alerts: on"
gh api -X PUT "repos/$repo/private-vulnerability-reporting" && echo "private vulnerability reporting: on"
gh api -X PATCH "repos/$repo" --silent \
  -F "security_and_analysis[secret_scanning][status]=enabled" \
  -F "security_and_analysis[secret_scanning_push_protection][status]=enabled" && echo "secret scanning + push protection: on"
