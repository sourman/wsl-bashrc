# ============================================================================
# Custom bash functions
# ============================================================================

# Push to all remotes (never forget a mirror)
pushy() {
  git remote | while read remote; do
    echo "Pushing to $remote..."
    git push "$remote" "$@"
  done
}

# Wrap an XML/HTML tag around a file's contents
kayes() {
  local f="$1" tag="$2"
  { echo "<$tag>"; cat "$f"; echo "</$tag>"; } > "$f.tmp" && mv "$f.tmp" "$f"
}

# Peek at the last N supabase migrations (default 5)
rukn() { supabase migration list | tail -"${1:-5}"; }

# Trick Cursor's terminal tool into waiting — it skips bare `sleep N` calls
holdon() { sleep "$(($1))"; }

# ============================================================================
# wt — worktree navigator. Jump is the universal default.
#   wt                fzf-pick a worktree → cd
#   wt feat-mcp       substring-match → cd (1 match: instant, N matches: fzf)
#   wt list | wt ls   list worktrees (name + branch + path)
#   wt rm [name]      remove worktree + delete its branch (-d safe; -f force; -k keep)
#   wt prune          prune stale worktree refs
#   wt help           this help
# ============================================================================
_wt_list_porcelain() {
  git worktree list --porcelain 2>/dev/null
}

# Print "name<TAB>branch<TAB>path" per worktree (excludes the bare HEAD/detached)
_wt_entries() {
  local name branch path line
  while IFS= read -r line; do
    case "$line" in
      worktree\ *) path="${line#worktree }"; name="$(basename "$path")";;
      branch\ *)   branch="${line#branch refs/heads/}";;
      "")
        # blank line = end of record; emit if we have a path
        [ -n "$path" ] && printf '%s\t%s\t%s\n' "$name" "${branch:-detached}" "$path"
        name=""; branch=""; path="";;
    esac
  done < <(_wt_list_porcelain)
  # emit the last record if file didn't end with blank line
  [ -n "$path" ] && printf '%s\t%s\t%s\n' "$name" "${branch:-detached}" "$path"
}

