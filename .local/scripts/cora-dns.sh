#!/usr/bin/env bash
# Shared DNS host collision logic for wt (worktrees) and ebox (E2B sandboxes).
# When the same logical name exists in both registries for the same zone,
# suffix -wt / -ebox so Caddy never sees ambiguous site blocks.
#
# Optional: export CORA_GIT_ROOT to the main repo checkout when not cwd'd there
# (ebox sets this from _ebox_main_repo_root).

CORA_DNS_REGISTRY="${CORA_DNS_REGISTRY:-$HOME/.config/ebox/registry.json}"
CORA_CADDYFILE="${CORA_CADDYFILE:-/etc/caddy/Caddyfile}"

_cora_slug() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-+/-/g'
}

_cora_git_root() {
  if [ -n "${CORA_GIT_ROOT:-}" ]; then
    printf '%s' "$CORA_GIT_ROOT"
    return 0
  fi
  git rev-parse --show-toplevel 2>/dev/null || true
}

_cora_main_repo_root() {
  local root common
  root="$(_cora_git_root)" || return 1
  [ -n "$root" ] || return 1
  common="$(git -C "$root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  common="${common%/}"
  if [[ "$common" == */.git ]]; then
    dirname "$common"
  else
    dirname "$common"
  fi
}

# e.g. cora.test
_cora_wt_zone() {
  local main
  main="$(_cora_main_repo_root)" || return 1
  printf '%s.test' "$(_cora_slug "$(basename "$main")")"
}

_cora_ebox_zone_for() {
  local name="$1" z
  if [ -f "$CORA_DNS_REGISTRY" ]; then
    z="$(jq -r --arg n "$name" '.[$n].dns_zone // empty' "$CORA_DNS_REGISTRY" 2>/dev/null)"
    if [ -n "$z" ]; then
      printf '%s' "$z"
      return 0
    fi
  fi
  _cora_wt_zone
}

# Basenames of all git worktrees for the current repo (one per line).
_cora_wt_names() {
  local main line path name
  main="$(_cora_main_repo_root)" || return 0
  while IFS= read -r line; do
    case "$line" in
      worktree\ *)
        path="${line#worktree }"
        name="$(basename "$path")"
        [ -n "$name" ] && printf '%s\n' "$name"
        ;;
    esac
  done < <(git -C "$main" worktree list --porcelain 2>/dev/null)
}

_cora_ebox_names() {
  [ -f "$CORA_DNS_REGISTRY" ] || return 0
  jq -r 'keys[]' "$CORA_DNS_REGISTRY" 2>/dev/null
}

# True when the same slug exists as both a worktree and an ebox in the same zone.
_cora_names_collide() {
  local name="$1" want wt_zone ezone
  want="$(_cora_slug "$name")"
  [ -n "$want" ] || return 1

  local found_wt=0 found_ebox=0 wn en
  while IFS= read -r wn; do
    [ -n "$wn" ] || continue
    [ "$(_cora_slug "$wn")" = "$want" ] && found_wt=1 && break
  done < <(_cora_wt_names)

  while IFS= read -r en; do
    [ -n "$en" ] || continue
    [ "$(_cora_slug "$en")" = "$want" ] && found_ebox=1 && break
  done < <(_cora_ebox_names)

  [ "$found_wt" = 1 ] && [ "$found_ebox" = 1 ] || return 1

  wt_zone="$(_cora_wt_zone)" || return 1
  ezone="$(_cora_ebox_zone_for "$name")"
  [ -n "$ezone" ] && [ "$wt_zone" = "$ezone" ]
}

# kind: wt | ebox — appended as -wt / -ebox only when _cora_names_collide.
_cora_host_slug() {
  local kind="$1" name="$2" base
  base="$(_cora_slug "$name")"
  if _cora_names_collide "$name"; then
    printf '%s-%s' "$base" "$kind"
  else
    printf '%s' "$base"
  fi
}

_cora_caddy_reload() {
  if ! sudo caddy validate --config "$CORA_CADDYFILE" 2>&1; then
    echo "cora-dns: caddy config invalid — not reloading" >&2
    return 1
  fi
  sudo systemctl reload caddy
}
