# System-wide .bashrc file for interactive bash(1) shells.

# To enable the settings / commands in this file for login shells as well,
# this file has to be sourced in /etc/profile.

# If not running interactively, don't do anything
[ -z "$PS1" ] && return

# Reset the kitty keyboard protocol on every new shell. Neovim 0.10 enables
# CSI u at startup; if it crashes or is killed, VTE stays stuck in that mode
# and ESC is re-encoded as CSI 27 u -- which most apps (vim, less, fzf, ...)
# do not recognize, so ESC silently stops working inside them. This pops the
# protocol stack and disables all flags, restoring raw key delivery.
printf '\033[<u\033[>0u' 2>/dev/null
# ble.sh — must be the very FIRST thing (before any other readline/prompt setup)
# so it can hook the line editor. --noattach defers actual attachment until the
# end of the file (after starship). fish/zsh-style autosuggestions + syntax hl.
if [[ $- == *i* ]] && [ -f "$HOME/.local/share/blesh/ble.sh" ]; then
  source "$HOME/.local/share/blesh/ble.sh" --noattach
fi

# ============================================================================
# BASH HISTORY CONFIGURATION
# ============================================================================
# Keep a large history
export HISTSIZE=10000                    # Commands in memory
export HISTFILESIZE=20000                # Commands in history file

# Append to history file instead of overwriting (critical for multiple terminals)
shopt -s histappend

# Avoid duplicates and commands starting with space
export HISTCONTROL=ignoreboth:erasedups

# Add timestamps to history
export HISTTIMEFORMAT='%F %T  '

# Save history after each command (prevents loss on crashes/forced closures)
# This is crucial for Cursor/IDE terminals that may close unexpectedly
PROMPT_COMMAND='history -a'

# ============================================================================

# check the window size after each command and, if necessary,
# update the values of LINES and COLUMNS.
shopt -s checkwinsize

# set variable identifying the chroot you work in (used in the prompt below)
if [ -z "${debian_chroot:-}" ] && [ -r /etc/debian_chroot ]; then
    debian_chroot=$(cat /etc/debian_chroot)
fi

# set a fancy prompt (non-color, overwrite the one in /etc/profile)
# but only if not SUDOing and have SUDO_PS1 set; then assume smart user.
if ! [ -n "${SUDO_USER}" -a -n "${SUDO_PS1}" ]; then
  PS1='${debian_chroot:+($debian_chroot)}\u@\h:\w\$ '
fi

# Commented out, don't overwrite xterm -T "title" -n "icontitle" by default.
# If this is an xterm set the title to user@host:dir
#case "$TERM" in
#xterm*|rxvt*)
#    PROMPT_COMMAND='echo -ne "\033]0;${USER}@${HOSTNAME}: ${PWD}\007"'
#    ;;
#*)
#    ;;
#esac

# enable bash completion in interactive shells (the framework; _completion_loader
# becomes available for lazy per-command loading of the 1223 completion scripts)
if ! shopt -oq posix; then
  if [ -f /usr/share/bash-completion/bash_completion ]; then
    . /usr/share/bash-completion/bash_completion
  elif [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
  fi
fi

# sudo hint
if [ ! -e "$HOME/.sudo_as_admin_successful" ] && [ ! -e "$HOME/.hushlogin" ] ; then
    case " $(groups) " in *\ admin\ *|*\ sudo\ *)
    if [ -x /usr/bin/sudo ]; then
	cat <<-EOF
	To run a command as administrator (user "root"), use "sudo <command>".
	See "man sudo_root" for details.
	
	EOF
    fi
    esac
fi

# if the command-not-found package is installed, use it
if [ -x /usr/lib/command-not-found -o -x /usr/share/command-not-found/command-not-found ]; then
	function command_not_found_handle {
	        # check because c-n-f could've been removed in the meantime
                if [ -x /usr/lib/command-not-found ]; then
		   /usr/lib/command-not-found -- "$1"
                   return $?
                elif [ -x /usr/share/command-not-found/command-not-found ]; then
		   /usr/share/command-not-found/command-not-found -- "$1"
                   return $?
		else
		   printf "%s: command not found\n" "$1" >&2
		   return 127
		fi
	}
fi
# ============================================================================
# SOURCE custom aliases, functions, then completions (order matters)
# ============================================================================

# Source bash aliases if file exists
if [ -f ~/.bash_aliases ]; then
    . ~/.bash_aliases
fi

# Source bash functions if file exists
if [ -f ~/.bash_functions ]; then
    . ~/.bash_functions
fi

# Source custom completions LAST (after bash-completion framework, aliases, and
# functions are all loaded so it can clone completions onto aliases)
if [ -f ~/.bash_completions ]; then
    . ~/.bash_completions
fi

# ============================================================================
# PATH CONFIGURATION
# All PATH modifications live here so they work in both login and non-login
# shells. WSL-native tools are prepended so they always beat Windows paths.
# ============================================================================