# fzf picker over worktree entries → echoes the chosen PATH (nothing if aborted)
# Feed raw "name<TAB>branch<TAB>path" rows straight through fzf (matching the
# Ctrl+R pattern: no preformatting, let fzf's display opts do the work).
# --with-nth=1,2 shows name+branch; the full tab-separated line is returned
# so we can cleanly extract field 3 (the path) with awk afterwards.
#
# ble.sh ESC fix: under ble.sh, the line editor can intercept the ESC key before
# fzf sees it, making Escape do nothing. We explicitly detach ble.sh's decoder
# before launching fzf and re-attach after, so fzf owns the terminal cleanly.
_wt_fzf_path() {
  local query="${1:-}" had_ble=0
  if [[ ${BLE_VERSION-} ]] && declare -F ble/decode/detach >/dev/null 2>&1; then
    had_ble=1; ble/decode/detach
  fi
  # Aligned picker rows: line 1 = column header; each data line is
  # "<padded name>  <branch>  <dev>  <supabase>\t<path>" so fzf shows the
  # display (--with-nth=1) and we recover the path (field 2) afterwards.
  local -a rows
  local table
  # Build via a pipe into $(...) rather than a nested <(...) process
  # substitution, which can race the SERVE-loop probe inside _wt_state_init.
  table=$(_wt_rich_entries | awk -F'\t' '
    function max(a,b){return a>b?a:b}
    { nm[NR]=$1; br[NR]=($2==$1?"-":$2); pt[NR]=$3; dv[NR]=$4; sb[NR]=$5; ul[NR]=($6==""?"-":$6)
      w1=max(w1,length(nm[NR])); w2=max(w2,length(br[NR])); w3=max(w3,length(dv[NR])); w4=max(w4,length(ul[NR])) }
    END { h1="WORKTREE"; h2="BRANCH"; h3="DEV"; h4="URL"
      w1=max(w1,length(h1)); w2=max(w2,length(h2)); w3=max(w3,length(h3)); w4=max(w4,length(h4))
      printf "%-*s  %-*s  %-*s  %-*s  %s\n", w1,h1, w2,h2, w3,h3, w4,h4, "supabase"
      for (i=1;i<=NR;i++) printf "%-*s  %-*s  %-*s  %-*s  %s\t%s\n", w1,nm[i], w2,br[i], w3,dv[i], w4,ul[i], sb[i], pt[i] }')
  mapfile -t rows <<< "$table"
  local header="${rows[0]}" legend
  legend="$(_wt_fzf_header)"
  [ -n "$legend" ] && header="$header"$'\n'"$legend"
  local sel
  sel=$(printf '%s\n' "${rows[@]:1}" \
    | fzf --query="$query" --prompt='worktree> ' \
          --delimiter='\t' --with-nth=1 --header="$header" \
          --height=40% --min-height=20 --reverse \
    | awk -F'\t' '{print $2}')
  local rc=$?
  if (( had_ble )) && declare -F ble/decode/attach >/dev/null 2>&1; then
    ble/decode/attach
  fi
  printf '%s\n' "$sel"
  return $rc
}

# ============================================================================
# wt — status helpers. Pure reads (docker/ps/ss/config); no supabase CLI (it's
# slow and misreports state — supabase/cli#2419). State computed once per command.
# ============================================================================

# project_id from a worktree's supabase/config.toml (empty if no config)
_wt_pid_for_path() {
  local cfg="$1/supabase/config.toml"
  [ -f "$cfg" ] || return 0
  awk -F'"' '/^project_id *=/{print $2; exit}' "$cfg" 2>/dev/null
}

# assigned vite base port from <path>/.vite-port (empty if absent/invalid)
_wt_vite_port_for_path() {
  local f="$1/.vite-port"
  [ -f "$f" ] || return 0
  local v; v="$(head -1 "$f" 2>/dev/null | tr -d '[:space:]')"
  [[ "$v" =~ ^[0-9]+$ ]] && echo "$v"
}

# Cache docker ps + volumes + listening ports + serve watchers once.
_wt_state_init() {
  [ "${_WT_STATE_LOADED:-0}" = 1 ] && return 0
  _WT_DPS="$(docker ps --format '{{.Names}}\t{{.Ports}}\t{{.Status}}' 2>/dev/null)"
  _WT_DVL="$(docker volume ls --format '{{.Name}}' 2>/dev/null | grep '^supabase_')"
  _WT_LISTEN="$(ss -ltn 2>/dev/null | awk 'NR>1{print $4}' | grep -oE '[0-9]+$' | sort -un)"
  # who holds the shared 8080? (answers "which worktree grabbed 8080")
  _WT_8080_OWNER=""
  local pid8080; pid8080="$(lsof -ti :8080 -sTCP:LISTEN -P 2>/dev/null | head -1)"
  [ -n "$pid8080" ] && _WT_8080_OWNER="$(pwdx "$pid8080" 2>/dev/null | sed 's/^[0-9]*: //')"
  # foreground `functions serve` watchers: pid<TAB>cwd<TAB>args, one entry per
  # worktree (a single serve session spawns npm/sh/node/binary, all sharing cwd).
  _WT_SERVE=""
  local -A _wt_seen_cwd=()
  local line spid scwd sargs
  while IFS= read -r line; do
    spid="${line%% *}"
    [ -n "$spid" ] || continue
    scwd="$(pwdx "$spid" 2>/dev/null | sed 's/^[0-9]*: //')"
    [ -n "$scwd" ] || continue
    [ -n "${_wt_seen_cwd[$scwd]:-}" ] && continue
    _wt_seen_cwd[$scwd]=1
    sargs="${line#* }"; sargs="${sargs:0:100}"
    _WT_SERVE+="${spid}"$'\t'"${scwd}"$'\t'"${sargs}"$'\n'
  done < <(ps -eo pid,args 2>/dev/null | grep -F 'functions serve' | grep -v grep)
  _WT_STATE_LOADED=1
}

# host port of supabase_studio_<pid> (->3000); empty if stack not up
_wt_studio_port() {
  [ -n "$1" ] || return 0
  echo "$_WT_DPS" | awk -F'\t' -v n="supabase_studio_$1" '$1==n{print $2}' \
    | grep -oE '0\.0\.0\.0:[0-9]+->3000' | head -1 | sed -E 's/.*:([0-9]+)->.*/\1/'
}

# host port of supabase_kong_<pid> (->8000) — the API/functions gateway
_wt_api_port() {
  [ -n "$1" ] || return 0
  echo "$_WT_DPS" | awk -F'\t' -v n="supabase_kong_$1" '$1==n{print $2}' \
    | grep -oE '0\.0\.0\.0:[0-9]+->8000' | head -1 | sed -E 's/.*:([0-9]+)->.*/\1/'
}

# 1 if supabase_edge_runtime_<pid> is Up, else 0
_wt_edge_up() {
  [ -n "$1" ] || { echo 0; return; }
  echo "$_WT_DPS" | awk -F'\t' -v n="supabase_edge_runtime_$1" '$1==n{print $3}' \
    | grep -qi '^Up' && echo 1 || echo 0
}

_wt_is_listening() { echo "$_WT_LISTEN" | grep -qxF "$1"; }

# all project_ids with docker resources (containers + volumes), one per line
_wt_docker_pids() {
  _wt_state_init
  {
    printf '%s\n' "$_WT_DPS" | awk -F'\t' '{print $1}' | sed -E 's/^supabase_[a-z_]+_//'
    printf '%s\n' "$_WT_DVL" | sed -E 's/^supabase_[a-z_]+_//'
  } | grep -v '^$' | sort -u
}

# Kill any `supabase functions serve` watcher whose cwd is the given worktree
# path. A serve session spans npm/sh/node/binary (all sharing cwd) — collect and
# kill them as a group: SIGTERM, brief grace, then SIGKILL stragglers. Used by
# `wt rm` to tear down the watcher alongside the stack.
_wt_kill_serve_for_path() {
  local path="$1" kpid kcwd klist=""
  while IFS= read -r kpid; do
    [ -n "$kpid" ] || continue
    kcwd="$(pwdx "$kpid" 2>/dev/null | sed 's/^[0-9]*: //')"
    [ "$kcwd" = "$path" ] && klist+=" $kpid"
  done < <(pgrep -f 'functions serve' 2>/dev/null)
  [ -z "$klist" ] && return 0
  # shellcheck disable=SC2086  # intentional word-split over the pid list
  kill $klist 2>/dev/null
  sleep 0.3 2>/dev/null || true
  # shellcheck disable=SC2086
  kill -9 $klist 2>/dev/null
  echo "Stopped functions-serve watcher in $(basename "$path")"
}

# orphan project_ids: docker resources with no git-registered worktree claiming
# them. `git worktree list` is the authority for ownership — a worktree git no
# longer lists (e.g. a half-removed one) has no owner, so its stack is an orphan.
# (Half-removed worktrees are prevented at the source in `wt rm`, not papered
# over here by scanning the filesystem — that would mis-own unrelated configs.)
_wt_orphan_ids() {
  _wt_state_init
  local live
  live="$(while IFS=$'\t' read -r _ _ p; do _wt_pid_for_path "$p"; done < <(_wt_entries) | sort -u)"
  # Safety: if git lists no worktrees we're outside the cora repo and cannot tell
  # owned from orphan — flagging every docker stack would be catastrophic.
  if [ -z "$live" ]; then
    echo 'wt: git lists no cora worktrees — run from the cora repo (are you outside it?)' >&2
    return 0
  fi
  comm -13 <(printf '%s\n' "$live") <(_wt_docker_pids) | grep -v '^$'
}

# vite/dev-server column for a worktree path. The leading glyph is the only
# running signal: bullet = one or more vite dev servers for this worktree are
# bound now, ring = idle. Sticky 9xxx worktrees list every bound port in the
# base/+1/+2 band (dev/dev:local/dev:preview), comma-joined; idle shows the base.
# * = legacy 8080 band (no sticky .vite-port); strictPort means only the 8080
# owner can ever show the running glyph.
_wt_render_vite() {
  local path="$1" vp p bound=""
  vp="$(_wt_vite_port_for_path "$path")"
  if [ -z "$vp" ]; then
    # no sticky port: main checkout (.git dir) legitimately owns 8080; any other
    # linked worktree sharing 8080 gets * (strictPort: only one can bind it).
    local star="*"; [ -d "$path/.git" ] && star=""
    if _wt_is_listening 8080 && [ "$_WT_8080_OWNER" = "$path" ]; then
      printf '●8080'
    else
      printf '○8080%s' "$star"
    fi
  else
    # sticky 9xxx: collect every bound port across base/+1/+2, comma-joined.
    for p in $((vp)) $((vp + 1)) $((vp + 2)); do _wt_is_listening "$p" && bound="${bound:+$bound,}$p"; done
    [ -n "$bound" ] && printf '●%s' "$bound" || printf '○%s' "$vp"
  fi
}

# supabase column for a worktree path (studio url when up, else ·)
_wt_render_supabase() {
  local pid sp; pid="$(_wt_pid_for_path "$1")"
  [ -n "$pid" ] || { printf '·'; return; }
  sp="$(_wt_studio_port "$pid")"
  [ -n "$sp" ] && printf 'http://localhost:%s' "$sp" || printf '·'
}
# proxy dev URL host for a worktree (feat-x.cora.test); empty for a legacy
# worktree with no routeable port (no .vite-port -> wt adopt).
_wt_url_for() {
  local path="$1" app="${2:-}" port name
  if [ -d "$path/.git" ]; then port=8080
  else port="$(_wt_vite_port_for_path "$path")"; fi
  [ -n "$port" ] && [ -n "$app" ] || return 0
  name="$(basename "$path")"
  printf '%s.%s.test' "$(_wt_slug "$name")" "$app"
}

# name<TAB>branch<TAB>path<TAB>vite<TAB>supabase  (lookups computed once)
_wt_rich_entries() {
  _wt_state_init
  local name branch path vite sb url app
  app="$(_wt_app_name)"
  while IFS=$'\t' read -r name branch path; do
    [ -n "$path" ] || continue
    vite="$(_wt_render_vite "$path")"
    sb="$(_wt_render_supabase "$path")"
    url="$(_wt_url_for "$path" "$app")"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$branch" "$path" "$vite" "$sb" "$url"
  done < <(_wt_entries)
}

# compact header for the fzf picker
_wt_fzf_header() {
  _wt_state_init
  local orphan_n edge_n
  orphan_n="$(_wt_orphan_ids | grep -c .)"
  edge_n="$(printf '%s' "$_WT_SERVE" | grep -c .)"
  local h=''
  (( orphan_n > 0 )) && h+="⚠ ${orphan_n} orphan(s): wt reap  "
  (( edge_n > 0 )) && h+="⚡ ${edge_n} edge serve  "
  h+='● running  ○ idle  *=no sticky port (8080 band)  - =no URL (wt adopt)'
  printf '%s' "$h"
}

# full orphan footer (for wt list): stacks with no git-registered worktree.
_wt_orphan_report() {
  local orphan id has_up sp
  orphan="$(_wt_orphan_ids)"
  [ -n "$orphan" ] || return 0
  echo
  echo '⚠ ORPHANED supabase (no git worktree owns this stack — safe to reap):'
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    has_up=0
    echo "$_WT_DPS" | awk -F'\t' -v id="$id" '$1 ~ "_"id"$"{print $3}' | grep -qi '^Up' && has_up=1
    sp="$(_wt_studio_port "$id")"
    if [ "$has_up" = 1 ]; then
      [ -n "$sp" ] && printf '   %-40s %-9s %s\n' "$id" running "http://localhost:$sp" \
                   || printf '   %-40s %-9s %s\n' "$id" running '(no studio)'
    else
      printf '   %-40s %-9s %s\n' "$id" stopped 'leftover volume'
    fi
  done <<<"$orphan"
  echo '   → wt reap   (fzf)   ·   wt reap --all   ·   wt reap --dry-run'
}

# edge-fn watcher section (for wt list)
_wt_edge_report() {
  [ -n "$_WT_SERVE" ] || return 0
  echo
  echo '⚡ EDGE FN SERVE (foreground watchers live):'
  local pid cwd args slug wpid api rt url t
  local -a toks
  while IFS=$'\t' read -r pid cwd args; do
    [ -n "$pid" ] || continue
    slug=""
    read -ra toks <<<"${args#*functions serve}"
    for t in "${toks[@]}"; do case "$t" in --*) continue;; esac; slug="$t"; break; done
    [ -z "$slug" ] && slug=all
    wpid="$(_wt_pid_for_path "$cwd")"
    api="$(_wt_api_port "$wpid")"
    rt="$(_wt_edge_up "$wpid")"; [ "$rt" = 1 ] && rt='✓' || rt='✗'
    if [ -n "$api" ]; then
      if [ "$slug" = all ]; then url="http://localhost:$api/functions/v1/<slug>"; else url="http://localhost:$api/functions/v1/$slug"; fi
    else url='(stack down)'; fi
    printf '   %-34s %-12s → %-58s runtime %s\n' "$(basename "$cwd")" "$slug" "$url" "$rt"
  done <<<"$_WT_SERVE"
}

# ============================================================================
# wt — local dev DNS via Caddy. Visit <worktree>.<app>.test (plus -local /
# -preview variants) instead of localhost:<port>. `wt proxy` rewrites a managed
# /etc/hosts block (glibc checks `files` before Tailscale DNS, so this wins with
# zero resolver conflict) plus /etc/caddy/wt-routes.caddy, then reloads caddy.
# Subdomains key off the worktree NAME (not branch), so they survive a checkout.
# ============================================================================

# slugify a worktree name into one DNS label (lowercase [a-z0-9-])
_wt_slug() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'
}

# per-app DNS zone, e.g. "cora.test": basename of the repo's main checkout,
# resolved from the shared git-common-dir (the main worktree's .git).
_wt_app_name() {
  local cd
  cd="$(git rev-parse --git-common-dir 2>/dev/null)" || return 1
  cd="$(cd "$cd" && pwd -P)"; cd="${cd%/.git}"
  basename "$cd"
}

# Emit "<subdomain>\t<port>" for every routeable worktree dev mode
# (dev / -local=+1 / -preview=+2). Main checkout uses 8080; linked worktrees use
# their .vite-port; legacy linked worktrees without one are skipped (wt adopt).
_wt_routes() {
  local app zone name branch path port sub m p
  app="$(_wt_app_name)" || return 1
  zone="${app}.test"
  _wt_entries | while IFS=$'\t' read -r name branch path; do
    [ -n "$path" ] || continue
    if [ -d "$path/.git" ]; then port=8080
    else port="$(_wt_vite_port_for_path "$path")"; fi
    if [ -z "$port" ]; then
      printf 'wt proxy: skip %s (no .vite-port -- run: wt adopt %s)\n' "$name" "$name" >&2
      continue
    fi
    sub="$(_wt_slug "$name")"   # <slug>.<app>.test (main is cora.cora.test by design)
    for m in '' '-local' '-preview'; do
      p=$port
      [ "$m" = '-local' ] && p=$((port + 1))
      [ "$m" = '-preview' ] && p=$((port + 2))
      printf '%s%s.%s\t%s\n' "$sub" "$m" "$zone" "$p"
    done
  done
}