# bun (package manager / runtime)
# BUN_INSTALL anchors the runtime AND the global install layout:
#   bin shims -> $BUN_INSTALL/bin            (~/.bun/bin)
#   packages  -> $BUN_INSTALL/install/global (~/.bun/install/global)
# Without it, bun 1.3.x runs unanchored and drops globals in ~/node_modules
# with bins in ~/.cache/.bun/bin (XDG fallback). See oven-sh/bun install.sh.
export BUN_INSTALL="$HOME/.bun"
if [ -d "$BUN_INSTALL/bin" ] ; then
    PATH="$BUN_INSTALL/bin:$PATH"
fi

# nvm (Node.js version manager)
export NVM_DIR="$HOME/.config/nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# pnpm
if [ -d "$HOME/.local/share/pnpm/bin" ] ; then
    PATH="$HOME/.local/share/pnpm/bin:$PATH"
fi

# AWS CLI
if [ -d "$HOME/.local/aws-cli/v2/current/dist" ] ; then
    PATH="$HOME/.local/aws-cli/v2/current/dist:$PATH"
elif [ -d "$HOME/.local/aws-cli/v2/2.32.23/dist" ] ; then
    PATH="$HOME/.local/aws-cli/v2/2.32.23/dist:$PATH"
fi

# Snap binaries
if [ -d "/snap/bin" ] ; then
    PATH="/snap/bin:$PATH"
fi

# Android SDK
export ANDROID_HOME=$HOME/Android/sdk
PATH="$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/build-tools/34.0.0"

# Go packages
if [ -d "$HOME/go/bin" ] ; then
    PATH="$HOME/go/bin:$PATH"
fi

# ~/.local/bin (agent-browser wrapper, user bins)
if [ -d "$HOME/.local/bin" ] ; then
    PATH="$HOME/.local/bin:$PATH"
fi

# Scripts dir (version-controlled text scripts, tracked in dotfiles repo).
if [ -d "$HOME/.local/scripts" ] ; then
    PATH="$HOME/.local/scripts:$PATH"
fi

export PATH

# ============================================================================
# fzf — wired through ble.sh integration modules (NOT `eval "$(fzf --bash)"`)
# because fzf's own bind calls are swallowed by ble.sh's line editor. The modules
# bind Ctrl-R/Ctrl-T/Alt-C into ble.sh's keymap. Plain-bash fallback if no ble.sh.
# ============================================================================
if [[ ${BLE_VERSION-} ]]; then
  _ble_contrib_fzf_base=/usr/share/doc/fzf/examples   # Debian's fzf script location
  ble-import integration/fzf-completion
  ble-import integration/fzf-key-bindings
elif [ -f /usr/share/doc/fzf/examples/key-bindings.bash ]; then
  . /usr/share/doc/fzf/examples/key-bindings.bash
  . /usr/share/doc/fzf/examples/completion.bash
fi

# ----------------------------------------------------------------------------
# Restore native bash-completion for commands fzf overwrote.
# fzf's completion setup (both its completion.bash AND ble.sh's fzf-completion
# integration) unconditionally stamps `_fzf_path_completion` onto every command
# in its "Anything" list — git, curl, scp, sftp, java, perl, python, tar, … —
# which CLOBBERS their real completions. Symptom: `git check<TAB>` completed
# file paths instead of `checkout`. This re-loads the native completion for any
# victim that actually has one; commands without a native script keep fzf's
# path fallback (correct). Must run AFTER fzf and BEFORE ble-attach so the right
# registration is in place when ble attaches.
#
# Separately: fzf also replaces bash-completion's `complete -D` lazy loader
# (`_comp_complete_load`) with `__fzf_default_completion` (path picker). Commands
# NOT in the Anything list (e.g. `gh`) never get stamped, so they never get
# restored above AND never lazy-load via -D — Tab falls through to fzf paths.
# Preload those explicitly here. Same loader, same timing, no new framework.
# ----------------------------------------------------------------------------
if declare -F _completion_loader >/dev/null 2>&1; then
  while read -r _cmd; do
    [ -n "$_cmd" ] && _completion_loader "$_cmd" 2>/dev/null
  done < <(complete -p 2>/dev/null | awk '/_fzf_path_completion/{print $NF}' | sort -u)
  # -D victims (not in fzf's Anything list; need explicit preload)
  _completion_loader gh 2>/dev/null
fi

# Starship prompt (git-aware, nerd-font powerline) — overrides PS1 above
eval "$(starship init bash)"

# Attach ble.sh last (after starship) so it wraps the prompt properly.
if [[ ${BLE_VERSION-} ]]; then
  ble-attach
fi
export PATH="$HOME/.deno/bin:$PATH"

# The next line updates PATH for the Google Cloud SDK.
if [ -f '/home/ahmed/google-cloud-sdk/path.bash.inc' ]; then . '/home/ahmed/google-cloud-sdk/path.bash.inc'; fi

# Added by Cap
export PATH="/home/ahmed/.cap/bin:$PATH"