# Regenerate /etc/hosts (managed block) + /etc/caddy/wt-routes.caddy, reload caddy.
_wt_proxy_apply() {
  local routes hosts caddy tmp
  routes="$(_wt_routes)"
  hosts="$(printf '%s' "$routes" | awk -F'\t' '{print "127.0.0.1 "$1}' | sort -u)"
  caddy="$(printf '%s' "$routes" | awk -F'\t' '{printf "%s {\n\ttls internal\n\treverse_proxy 127.0.0.1:%s\n}\n", $1, $2}')"
  # rewrite the managed /etc/hosts block, preserving everything outside it
  tmp="$(mktemp)"
  awk '/^# BEGIN wt-proxy/{f=1} !f{print} /^# END wt-proxy/{f=0}' /etc/hosts > "$tmp"
  { echo "# BEGIN wt-proxy (managed by wt proxy)"; printf '%s\n' "$hosts"; echo "# END wt-proxy"; } >> "$tmp"
  sudo cp "$tmp" /etc/hosts && rm -f "$tmp"
  printf '%s' "$caddy" | sudo tee /etc/caddy/wt-routes.caddy >/dev/null
  sudo systemctl reload caddy
  echo "Routes:"
  printf '%s' "$routes" | awk -F'\t' '{printf "  https://%s -> %s\n", $1, $2}'
}

# Assign a sticky 9xxx .vite-port to legacy linked worktrees (all, or one name),
# mirroring new-worktree's allocation (max existing + 10, min 9000).
_wt_adopt() {
  local query="${1:-}" name branch path v out vmax
  # highest existing sticky port (assign max+10, min 9000), mirroring new-worktree
  vmax=$(_wt_entries | while IFS=$'\t' read -r name branch path; do
    [ -f "$path/.vite-port" ] || continue
    v="$(head -1 "$path/.vite-port" 2>/dev/null | tr -d '[:space:]')"
    [[ "$v" =~ ^[0-9]+$ ]] && echo "$v"
  done | sort -n | tail -1)
  vmax="${vmax:-8990}"
  out=$(_wt_entries | while IFS=$'\t' read -r name branch path; do
    [ -n "$path" ] || continue
    { [ -d "$path/.git" ] || [ -f "$path/.vite-port" ]; } && continue
    [ -n "$query" ] && [ "$query" != "$name" ] && continue
    vmax=$((vmax + 10))
    printf '%s' "$vmax" > "$path/.vite-port"
    echo "  adopted $name -> .vite-port=$vmax (dev/local/preview = $vmax/$((vmax+1))/$((vmax+2)))"
  done)
  if [ -n "$out" ]; then printf '%s\n' "$out"; else echo "  nothing to adopt (all linked worktrees already have a sticky .vite-port)."; fi
}

wt() {
  local arg="${1:-}"
  [ -z "$arg" ] && arg="go"

  _WT_STATE_LOADED=0   # fresh probe snapshot per wt invocation (the cache
                       # would otherwise persist for the shell lifetime and
                       # hide a dev server started since the last wt call)
  case "$arg" in
    go)
      local fzf_query="$2" target
      # If a query is given, try exact/substring match first (instant cd)
      if [ -n "$fzf_query" ]; then
        local matches path
        matches="$(_wt_entries | awk -F'\t' -v q="$fzf_query" 'index($1,q)')"
        local count; count="$(printf '%s\n' "$matches" | grep -c .)"
        if [ "$count" -eq 1 ]; then
          target="$(printf '%s' "$matches" | awk -F'\t' '{print $3}')"
        elif [ "$count" -gt 1 ]; then
          target="$(_wt_fzf_path "$fzf_query")"
        else
          echo "wt: no worktree matches '$fzf_query'" >&2
          _wt_entries | awk -F'\t' '{print "  "$1}' >&2
          return 1
        fi
      else
        target="$(_wt_fzf_path)"
      fi
      [ -n "$target" ] && cd "$target" || return 1
      ;;
    ls|list)
      _wt_state_init
      # Dynamic-width table: column(1) sizes each column to its widest cell
      # (header included), so long worktree/branch names never misalign the
      # DEV/supabase columns. Branch collapses to "-" when it merely repeats
      # the worktree name. DEV column leads with a glyph (● bound / ○ idle)
      # before the configured base port; *=no sticky .vite-port (8080 band).
      { printf 'WORKTREE\tBRANCH\tDEV\tURL\tsupabase\n'
        _wt_rich_entries | awk -F'\t' '{print $1"\t"($2==$1?"-":$2)"\t"$4"\t"($6==""?"-":$6)"\t"$5}'
      } | column -t -s$'\t' -o '  '
      echo
      echo '  dev=base · dev:local=base+1 · dev:preview=base+2 · ● running  ○ idle  ·  *=no sticky port (8080 band)  ·  - =no URL (wt adopt)'
      _wt_orphan_report
      _wt_edge_report
      ;;
    new)
      shift  # drop the "new" so "$@" is just the flags + branch name
      [ "$#" -eq 0 ] && { echo "wt new: branch name required (e.g. wt new feat/thing)" >&2; return 1; }
      local before after new_path
      before="$(_wt_entries | awk -F'\t' '{print $3}' | sort)"
      new-worktree "$@" || return $?
      after="$(_wt_entries | awk -F'\t' '{print $3}' | sort)"
      new_path="$(comm -13 <(echo "$before") <(echo "$after") | head -1)"
      if [ -n "$new_path" ]; then
        echo
        echo "→ cd $(basename "$new_path")"
        cd "$new_path"
      fi
      ;;
    rm|remove)
      shift  # drop "rm" so "$@" is the optional flags + query
      local force=0 keep_branch=0 keep_stack=0 query
      while [ $# -gt 0 ]; do
        case "$1" in
          -f|--force)       force=1;       shift;;
          -k|--keep-branch) keep_branch=1; shift;;
          --keep-stack)     keep_stack=1;  shift;;
          --)               shift; query="${1:-}"; break;;
          *)                query="$1";    shift;;
        esac
      done

      local matches count path name branch
      if [ -n "$query" ]; then
        matches="$(_wt_entries | awk -F'\t' -v q="$query" 'index($1,q)')"
        count="$(printf '%s\n' "$matches" | grep -c .)"
        if [ "$count" -eq 0 ]; then
          echo "wt: no worktree matches '$query'" >&2; return 1
        elif [ "$count" -eq 1 ]; then
          path="$(printf '%s' "$matches" | awk -F'\t' '{print $3}')"
          branch="$(printf '%s' "$matches" | awk -F'\t' '{print $2}')"
        else
          path="$(_wt_fzf_path "$query")"
          [ -z "$path" ] && return 1
        fi
      else
        path="$(_wt_fzf_path)"
        [ -z "$path" ] && return 1
      fi
      name="$(basename "$path")"
      # fzf-chosen paths don't carry the branch — look it up from the entries
      branch="${branch:-$(_wt_entries | awk -F'\t' -v p="$path" '$3 == p {print $2; exit}')}"

      # Tear down this worktree's local Supabase stack + volume before removing
      # the dir (config.toml must still exist to resolve project_id). Skipped with
      # --keep-stack. Volumes are isolated per project_id, so this only touches
      # THIS worktree's data — never main or a sibling.
      if (( ! keep_stack )); then
        local rmpid; rmpid="$(_wt_pid_for_path "$path")"
        if [ -n "$rmpid" ]; then
          if docker ps --format '{{.Names}}' 2>/dev/null | grep -qE "_${rmpid}$"; then
            echo "Stopping supabase stack '$rmpid' + wiping volume (--no-backup)…"
            ( cd "$path" && npx supabase stop --no-backup ) || echo "wt: supabase stop failed — continuing" >&2
          else
            docker volume rm "supabase_db_${rmpid}" >/dev/null 2>&1 \
              && echo "Removed dangling volume supabase_db_${rmpid}"
          fi
        fi
        # stop the functions-serve watcher for this worktree alongside the stack
        _wt_kill_serve_for_path "$path"
      fi

      echo "Removing worktree '$name'..."
      git worktree remove "$path" 2>/dev/null || git worktree remove --force "$path" 2>/dev/null
      # Judge success by whether git still lists the worktree — NOT by exit code.
      # `git worktree remove` can deregister a worktree then fail to delete a busy
      # working dir (the edge-runtime container bind-mounts supabase/functions/),
      # leaving a half-removed worktree (dir present, git blind). Teardown above
      # stops the stack to release those mounts; this backstop removes any stray
      # dir once git has deregistered, so we never leave that broken state.
      if git worktree list --porcelain 2>/dev/null \
        | awk -v p="$path" '$1=="worktree" && $2==p {f=1} END{exit !f}'; then
        echo "wt: failed to remove worktree '$name' (still registered)." >&2
        return 1
      fi
      if [ -e "$path" ]; then
        rm -rf "$path" 2>/dev/null \
          || echo "wt: deregistered, but $path still on disk (busy file?) — remove manually" >&2
      fi
      echo "Removed $path"

      # Branch cleanup — also delete the worktree's branch. Must run AFTER the
      # worktree is removed: git refuses to delete a branch still checked out in
      # a worktree. Default is safe -d (refuses unmerged → never loses work);
      # -f forces -D; -k keeps the branch.
      if (( keep_branch )); then
        echo "Keeping branch '${branch}' (--keep-branch)."
      elif [ -z "$branch" ] || [ "$branch" = "detached" ]; then
        : # detached-HEAD worktree — no branch to delete
      else
        local err
        if (( force )); then
          if err="$(git branch -D "$branch" 2>&1)"; then
            echo "Deleted branch '$branch' (forced -D)."
          else
            echo "wt: could not force-delete branch '$branch':" >&2
            printf '%s\n' "$err" | sed 's/^/  /' >&2
          fi
        else
          if err="$(git branch -d "$branch" 2>&1)"; then
            echo "Deleted branch '$branch' (safe -d)."
          else
            echo "wt: branch '$branch' not deleted:" >&2
            printf '%s\n' "$err" | sed 's/^/  /' >&2
            echo "  → force-delete: git branch -D '$branch'   |   keep: wt rm -k '$name'" >&2
          fi
        fi
      fi
      ;;
    prune)
      git worktree prune "$@"
      echo "Pruned stale worktree refs."
      ;;
    reap)
      # Remove orphaned Supabase resources (containers/volumes/network whose
      # project_id matches no live worktree) by project_id, via raw docker —
      # there's no worktree cwd to `supabase stop` from.
      git rev-parse --git-dir >/dev/null 2>&1 || {
        echo 'wt reap: must run from within the cora repo (or one of its worktrees).' >&2
        return 1
      }
      local dry=0 all=0
      shift
      while [ $# -gt 0 ]; do
        case "$1" in --dry-run) dry=1; shift;; --all) all=1; shift;; *) shift;; esac
      done
      _wt_state_init
      local orphan targets
      orphan="$(_wt_orphan_ids)"
      if [ -z "$orphan" ]; then
        echo "No orphaned supabase resources."
        return 0
      fi
      echo "Orphaned supabase project_ids (docker resources, no worktree):"
      printf '%s\n' "$orphan" | sed 's/^/  - /'
      echo
      if (( ! all )); then
        targets="$(printf '%s\n' "$orphan" \
          | fzf --prompt='reap> ' --multi --height=40% --reverse \
                --header='Tab to mark · Enter to reap · Esc to abort' || true)"
        [ -z "$targets" ] && { echo "Aborted."; return 1; }
      else
        targets="$orphan"
      fi
      local id ctrs vols net
      while IFS= read -r id; do
        [ -n "$id" ] || continue
        ctrs="$(docker ps -a --format '{{.Names}}' 2>/dev/null | awk -v id="$id" '$0 ~ "_"id"$"')"
        vols="$(docker volume ls --format '{{.Name}}' 2>/dev/null | awk -v id="$id" '$0 ~ "_"id"$"')"
        net="supabase_network_${id}"
        if (( dry )); then
          echo "→ would reap $id"
          [ -n "$ctrs" ] && echo "$ctrs" | paste -sd' ' - | sed 's/^/    containers: /'
          [ -n "$vols" ] && echo "$vols" | paste -sd' ' - | sed 's/^/    volumes:    /'
          docker network ls --format '{{.Name}}' 2>/dev/null | grep -qx "$net" && echo "    network:    $net"
        else
          echo "→ reaping $id"
          # shellcheck disable=SC2086  # intentional word-split over container/volume lists
          [ -n "$ctrs" ] && { docker stop $ctrs >/dev/null 2>&1; docker rm -f $ctrs >/dev/null 2>&1; }
          [ -n "$vols" ] && docker volume rm $vols >/dev/null 2>&1
          docker network rm "$net" >/dev/null 2>&1
        fi
      done <<<"$targets"
      if (( dry )); then echo "(dry-run — nothing removed; re-run without --dry-run)"; fi
      ;;
    proxy)
      git rev-parse --git-dir >/dev/null 2>&1 || { echo 'wt proxy: run from within a git repo.' >&2; return 1; }
      command -v caddy >/dev/null 2>&1 || { echo 'wt proxy: caddy is not installed.' >&2; return 1; }
      _wt_proxy_apply
      ;;
    adopt)
      git rev-parse --git-dir >/dev/null 2>&1 || { echo 'wt adopt: run from within a git repo.' >&2; return 1; }
      _wt_adopt "$2"
      ;;
    help|-h|--help)
      cat <<'HELP'
wt — worktree navigator (jump is the default)

  wt                fzf-pick a worktree → cd  (rows show vite port + supabase url)
  wt feat-mcp       substring-match → cd (1 match: instant, N: fzf filtered)
  wt new <branch>   create a worktree via new-worktree (assigns a 9xxx vite port),
                    then cd into it (--base, --clean, etc. pass through)
  wt list | wt ls   full status: vite ports, supabase studio urls, edge-fn watchers,
                    orphaned supabase stacks
  wt rm [name]      remove worktree + tear down its supabase stack/volume + delete
                    branch (safe git branch -d)
  wt rm -f [name]   same, but force-delete the branch (-D) even if unmerged
  wt rm -k [name]   remove worktree only, keep the branch
  wt rm --keep-stack [name]  remove worktree but leave its supabase stack running
  wt reap           fzf-pick orphaned supabase stacks (no worktree) → stop + wipe
  wt reap --all     reap every orphan without prompting
  wt reap --dry-run preview what reaping would remove
  wt prune          prune stale worktree refs
  wt proxy         (re)generate local dev DNS: <worktree>.cora.test -> vite port
                    via Caddy (tls internal). Re-run after wt new / rm / adopt.
  wt adopt [name]  assign a sticky .vite-port (9xxx) to a legacy worktree so it
                    gets its own dev URL too (all, or one worktree name)

Jump mode is the default — any unrecognized arg is treated as a substring to
match against worktree names. So `wt feat` == `wt go feat`. Vite dev ports are
sticky per worktree (9000/9010/…); main stays on 8080. dev / dev:local /
dev:preview bind base / base+1 / base+2.
HELP
      ;;
    *)
      # Unrecognized arg → treat as substring jump (so `wt feat-mcp` works)
      wt go "$arg"
      ;;
  esac
}

# Print a GCS bucket as a tree
gsutil-tree() {
  local bucket_path="${1#gs://}"
  gsutil ls -r "gs://$bucket_path" | awk '
    BEGIN { path[0] = "" }
    /:$/ {
      dir = substr($0, 1, length($0)-1)
      if (dir == ".") { depth = 0; path[0] = "" }
      else { depth = gsub(/\//, "/", dir); path[depth] = dir }
      if (depth > 0) {
        for (i = 1; i < depth; i++) printf "| "
        printf "|____" dir; gsub(/.*\//, "", dir); print dir
      }
    }
    /^$/ { next }
    !/^[[:space:]]*$/ && !/:$/ {
      for (i = 0; i < depth; i++) printf "| "
      print "|____" $0
    }'
}

# Cursor: prepend anti-throttle flags so background agent/build work isn't
# throttled when the screen locks/blanks (mirrors ~/.local/share/applications/
# cursor.desktop). Delete this function to restore stock terminal behavior.
cursor() {
  command cursor --disable-background-timer-throttling \
                 --disable-renderer-backgrounding \
                 --disable-backgrounding-occluded-windows "$@"
}


# Launch claude in z.ai glm mode
z() {
    claude --settings ~/.claude/settings.json.zai
}

# Wrap `bun install`/`add` (incl. -g) with bunr: blocked lifecycle scripts get
# reviewed by claude — safe auto-trusted, suspicious prompted [y/N], malicious
# left blocked. Everything else passes to the real bun unchanged. Interactive
# shells only, so scripts/tools that invoke bun aren't intercepted.
# Bypass one call:  BUNR=0 bun add ...   or   command bun add ...
bun() {
  if [[ $- == *i* ]] && [ "${BUNR:-1}" != "0" ]; then
    case "${1:-}" in
      install|add|i|a) command bunr "$@"; return $? ;;
    esac
  fi
  command bun "$@"
}

# ============================================================================
# box — remote sticky boxes (Sprites). wt-shaped; does not touch wt.
# Implementation: ~/.local/bin/box  |  help: box help
# ============================================================================
box() { command box "$@"; }

# ============================================================================
# ebox — E2B boxes with human names. Parallel to `box` (Sprites). Leaves wt alone.
# Implementation: ~/.local/bin/ebox  |  help: ebox help
# ============================================================================
ebox() { command ebox "$@"; }
